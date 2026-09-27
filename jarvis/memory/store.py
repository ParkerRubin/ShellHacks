import logging
import math
import threading
import time
from dataclasses import asdict
from datetime import timedelta
from functools import partial

from .crypto import FieldCipher
from .local_store import LocalStore
from .models import DeletionReport, HealthStatus, now
from .privacy import classify_privacy, extract_context
from .schemas import upgrade, validate

log = logging.getLogger(__name__)


class ResilientMemoryStore:
    """Local-first encrypted persistence; one serialized network replay worker.

    All writes and tombstones commit locally before any remote action. Network
    replay never holds the local lock, so callbacks and local recall stay fast.
    """

    def __init__(self, config, mongo=None, connection=None, embedder=None):
        self.config, self.mongo, self.connection = config, mongo, connection
        self.embedder = embedder
        self.cipher = FieldCipher(config.key)
        self.local = LocalStore(config.local_path)
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.replay_lock = threading.Lock()
        self.worker = None
        self.online = False
        self.hydrated = False
        self.purge_expired()

    def start(self):
        self.worker = threading.Thread(
            target=self._run, name="memory-health", daemon=True
        )
        self.worker.start()

    def _run(self):
        ping_at = health_at = purge_at = 0
        offline_since = time.monotonic()
        while not self.stop.is_set():
            clock = time.monotonic()
            try:
                if self.connection and clock >= ping_at:
                    self.online = self.connection.ping()
                    ping_at = clock + 30
                if self.online:
                    self.replay()
                    if not self.hydrated:
                        self.hydrate_profiles()
                    offline_since = clock
                if clock >= purge_at:
                    self.purge_expired()
                    self.backfill()
                    purge_at = clock + 3600
                if clock >= health_at:
                    log.info(
                        "memory_health state=%s outbox=%d",
                        self.health().state,
                        self.local.depth(),
                    )
                    if self.mongo and clock - offline_since > 300:
                        log.error("memory_offline prolonged=true")
                    health_at = clock + 60
            except Exception as exc:
                log.warning("memory_maintenance_failed type=%s", type(exc).__name__)
            self.wake.wait(1)
            self.wake.clear()

    def hydrate_profiles(self):
        """Recover consented identities after a fresh local install, without overwriting pending edits."""
        if not self.mongo:
            return
        for collection in ("user_profiles", "face_signatures"):
            for doc in self.mongo.db[collection].find({}):
                if self.stop.is_set():
                    return
                if self.local.get(collection, doc["_id"]) is None:
                    validate(collection, doc)
                    # Wrong-key/corrupt data must not enter the recognition cache.
                    if self._decode(collection, doc):
                        self.local.put(collection, doc, pending=False)
        self.purge_expired()
        self.hydrated = True

    def _write(self, collection, doc, private_fields):
        try:
            doc = self.cipher.encrypt_fields(doc, private_fields)
            validate(collection, doc)
            if not self.local.put(collection, doc, pending=self.mongo is not None):
                return ""
            self.wake.set()
            return doc["_id"]
        except Exception as exc:
            log.error(
                "memory_write_failed collection=%s type=%s",
                collection,
                type(exc).__name__,
            )
            return ""

    def replay(self):
        if not self.mongo or not self.replay_lock.acquire(blocking=False):
            return
        try:
            for seq, col, rid, doc in self.local.pending():
                if self.stop.is_set():
                    break
                try:
                    if col == "delete":
                        operation = partial(self.mongo.delete_user_data, doc["user_id"])
                    else:
                        # A delete racing an in-flight upsert is replayed after it.
                        user_id = doc.get("user_id") or (
                            rid if col == "user_profiles" else None
                        )
                        if self.local.is_deleted(user_id) or (
                            doc.get("expires_at") and doc["expires_at"] <= now()
                        ):
                            self.local.ack(seq)
                            continue
                        operation = partial(self.mongo.put, col, doc)
                    if self.connection:
                        self.connection.with_retry(operation)
                    else:
                        operation()
                    self.local.ack(seq)
                except Exception as exc:
                    self.online = False
                    log.warning("memory_replay_failed type=%s", type(exc).__name__)
                    break
        finally:
            self.replay_lock.release()

    def store_interaction(self, record):
        doc = asdict(record)
        user_id = doc["user_id"]
        profile = self.get_user_profile(user_id) if user_id else None
        consent = bool(profile and profile["consents"]["store_personal_data"])
        if user_id and not consent:
            return (
                ""  # Revoked/deleted identity must not return as anonymous queued text.
            )
        full_text = " ".join(
            [doc["input_text"], doc["ai_response"], doc["gemini_analysis"] or ""]
        )
        context = extract_context(full_text)
        privacy = classify_privacy(full_text, consent)
        if not consent:
            # Regex scrubbing is insufficient to anonymize free text. Persist tags only.
            doc.update(
                input_text="[anonymous topics] " + ", ".join(context["topics"]),
                ai_response="",
                gemini_analysis=None,
            )
            privacy = "public"
        doc.update(
            schema_version="1.0",
            expires_at=doc["timestamp"] + timedelta(days=self.config.retention_days),
            context=context,
            privacy_level=privacy,
            embedding=None,
            embedding_pending=False,
            embedding_model=self.config.embedding_model or None,
        )
        # Only fixed-vocabulary topics are embedded: no private text leaves the cipher boundary.
        if self.embedder and privacy != "sensitive" and context["topics"]:
            try:
                doc["embedding"] = self.embedder.embed(" ".join(context["topics"]))
            except Exception:
                doc["embedding_pending"] = True
        result = self._write(
            "interactions", doc, ["input_text", "ai_response", "gemini_analysis"]
        )
        if result and profile:
            profile["updated_at"] = now()
            # Keep the already encrypted payload; update only activity metadata.
            self.local.put(
                "user_profiles",
                {
                    k: v
                    for k, v in profile.items()
                    if k not in ("display_name", "preferences")
                },
                pending=self.mongo is not None,
            )
        return result

    def store_user_profile(self, profile):
        doc = asdict(profile)
        if doc["consents"].get("store_personal_data") is not True:
            return ""
        doc.update(schema_version="1.0", created_at=now(), updated_at=now())
        return self._write("user_profiles", doc, ["display_name", "preferences"])

    def _decode(self, collection, doc):
        if not doc:
            return None
        user_id = doc.get("user_id") or (
            doc["_id"] if collection == "user_profiles" else None
        )
        if self.local.is_deleted(user_id):
            return None
        try:
            return self.cipher.decrypt_fields(upgrade(doc))
        except Exception:
            log.warning(
                "memory_corrupt collection=%s id=%s", collection, doc.get("_id")
            )
            fallback = self.local.get(collection, doc["_id"])
            if fallback and fallback != doc:
                try:
                    return self.cipher.decrypt_fields(upgrade(fallback))
                except Exception:
                    pass
            return None

    def get_user_profile(self, user_id):
        if not user_id or self.local.is_deleted(user_id):
            return None
        doc = self.local.get("user_profiles", user_id)
        if doc and doc["updated_at"] < now() - timedelta(
            days=self.config.profile_retention_days
        ):
            self.delete_user_data(user_id)
            return None
        return self._decode("user_profiles", doc)

    def associate_face(self, signature, user_id):
        profile = self.get_user_profile(user_id)
        if (
            signature.user_id != user_id
            or not profile
            or not profile["consents"].get("store_face_data")
        ):
            return False
        doc = asdict(signature)
        doc.update(schema_version="1.0", updated_at=now())
        return bool(self._write("face_signatures", doc, ["embedding"]))

    def identify_user(self, signature):
        best = None
        for doc in self.local.list("face_signatures", all_users=True, limit=1000):
            profile = self.get_user_profile(doc["user_id"])
            if not profile or not all(
                profile["consents"].get(k)
                for k in ("store_face_data", "use_for_personalization")
            ):
                continue
            face = self._decode("face_signatures", doc)
            if not face or len(face["embedding"]) != len(signature):
                continue
            vector = face["embedding"]
            denominator = math.sqrt(
                sum(x * x for x in vector) * sum(x * x for x in signature)
            )
            score = (
                sum(x * y for x, y in zip(vector, signature)) / denominator
                if denominator
                else -1
            )
            if score >= self.config.face_match_threshold and (
                not best or score > best[1]
            ):
                best = (doc["user_id"], score)
        return best

    def retrieve_context(self, query, user_id=None, limit=5, session_id=None):
        try:
            if self.local.is_deleted(user_id):
                return []
            profile = self.get_user_profile(user_id) if user_id else None
            if user_id and not (
                profile and profile["consents"].get("use_for_personalization")
            ):
                return []
            candidates = []
            if self.online and self.mongo:
                from pymongo import timeout

                topics = " ".join(extract_context(query)["topics"])
                if self.embedder and topics:
                    try:
                        vector = self.embedder.embed(topics, query=True, timeout=0.15)
                        with timeout(0.12):
                            candidates = self.mongo.search(topics, user_id, vector)
                    except Exception:
                        pass
                if not candidates and topics:
                    try:
                        with timeout(0.10):
                            candidates = self.mongo.search(topics, user_id)
                    except Exception:
                        pass
                if not candidates:
                    try:
                        with timeout(0.10):
                            candidates = self.mongo.list("interactions", user_id, 50)
                    except Exception:
                        pass
            local = self.local.list("interactions", user_id, 50)
            local += self.local.search(set(extract_context(query)["topics"]), user_id)
            candidates = list({d["_id"]: d for d in local + candidates}.values())
            words = set(extract_context(query)["topics"])
            eligible = []
            for doc in candidates:
                if doc.get("user_id") != user_id or doc["expires_at"] <= now():
                    continue
                if user_id is None and (
                    not session_id or doc.get("session_id") != session_id
                ):
                    continue
                if doc["privacy_level"] == "sensitive" and not (
                    profile and profile["consents"].get("use_for_personalization")
                ):
                    continue
                overlap = len(words & set(doc["context"]["topics"])) / max(
                    1, len(words)
                )
                similarity = min(1, max(0, doc.get("similarity", overlap)))
                age = max(0, (now() - doc["timestamp"]).total_seconds() / 86400)
                eligible.append((0.7 * similarity + 0.3 * math.exp(-age / 14), doc))
            result = []
            for _, doc in sorted(eligible, key=lambda pair: pair[0], reverse=True):
                decoded = self._decode("interactions", doc)
                if decoded:
                    result.append(decoded)
                if len(result) >= limit:
                    break
            return result
        except Exception as exc:
            log.warning("memory_read_failed type=%s", type(exc).__name__)
            return []

    def delete_user_data(self, user_id):
        count = self.local.delete_user_data(user_id)
        if self.mongo is None:
            for seq, col, rid, _ in self.local.pending():
                if col == "delete" and rid == user_id:
                    self.local.ack(seq)
        self.wake.set()
        # Never promise remote deletion before the tombstone has been acknowledged.
        return DeletionReport(user_id, count, self.mongo is not None)

    def purge_expired(self):
        count = self.local.purge_expired()
        cutoff = now() - timedelta(days=self.config.profile_retention_days)
        for doc in self.local.list("user_profiles", all_users=True, limit=10000):
            if doc["updated_at"] < cutoff:
                count += self.delete_user_data(doc["_id"]).local_deleted
        return count

    def backfill(self):
        if not self.embedder:
            return
        for doc in self.local.pending_embeddings():
            if self.stop.is_set():
                break
            if doc.get("embedding_pending") and doc["privacy_level"] != "sensitive":
                try:
                    doc["embedding"] = self.embedder.embed(
                        " ".join(doc["context"]["topics"])
                    )
                    doc["embedding_pending"] = False
                    self.local.put("interactions", doc, pending=self.mongo is not None)
                except Exception:
                    break

    def health(self):
        state = "ONLINE" if self.online else ("OFFLINE" if self.mongo else "LOCAL_ONLY")
        return HealthStatus(
            state,
            self.local.depth(),
            self.connection.failures if self.connection else 0,
        )

    def close(self):
        self.stop.set()
        self.wake.set()
        if self.connection:
            self.connection.close()
        if self.worker:
            self.worker.join(timeout=3)
        # A stuck daemon may still use SQLite; don't close its connection under it.
        if not self.worker or not self.worker.is_alive():
            self.local.close()
