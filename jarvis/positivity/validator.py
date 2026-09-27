import re

from .lexicon import (
    ALLOWED_FEATURES,
    BACKHANDED,
    DENY_CATEGORIES,
    FEATURE_KEYWORDS,
    NEUTRAL_GREETINGS,
)
from .models import ValidationResult


def has_term(text, term):
    return re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text, re.I) is not None


class RemarkValidator:
    def __init__(self, min_referenced=2):
        self.min_referenced = min_referenced

    def validate(self, description):
        reasons = []
        remark = description.remark or ""
        combined = " ".join([remark] + [o.detail for o in description.observations])
        for category, words in DENY_CATEGORIES.items():
            if any(has_term(combined, w) for w in words):
                reasons.append("blocked category: " + category)
        if any(has_term(combined, w) for w in BACKHANDED):
            reasons.append("comparison or backhanded wording")
        if (
            not re.fullmatch(r"[A-Za-z .,!?;:'\-]+", combined)
            or len(remark) > 240
            or not remark
        ):
            reasons.append("length or characters")
        sentences = [s for s in re.split(r"[.!?]+", remark) if s.strip()]
        if not 1 <= len(sentences) <= 3:
            reasons.append("sentence count")
        features = {o.feature for o in description.observations}
        if not features <= ALLOWED_FEATURES:
            reasons.append("unknown feature")
        # Sparse local evidence cannot truthfully manufacture three observations.
        # Only these exact hardcoded draft greetings may bypass specificity.
        neutral = description.generic and remark in NEUTRAL_GREETINGS
        if description.generic and not neutral:
            reasons.append("untrusted generic text")
        if not neutral:
            if (
                len({(o.feature, o.detail.lower()) for o in description.observations})
                < 3
            ):
                reasons.append("fewer than three distinct observations")
            referenced = sum(
                any(has_term(remark, w) for w in FEATURE_KEYWORDS[f])
                for f in features & ALLOWED_FEATURES
            )
            if referenced < self.min_referenced:
                reasons.append("insufficient observed features referenced")
        return ValidationResult(not reasons, tuple(reasons))
