import json
import math
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
    """Uses the robot's existing synchronous Gemini model; no client or keys here."""

    def __init__(self, model, timeout=2.5):
        self.model, self.timeout = model, timeout

    def describe(self, face, feedback=()):
        if not isinstance(face, FaceInput):
            raise TypeError("GeminiDescriber accepts only FaceInput")
        prompt = SYSTEM_PROMPT
        if feedback:
            prompt += "\nPrevious response failed checks: " + "; ".join(feedback)
        if face.jpeg is not None:
            content = [prompt, {"mime_type": "image/jpeg", "data": face.jpeg}]
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
        response = self.model.generate_content(
            content,
            generation_config={
                "response_mime_type": "application/json",
                "response_schema": RESPONSE_SCHEMA,
            },
            request_options={"timeout": self.timeout, "retry": None},
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


class LocalTagDescriber:
    """Modest local expression proxies, not mood/health or eyeglass identification."""

    def __init__(self):
        self.cascades = {
            key: cv2.CascadeClassifier(cv2.data.haarcascades + filename)
            for key, filename in {
                "smile": "haarcascade_smile.xml",
                "eyes": "haarcascade_eye.xml",
                "glasses": "haarcascade_eye_tree_eyeglasses.xml",
            }.items()
        }
        if any(c.empty() for c in self.cascades.values()):
            raise ValueError("Local cascades unavailable")

    def describe(self, face, feedback=()):
        if not isinstance(face, FaceInput) or face.jpeg is None:
            raise TypeError("Local describer needs one crop")
        image = cv2.imdecode(
            np.frombuffer(face.jpeg, dtype=np.uint8), cv2.IMREAD_GRAYSCALE
        )
        smile = self.cascades["smile"].detectMultiScale(image, 1.7, 20)
        eyes = self.cascades["eyes"].detectMultiScale(image, 1.1, 5)
        glasses_eyes = self.cascades["glasses"].detectMultiScale(image, 1.1, 5)
        observations = [Observation("presence", "You are here in this moment")]
        if len(smile):
            observations += [
                Observation("smile", "A visible smile"),
                Observation("expression", "An expressive smile"),
            ]
        eye_boxes = eyes if len(eyes) >= 2 else glasses_eyes
        if len(eye_boxes) >= 2:
            pair = sorted(eye_boxes, key=lambda b: b[0])[:2]
            tilt = abs(float(pair[0][1]) - float(pair[1][1])) / max(1, image.shape[0])
            center = sum(float(box[0]) + float(box[2]) / 2 for box in pair) / 2
            if abs(center / image.shape[1] - 0.5) < 0.2:
                observations[0] = Observation("presence", "A centered presence")
            observations.append(Observation("eyes", "An engaged gaze"))
            if tilt < 0.15:
                observations.append(
                    Observation("expression", "An attentive expression")
                )
        # The eyeglasses cascade detects eyes even without glasses. Never assert
        # 'glasses' from that detector alone. Framing is a local proxy only.
        score = min(1.0, 0.5 * bool(len(smile)) + 0.5 * (len(eye_boxes) >= 2))
        return FaceDescription(
            tuple(observations),
            smile_score=float(bool(len(smile))),
            expression_score=score,
        )
