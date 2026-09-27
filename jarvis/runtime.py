"""Bound shutdown latency on the camera's ESC path."""

import os
import threading


def close_and_exit(close, timeout=0.2, exit_fn=os._exit):
    def cleanup():
        try:
            close()
        except Exception:
            pass

    try:
        worker = threading.Thread(target=cleanup, name="robot-shutdown", daemon=True)
        worker.start()
        worker.join(timeout=timeout)
    finally:
        exit_fn(0)
