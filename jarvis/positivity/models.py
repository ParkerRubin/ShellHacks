from dataclasses import dataclass


@dataclass(frozen=True)
class Observation:
    feature: str
    detail: str


@dataclass(frozen=True)
class FaceDescription:
    observations: tuple[Observation, ...]
    remark: str | None = None
    smile_score: float = 0.0
    expression_score: float = 0.0
    source: str = "local"
    generic: bool = False


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    reasons: tuple[str, ...] = ()
