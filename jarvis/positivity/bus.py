"""A latest-wins mailbox; frames stay local and are never mutated by consumers."""

import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class FaceEvent:
    frame: object
    faces: tuple[tuple[int, int, int, int], ...]
    ts: float


class FaceBus:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.Lock()
        self.latest = None
        self.closed = False

    def publish(self, frame, faces):
        if not self.lock.acquire(blocking=False):
            return False
        try:
            if self.closed:
                return False
            self.latest = FaceEvent(
                frame.copy(),
                tuple(tuple(int(n) for n in box) for box in faces),
                self.clock(),
            )
            return True
        except Exception:
            return False
        finally:
            self.lock.release()

    def take(self):
        with self.lock:
            event, self.latest = self.latest, None
            return event

    def close(self):
        with self.lock:
            self.closed = True
            self.latest = None
