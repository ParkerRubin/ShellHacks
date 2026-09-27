import re

VOCABULARY = frozenset(
    "robot robotics python coding hackathon music study school science travel food sports art weather project mongodb database homework programming coffee".split()
)
EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
PHONE = re.compile(r"(?<!\w)\+?\d[\d ()-]{7,}\d(?!\w)")


def scrub_pii(text):
    return PHONE.sub("[phone]", EMAIL.sub("[email]", text))


def extract_context(text):
    words = set(re.findall(r"[a-z]+", text.lower()))
    return {"topics": sorted(words & VOCABULARY), "entities": [], "sentiment": "neu"}


def classify_privacy(text, consent=False):
    if re.search(
        r"\b(password|medical|diagnosis|bank|ssn|address|health|secret)\b", text, re.I
    ):
        return "sensitive"
    # Unstructured transcripts are never assumed to be free of personal information.
    return "personal" if consent else "public"
