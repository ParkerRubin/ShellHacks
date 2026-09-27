import logging
import queue
import threading

from .models import InteractionRecord, uid

log = logging.getLogger(__name__)


class MemoryIngestor:
    def __init__(self, store, presence):
        self.store, self.presence = store, presence
        self.session_id = uid()
        self.queue = queue.Queue(maxsize=200)
        self.lock = threading.Lock()
        self.pending = None
        self.stop = threading.Event()
        self.worker = threading.Thread(
            target=self._run, name="memory-ingestor", daemon=True
        )
        self.worker.start()

    def on_user(self, text):
        try:
            with self.lock:
                self.pending = (str(text)[:12000], self.presence.get(), None)
        except Exception:
            log.warning("memory_callback_failed operation=user")

    def on_gemini(self, text):
        with self.lock:
            if self.pending:
                self.pending = (*self.pending[:2], str(text)[:4000])

    def on_agent(self, text):
        try:
            with self.lock:
                pending, self.pending = self.pending, None
            if pending:
                user_text, snapshot, gemini = pending
                # A person leaving or deletion during the turn invalidates the pair.
                if snapshot != self.presence.get():
                    return
                record = InteractionRecord(
                    user_text,
                    str(text)[:12000],
                    self.session_id,
                    user_id=snapshot.user_id if snapshot.store_personal_data else None,
                    gemini_analysis=gemini,
                )
                self.enqueue(record)
        except Exception:
            log.warning("memory_callback_failed operation=agent")

    def enqueue(self, record):
        if self.stop.is_set():
            return False
        try:
            self.queue.put_nowait(record)
            return True
        except queue.Full:
            try:
                self.queue.get_nowait()
                self.queue.task_done()
                self.queue.put_nowait(record)
            except (queue.Empty, queue.Full):
                pass
            log.warning("memory_queue_full dropped=true")
            return False

    def _run(self):
        while not self.stop.is_set() or not self.queue.empty():
            try:
                record = self.queue.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                self.store.store_interaction(record)
            except Exception as exc:
                log.warning("memory_ingest_failed type=%s", type(exc).__name__)
            finally:
                self.queue.task_done()

    def close(self):
        self.stop.set()
        self.worker.join(timeout=4)
