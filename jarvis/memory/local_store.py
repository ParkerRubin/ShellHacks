"""Durable encrypted mirror and transactional outbox. No network I/O here."""

import sqlite3
import threading
from pathlib import Path

from bson import json_util

from .models import now


class LocalStore:
    def __init__(self, path):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS documents (
                collection TEXT NOT NULL, id TEXT NOT NULL, user_id TEXT,
                timestamp REAL NOT NULL, expires REAL, body TEXT NOT NULL,
                PRIMARY KEY(collection, id));
            CREATE INDEX IF NOT EXISTS timeline ON documents(collection, user_id, timestamp DESC);
            CREATE TABLE IF NOT EXISTS outbox (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, collection TEXT NOT NULL,
                id TEXT NOT NULL, user_id TEXT, body TEXT NOT NULL,
                UNIQUE(collection, id));
            CREATE TABLE IF NOT EXISTS deleted_users (user_id TEXT PRIMARY KEY);
        """)
        self.db.commit()

    def is_deleted(self, user_id):
        with self.lock:
            return bool(
                user_id
                and self.db.execute(
                    "SELECT 1 FROM deleted_users WHERE user_id=?", (user_id,)
                ).fetchone()
            )

    def put(self, collection, doc, pending=True):
        user_id = doc.get("user_id") or (
            doc["_id"] if collection == "user_profiles" else None
        )
        stamp = doc.get("timestamp", doc.get("updated_at", now())).timestamp()
        expiry = doc.get("expires_at")
        body = json_util.dumps(doc)
        with self.lock, self.db:
            if self.is_deleted(user_id):
                return False
            self.db.execute(
                "INSERT OR REPLACE INTO documents VALUES (?, ?, ?, ?, ?, ?)",
                (
                    collection,
                    doc["_id"],
                    user_id,
                    stamp,
                    expiry.timestamp() if expiry else None,
                    body,
                ),
            )
            if pending:
                self.db.execute(
                    "INSERT OR REPLACE INTO outbox(collection,id,user_id,body) VALUES(?,?,?,?)",
                    (collection, doc["_id"], user_id, body),
                )
        return True

    def get(self, collection, record_id):
        with self.lock:
            row = self.db.execute(
                "SELECT body FROM documents WHERE collection=? AND id=?",
                (collection, record_id),
            ).fetchone()
        return (
            json_util.loads(row[0], json_options=json_util.JSONOptions(tz_aware=True))
            if row
            else None
        )

    def list(self, collection, user_id=None, limit=100, all_users=False):
        sql = "SELECT body FROM documents WHERE collection=? AND (expires IS NULL OR expires>?)"
        args = [collection, now().timestamp()]
        if not all_users:
            sql += " AND user_id IS ?"
            args.append(user_id)
        sql += " ORDER BY timestamp DESC LIMIT ?"
        args.append(limit)
        with self.lock:
            rows = self.db.execute(sql, args).fetchall()
        return [
            json_util.loads(row[0], json_options=json_util.JSONOptions(tz_aware=True))
            for row in rows
        ]

    def search(self, words, user_id=None, limit=50):
        """Search fixed public tags across the whole timeline before applying the limit."""
        if not words:
            return []
        placeholders = ",".join("?" for _ in words)
        sql = (
            "SELECT body FROM documents WHERE collection='interactions' AND user_id IS ? "
            "AND expires>? AND EXISTS (SELECT 1 FROM json_each(documents.body, '$.context.topics') "
            f"WHERE value IN ({placeholders})) ORDER BY timestamp DESC LIMIT ?"
        )
        with self.lock:
            rows = self.db.execute(
                sql, [user_id, now().timestamp(), *sorted(words), limit]
            ).fetchall()
        return [
            json_util.loads(row[0], json_options=json_util.JSONOptions(tz_aware=True))
            for row in rows
        ]

    def pending_embeddings(self, limit=100):
        with self.lock:
            rows = self.db.execute(
                "SELECT body FROM documents WHERE collection='interactions' AND expires>? "
                "AND json_extract(body, '$.embedding_pending')=1 ORDER BY timestamp LIMIT ?",
                (now().timestamp(), limit),
            ).fetchall()
        return [
            json_util.loads(row[0], json_options=json_util.JSONOptions(tz_aware=True))
            for row in rows
        ]

    def pending(self, limit=100):
        with self.lock:
            rows = self.db.execute(
                "SELECT seq,collection,id,body FROM outbox ORDER BY seq LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            (
                seq,
                col,
                rid,
                json_util.loads(
                    body, json_options=json_util.JSONOptions(tz_aware=True)
                ),
            )
            for seq, col, rid, body in rows
        ]

    def ack(self, seq):
        with self.lock, self.db:
            self.db.execute("DELETE FROM outbox WHERE seq=?", (seq,))

    def delete_user_data(self, user_id):
        with self.lock, self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO deleted_users VALUES (?)", (user_id,)
            )
            count = self.db.execute(
                "DELETE FROM documents WHERE user_id=?", (user_id,)
            ).rowcount
            self.db.execute("DELETE FROM outbox WHERE user_id=?", (user_id,))
            # Tombstone has no transcripts/biometrics; replay before further writes.
            self.db.execute(
                "INSERT OR IGNORE INTO outbox(collection,id,user_id,body) VALUES ('delete', ?, ?, ?)",
                (user_id, user_id, json_util.dumps({"user_id": user_id})),
            )
        return count

    def purge_expired(self):
        with self.lock, self.db:
            self.db.execute(
                "DELETE FROM outbox WHERE EXISTS (SELECT 1 FROM documents d WHERE "
                "d.collection=outbox.collection AND d.id=outbox.id AND d.expires<=?)",
                (now().timestamp(),),
            )
            return self.db.execute(
                "DELETE FROM documents WHERE expires<=?", (now().timestamp(),)
            ).rowcount

    def depth(self):
        with self.lock:
            return self.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0]

    def close(self):
        with self.lock:
            self.db.close()
