"""DRAFT FOR HUMAN REVIEW: templates have not been read aloud or culturally reviewed."""

from .lexicon import ALLOWED_FEATURES, NEUTRAL_GREETINGS
from .models import FaceDescription

TEMPLATES = {
    "smile": (
        "Your smile brings warmth.",
        "Your smile feels welcoming.",
        "Your smile adds a cheerful spark.",
        "Your smile lights up this moment.",
        "Your smile is full of warmth.",
    ),
    "expression": (
        "Your expression feels welcoming.",
        "Your expression brings warmth.",
        "Your expressive look adds energy.",
        "Your expression has a lively spark.",
        "Your expression feels open.",
    ),
    "eyes": (
        "Your eyes look engaged.",
        "Your gaze feels attentive.",
        "Your eyes have a lively spark.",
        "Your gaze adds warmth.",
        "Your eyes look expressive.",
    ),
    "presence": (
        "Your presence is welcome here.",
        "Your presence adds warmth.",
        "Your energy is welcome here.",
        "Your calm presence is welcome.",
        "Your presence brings a spark.",
    ),
    "style": (
        "Your style adds a creative touch.",
        "Your style brings a lively detail.",
        "Your style has a playful spark.",
        "Your style adds character.",
        "Your style feels expressive.",
    ),
}


class AffirmationBank:
    def __init__(self, validator):
        self.validator = validator
        self.next_variant = 0

    def compose(self, observations):
        observations = tuple(o for o in observations if o.feature in ALLOWED_FEATURES)
        features = sorted({o.feature for o in observations})
        text = " ".join(TEMPLATES[f][self.next_variant % 5] for f in features[:3])
        self.next_variant += 1
        candidate = FaceDescription(observations, text)
        if self.validator.validate(candidate).ok:
            return candidate
        # Do not retain rejected or fabricated observations in a degraded greeting.
        candidate = FaceDescription((), NEUTRAL_GREETINGS[0], generic=True)
        if not self.validator.validate(candidate).ok:
            raise ValueError("Neutral bank failed validation")
        return candidate
