import json
import math
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np

from .cropper import FaceInput
from .lexicon import ALLOWED_FEATURES
from .models import FaceDescription, Observation
from .prompts import RESPONSE_SCHEMA, SYSTEM_PROMPT


class FaceDescriber(Protocol):
    def describe(
        self, face: FaceInput, feedback: tuple[str, ...] = ()
    ) -> FaceDescription: ...


class GeminiDescriber:
    """Uses the app's existing google-genai client; no keys are read here."""

    def __init__(self, client, model="gemini-3.5-flash", timeout=2.5):
        self.client, self.model, self.timeout = client, model, timeout

    def describe(self, face, feedback=()):
        from google.genai import types

        if not isinstance(face, FaceInput):
            raise TypeError("GeminiDescriber accepts only FaceInput")
        prompt = SYSTEM_PROMPT
        if feedback:
            prompt += "\nPrevious response failed checks: " + "; ".join(feedback)
        if face.jpeg is not None:
            content = [
                prompt,
                types.Part.from_bytes(data=face.jpeg, mime_type="image/jpeg"),
            ]
        else:
            if not set(face.tags) <= ALLOWED_FEATURES:
                raise ValueError("Unknown local tags")
            from .bank import AffirmationBank
            from .validator import RemarkValidator

            draft = AffirmationBank(RemarkValidator()).compose(
                tuple(Observation(tag, "Observed " + tag) for tag in face.tags)
            )
            content = [
                prompt
                + "\nLocal tags: "
                + ", ".join(face.tags)
                + "\nWarmly rewrite this draft using only those tags: "
                + draft.remark
            ]
        response = self.client.models.generate_content(
            model=self.model,
            contents=content,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=RESPONSE_SCHEMA,
                http_options=types.HttpOptions(
                    timeout=max(1, int(self.timeout * 1000)),
                    retry_options=types.HttpRetryOptions(attempts=1),
                ),
            ),
        )
        raw = json.loads(response.text)
        observations = raw["observations"]
        if (
            not isinstance(observations, list)
            or len(observations) > 20
            or not isinstance(raw["remark"], str)
        ):
            raise ValueError("Malformed description")
        parsed = tuple(Observation(o["feature"], o["detail"]) for o in observations)
        if any(
            not isinstance(o.feature, str)
            or not isinstance(o.detail, str)
            or len(o.detail) > 240
            for o in parsed
        ):
            raise ValueError("Malformed observations")
        if face.jpeg is None and not {o.feature for o in parsed} <= set(face.tags):
            raise ValueError("Model invented an unobserved feature")
        scores = [float(raw[k]) for k in ("smile_score", "expression_score")]
        if not all(math.isfinite(s) and 0 <= s <= 1 for s in scores):
            raise ValueError("Invalid scores")
        return FaceDescription(parsed, raw["remark"], *scores, source="gemini")


MODELS = Path(__file__).resolve().parents[2] / "models"
YUNET_FILES = ("face_detection_yunet_2026may.onnx", "face_detection_yunet_2023mar.onnx")
# Mouth-corner span relative to the eye span. Smiles pull the corners outward;
# a neutral mouth sits well under the eye span. A modest proxy, not a classifier.
SMILE_RATIO = 1.0


class LocalTagDescriber:
    """Modest local expression proxies from YuNet landmarks (OpenCV 5 dropped the
    Haar cascades), not mood/health or eyeglass identification."""

    def __init__(self, model_path=None):
        paths = [Path(model_path)] if model_path else [MODELS / f for f in YUNET_FILES]
        path = next((p for p in paths if p.is_file()), None)
        if path is None:
            raise ValueError("Local face model unavailable")
        self.detector = cv2.FaceDetectorYN.create(str(path), "", (320, 320), 0.6, 0.3, 5)

    def describe(self, face, feedback=()):
        if not isinstance(face, FaceInput) or face.jpeg is None:
            raise TypeError("Local describer needs one crop")
        image = cv2.imdecode(np.frombuffer(face.jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
        h, w = image.shape[:2]
        self.detector.setInputSize((w, h))
        _, rows = self.detector.detect(image)
        observations = [Observation("presence", "You are here in this moment")]
        if rows is None or not len(rows):
            return FaceDescription(tuple(observations), smile_score=0.0, expression_score=0.0)
        r = max(rows, key=lambda row: row[2] * row[3])
        (rex, rey), (lex, ley) = (r[4], r[5]), (r[6], r[7])
        (rmx, rmy), (lmx, lmy) = (r[10], r[11]), (r[12], r[13])
        eye_span = max(1.0, math.hypot(lex - rex, ley - rey))
        smiling = math.hypot(lmx - rmx, lmy - rmy) / eye_span >= SMILE_RATIO
        if smiling:
            observations += [
                Observation("smile", "A visible smile"),
                Observation("expression", "An expressive smile"),
            ]
        tilt = abs(float(ley - rey)) / max(1, h)
        if abs((rex + lex) / 2 / w - 0.5) < 0.2:
            observations[0] = Observation("presence", "A centered presence")
        observations.append(Observation("eyes", "An engaged gaze"))
        if tilt < 0.15:
            observations.append(Observation("expression", "An attentive expression"))
        # Framing is a local proxy only; glasses are never asserted locally.
        score = min(1.0, 0.5 * smiling + 0.5)
        return FaceDescription(
            tuple(observations),
            smile_score=float(smiling),
            expression_score=score,
        )
