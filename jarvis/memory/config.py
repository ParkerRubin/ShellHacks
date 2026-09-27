import os
import re
from dataclasses import dataclass, field

from .errors import ValidationError


@dataclass(frozen=True)
class MemoryConfig:
    enabled: bool = True
    uri: str = field(default="", repr=False)
    database: str = "jarvis"
    key: str = field(default="", repr=False)
    local_path: str = "./data/fallback.sqlite3"
    retention_days: int = 90
    profile_retention_days: int = 180
    embedding_model: str = ""
    embedding_dim: int = 768
    face_detection_model: str = "models/face_detection_yunet_2023mar.onnx"
    face_recognition_model: str = "models/face_recognition_sface_2021dec.onnx"
    face_match_threshold: float = 0.363
    face_greet_threshold: float = 0.5

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        enabled = env.get("MEMORY_ENABLED", "true").lower()
        if enabled == "false":
            return cls(enabled=False)
        errors = []
        if enabled != "true":
            errors.append("MEMORY_ENABLED must be true or false")
        key = env.get("ENCRYPTION_KEY", "")
        from cryptography.fernet import Fernet

        try:
            Fernet(key.encode())
        except Exception:
            errors.append(
                "ENCRYPTION_KEY must be a Fernet key; run python scripts/gen_key.py"
            )
        uri = env.get("MONGODB_ATLAS_URI", "")
        if uri and not uri.startswith("mongodb+srv://"):
            errors.append(
                "MONGODB_ATLAS_URI must use mongodb+srv:// (TLS Atlas connection)"
            )
        database = env.get("MONGODB_DB", "jarvis")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,63}", database):
            errors.append(
                "MONGODB_DB must contain 1–63 letters, digits, underscores or hyphens"
            )
        values = {}
        for name, default in [
            ("RETENTION_DAYS", 90),
            ("PROFILE_RETENTION_DAYS", 180),
            ("EMBEDDING_DIM", 768),
        ]:
            try:
                values[name.lower()] = int(env.get(name, default))
                if values[name.lower()] <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                errors.append(f"{name} must be a positive integer")
        for name, default in [
            ("FACE_MATCH_THRESHOLD", 0.363),
            ("FACE_GREET_THRESHOLD", 0.5),
        ]:
            try:
                values[name.lower()] = float(env.get(name, default))
                if not 0 < values[name.lower()] <= 1:
                    raise ValueError
            except (TypeError, ValueError):
                errors.append(f"{name} must be in (0, 1]")
        if values.get("face_greet_threshold", 1) < values.get(
            "face_match_threshold", 0
        ):
            errors.append("FACE_GREET_THRESHOLD must be >= FACE_MATCH_THRESHOLD")
        if errors:
            raise ValidationError("; ".join(errors))
        return cls(
            uri=uri,
            database=database,
            key=key,
            local_path=env.get("LOCAL_FALLBACK_PATH", "./data/fallback.sqlite3"),
            embedding_model=env.get("EMBEDDING_MODEL", ""),
            face_detection_model=env.get(
                "FACE_DETECTION_MODEL", cls.face_detection_model
            ),
            face_recognition_model=env.get(
                "FACE_RECOGNITION_MODEL", cls.face_recognition_model
            ),
            **values,
        )
