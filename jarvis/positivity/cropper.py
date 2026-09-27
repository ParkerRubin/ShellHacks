"""In-memory, bounded face inputs. No external adapter accepts camera arrays."""

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class FaceInput:
    jpeg: bytes | None = None
    tags: tuple[str, ...] = ()

    def __post_init__(self):
        if self.jpeg is None:
            if not self.tags or any(not isinstance(t, str) for t in self.tags):
                raise ValueError("Text input requires tags")
            return
        if (
            not isinstance(self.jpeg, bytes)
            or len(self.jpeg) > 256 * 256 * 4
            or b"Exif\x00\x00" in self.jpeg
        ):
            raise ValueError("Only bounded metadata-free JPEG crops are accepted")
        image = cv2.imdecode(np.frombuffer(self.jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None or max(image.shape[:2]) > 256:
            raise ValueError("Invalid crop dimensions")

    @classmethod
    def from_tags(cls, observations):
        # Never forward model/free-form detail strings as supposedly anonymous tags.
        from .lexicon import ALLOWED_FEATURES

        return cls(
            tags=tuple(
                sorted(
                    {o.feature for o in observations if o.feature in ALLOWED_FEATURES}
                )
            )
        )


class FaceCropper:
    def crop_face(self, frame, box):
        x, y, w, h = (int(v) for v in box)
        if w <= 0 or h <= 0:
            raise ValueError("Empty face")
        height, width = frame.shape[:2]
        if x >= width or y >= height or x + w <= 0 or y + h <= 0:
            raise ValueError("Face outside frame")
        px, py = round(0.2 * w), round(0.2 * h)
        crop = frame[
            max(0, y - py) : min(height, y + h + py),
            max(0, x - px) : min(width, x + w + px),
        ].copy()
        h, w = crop.shape[:2]
        if max(h, w) > 256:
            scale = 256 / max(h, w)
            crop = cv2.resize(
                crop, (max(1, round(w * scale)), max(1, round(h * scale)))
            )
        ok, encoded = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            raise ValueError("Crop encoding failed")
        result = encoded.tobytes()
        FaceInput(jpeg=result)
        return result
