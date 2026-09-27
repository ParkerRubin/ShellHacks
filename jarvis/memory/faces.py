import logging
import threading
import time
from typing import Protocol

from .models import Presence

log = logging.getLogger(__name__)


class FaceSignatureProvider(Protocol):
    def signature(self, crop): ...


class OpenCVSFaceProvider:
    def __init__(self, config):
        import cv2

        self.cv2 = cv2
        self.detector = cv2.FaceDetectorYN.create(
            config.face_detection_model, "", (320, 320)
        )
        self.recognizer = cv2.FaceRecognizerSF.create(config.face_recognition_model, "")

    def signature(self, crop):
        h, w = crop.shape[:2]
        self.detector.setInputSize((w, h))
        _, faces = self.detector.detect(crop)
        if faces is None or len(faces) != 1:
            return None
        # SFace requires landmark alignment; Haar boxes alone are insufficient.
        aligned = self.recognizer.alignCrop(crop, faces[0])
        return self.recognizer.feature(aligned).flatten().tolist()


class FaceIdentifier:
    def __init__(self, store, presence, provider=None):
        self.store, self.presence, self.provider = store, presence, provider
        self.lock = threading.RLock()
        self.busy = threading.Lock()
        self.last_run = 0
        self.last_seen = 0
        self.current_signature = None
        self.previous_match = None
        self.box = None
        self.closed = False

    def clear(self):
        with self.lock:
            self.current_signature = None
            self.previous_match = None
            self.box = None
            self.presence.clear()

    def submit(self, frame, box=None):
        # Enrollment/deletion may briefly own the state lock; the camera skips
        # this frame instead of waiting on disk writes in those operations.
        if not self.lock.acquire(blocking=False):
            return
        acquired_busy = False
        try:
            if self.closed:
                return
            if box is None:
                if time.monotonic() - self.last_seen > 0.5:
                    self.clear()
                return
            self.last_seen = time.monotonic()
            # A discontinuous track invalidates the previous identity immediately.
            if self.box is not None:
                x, y, w, h = box
                px, py, pw, ph = self.box
                if abs(x - px) > max(w, pw) or abs(y - py) > max(h, ph):
                    self.clear()
            self.box = tuple(box)
            if (
                not self.provider
                or time.monotonic() - self.last_run < 2
                or not self.busy.acquire(False)
            ):
                return
            acquired_busy = True
            self.last_run = time.monotonic()
            snapshot = self.presence.get()
            x, y, w, h = box
            # YuNet needs context around the tight Haar detection. Add 30%
            # of each dimension on each side, clamped to the camera frame.
            pad_x, pad_y = round(w * 0.30), round(h * 0.30)
            height, width = frame.shape[:2]
            crop = frame[
                max(0, y - pad_y) : min(height, y + h + pad_y),
                max(0, x - pad_x) : min(width, x + w + pad_x),
            ].copy()

            def work():
                try:
                    signature = self.provider.signature(crop)
                    match = self.store.identify_user(signature) if signature else None
                    with self.lock:
                        if snapshot != self.presence.get():
                            return
                        self.current_signature = signature
                        if match and self.previous_match == match[0]:
                            profile = self.store.get_user_profile(match[0])
                            if profile:
                                c = profile["consents"]
                                self.presence.set(
                                    Presence(
                                        match[0],
                                        c["store_personal_data"],
                                        c["store_face_data"],
                                        c["use_for_personalization"],
                                        match[1]
                                        >= self.store.config.face_greet_threshold,
                                        snapshot.generation,
                                    )
                                )
                        elif snapshot.user_id and (
                            not match or match[0] != snapshot.user_id
                        ):
                            self.presence.clear()
                        self.previous_match = match[0] if match else None
                except Exception as exc:
                    self.clear()
                    log.warning("memory_face_failed type=%s", type(exc).__name__)
                finally:
                    self.busy.release()

            threading.Thread(target=work, name="memory-face", daemon=True).start()
        except Exception:
            self.clear()
            if acquired_busy:
                self.busy.release()
        finally:
            self.lock.release()

    def close(self):
        self.closed = True
        self.clear()
