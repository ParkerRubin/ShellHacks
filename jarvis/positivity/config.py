"""Configuration only; importing this module starts no threads or clients."""

import math
import os
from dataclasses import dataclass

DEFAULT_OPT_OUT = (
    "no",
    "no thanks",
    "stop",
    "leave me alone",
    "don't",
    "do not",
    "go away",
    "not now",
    "quiet",
)


@dataclass(frozen=True)
class PositivityConfig:
    enabled: bool = False
    privacy_mode: str = "crop"
    dwell_s: float = 1.0
    cooldown_min: float = 10.0
    max_faces: int = 3
    min_referenced: int = 2
    voice_id: str = ""
    tts_model: str = "eleven_flash_v2_5"
    opt_out_words: tuple[str, ...] = DEFAULT_OPT_OUT
    notice: str = "full"
    opt_out_s: float = 2.0
    rate_limit_s: float = 20.0
    face_timeout_s: float = 2.5
    voice_timeout_s: float = 20.0

    @property
    def notice_text(self):
        if self.notice == "short":
            return "May I offer a kind remark? Say no thanks or step away to skip."
        return (
            "I'd like to offer a kind remark. "
            + (
                "A small face crop will go to Gemini. "
                if self.privacy_mode == "crop"
                else "Only local feature tags will go to Gemini. "
            )
            + "Say no thanks or step away to skip."
        )

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        flag = env.get("POSITIVITY_ENABLED", "false").lower()
        if flag == "false":
            return cls()
        if flag != "true":
            raise ValueError("POSITIVITY_ENABLED must be true or false")
        values = {"enabled": True}
        for key in ("privacy_mode", "voice_id", "tts_model", "notice"):
            values[key] = env.get("POSITIVITY_" + key.upper(), getattr(cls(), key))
        for key in ("dwell_s", "cooldown_min"):
            value = float(env.get("POSITIVITY_" + key.upper(), getattr(cls(), key)))
            if not math.isfinite(value) or value <= 0:
                raise ValueError("Invalid positivity timing")
            values[key] = value
        for key, high in (("max_faces", 3), ("min_referenced", 3)):
            value = int(env.get("POSITIVITY_" + key.upper(), getattr(cls(), key)))
            if not 1 <= value <= high:
                raise ValueError("Invalid positivity count")
            values[key] = value
        if values["privacy_mode"] not in ("crop", "tags_only") or values[
            "notice"
        ] not in ("short", "full"):
            raise ValueError("Invalid positivity mode or notice")
        extra = tuple(
            w.strip().lower()
            for w in env.get("POSITIVITY_OPT_OUT_WORDS", "").split(",")
            if w.strip()
        )
        values["opt_out_words"] = tuple(dict.fromkeys(DEFAULT_OPT_OUT + extra))
        return cls(**values)
