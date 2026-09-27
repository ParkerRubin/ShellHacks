import json
import queue
import threading


class MemoryRetriever:
    """One daemon worker, no unbounded executor backlog even if a backend hangs."""

    def __init__(self, store, presence, session_id):
        self.store, self.presence, self.session_id = store, presence, session_id
        self.busy = threading.Lock()
        self.closed = False

    def recall(self, query, user_id=None):
        if self.closed or not self.busy.acquire(blocking=False):
            return ""
        snapshot = self.presence.get()
        if user_id != snapshot.user_id:
            self.busy.release()
            return ""
        result = queue.Queue(maxsize=1)

        def work():
            try:
                records = self.store.retrieve_context(
                    str(query)[:2000], user_id, session_id=self.session_id
                )
                lines = []
                profile = self.store.get_user_profile(user_id) if user_id else None
                if profile and snapshot.use_for_personalization:
                    facts = dict(profile.get("preferences", {}))
                    if snapshot.may_greet_by_name:
                        facts["name"] = profile.get("display_name")
                    lines.append("Profile: " + json.dumps(facts, ensure_ascii=False))
                for doc in records:
                    lines.append(f"- {doc['input_text']} / {doc['ai_response']}")
                result.put_nowait("\n".join(lines)[:600])
            except Exception:
                result.put_nowait("")
            finally:
                self.busy.release()

        threading.Thread(target=work, name="memory-recall", daemon=True).start()
        try:
            value = result.get(timeout=0.48)
            # Recheck consent/presence after network reads or a concurrent forget.
            return (
                value
                if snapshot == self.presence.get()
                and not self.store.local.is_deleted(user_id)
                else ""
            )
        except queue.Empty:
            return ""

    def close(self):
        self.closed = True
