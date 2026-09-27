from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import RLock
from typing import Protocol
from uuid import uuid4


def now():
    return datetime.now(timezone.utc)


def uid():
    return str(uuid4())


@dataclass(frozen=True)
class Presence:
    user_id: str | None = None
    store_personal_data: bool = False
    store_face_data: bool = False
    use_for_personalization: bool = False
    may_greet_by_name: bool = False
    generation: int = 0


class PresenceState:
    def __init__(self):
        self.lock = RLock()
        self._value = Presence()

    def get(self):
        with self.lock:
            return self._value

    def set(self, value):
        with self.lock:
            self._value = value

    def clear(self):
        with self.lock:
            self._value = Presence(generation=self._value.generation + 1)

    @property
    def user_id(self):
        return self.get().user_id


@dataclass
class InteractionRecord:
    input_text: str
    ai_response: str
    session_id: str
    user_id: str | None = None
    gemini_analysis: str | None = None
    _id: str = field(default_factory=uid)
    timestamp: datetime = field(default_factory=now)


@dataclass
class UserProfile:
    display_name: str | None = None
    preferences: dict = field(default_factory=dict)
    consents: dict = field(default_factory=dict)
    _id: str = field(default_factory=uid)


@dataclass
class FaceSignature:
    embedding: list[float]
    user_id: str
    _id: str = field(default_factory=uid)


@dataclass
class DeletionReport:
    user_id: str
    local_deleted: int = 0
    remote_pending: bool = False


@dataclass
class HealthStatus:
    state: str
    outbox_depth: int = 0
    consecutive_failures: int = 0


class IMemoryStore(Protocol):
    def store_interaction(self, record: InteractionRecord) -> str: ...
    def retrieve_context(
        self, query: str, user_id: str | None = None, limit: int = 5
    ) -> list[dict]: ...
    def store_user_profile(self, profile: UserProfile) -> str: ...
    def get_user_profile(self, user_id: str) -> dict | None: ...
    def associate_face(self, signature: FaceSignature, user_id: str) -> bool: ...
    def identify_user(self, signature: list[float]) -> tuple[str, float] | None: ...
    def delete_user_data(self, user_id: str) -> DeletionReport: ...
    def purge_expired(self) -> int: ...
    def health(self) -> HealthStatus: ...
