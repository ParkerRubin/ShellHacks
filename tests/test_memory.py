import threading
import time
from datetime import timedelta
from types import SimpleNamespace

import mongomock
import pytest
from cryptography.fernet import Fernet
from hypothesis import given
from hypothesis import strategies as st

from jarvis.memory import NullMemory, build_memory
from jarvis.memory.config import MemoryConfig
from jarvis.memory.consent import ConsentManager
from jarvis.memory.crypto import FieldCipher
from jarvis.memory.errors import PrivacyError, ValidationError
from jarvis.memory.faces import FaceIdentifier
from jarvis.memory.ingestor import MemoryIngestor
from jarvis.memory.models import (
    FaceSignature,
    InteractionRecord,
    Presence,
    PresenceState,
    UserProfile,
    now,
)
from jarvis.memory.mongo_store import MongoStore
from jarvis.memory.retriever import MemoryRetriever
from jarvis.memory.store import ResilientMemoryStore


@pytest.fixture
def store(tmp_path):
    config = MemoryConfig(
        key=Fernet.generate_key().decode(), local_path=str(tmp_path / "test.sqlite3")
    )
    value = ResilientMemoryStore(
        config, MongoStore(mongomock.MongoClient(tz_aware=True).db)
    )
    yield value
    value.close()


def enroll(store, name="Ada"):
    return store.store_user_profile(
        UserProfile(
            display_name=name,
            consents={
                "store_personal_data": True,
                "store_face_data": True,
                "use_for_personalization": True,
            },
        )
    )


def record(user_id=None, text="python robotics"):
    return InteractionRecord(text, "Let's build it", "session", user_id)


def test_disabled_short_circuits(monkeypatch):
    monkeypatch.setenv("MEMORY_ENABLED", "false")
    monkeypatch.setenv("ENCRYPTION_KEY", "wrong")
    assert isinstance(build_memory(), NullMemory)
    assert MemoryConfig.from_env({"MEMORY_ENABLED": "false"}).enabled is False


def test_config_errors_aggregate():
    with pytest.raises(ValidationError) as exc:
        MemoryConfig.from_env(
            {"RETENTION_DAYS": "0", "MONGODB_DB": "bad/db", "EMBEDDING_DIM": "x"}
        )
    assert all(
        name in str(exc.value)
        for name in ["ENCRYPTION_KEY", "RETENTION_DAYS", "MONGODB_DB", "EMBEDDING_DIM"]
    )


@given(st.text(max_size=500))
def test_encryption_roundtrip(text):
    cipher = FieldCipher(Fernet.generate_key().decode())
    doc = cipher.encrypt_fields({"message": text}, ["message"])
    assert "message" not in doc
    assert cipher.decrypt_fields(doc)["message"] == text
    with pytest.raises(PrivacyError):
        FieldCipher(Fernet.generate_key().decode()).decrypt_fields(doc)


def test_encrypted_roundtrip_and_no_other_users(store):
    user_id = enroll(store)
    other = enroll(store, "Grace")
    rec = record(user_id, "My private phone is 555-555-1212")
    rec.gemini_analysis = "Private name on a badge"
    store.store_interaction(rec)
    store.store_interaction(record(other, "Another person's details"))
    raw = store.local.get("interactions", rec._id)
    assert "input_text" not in raw and "gemini_analysis" not in raw
    assert "555-555-1212" not in str(raw)
    store.replay()
    assert store.mongo.db.interactions.count_documents({}) == 2
    results = store.retrieve_context("phone", user_id)
    assert len(results) == 1
    assert results[0]["input_text"] == rec.input_text
    assert results[0]["gemini_analysis"] == rec.gemini_analysis


def test_anonymous_is_topics_only_and_session_scoped(store):
    rec = record(
        None, "I am Alice at 123 Main Street. I like python. alice@example.com"
    )
    store.store_interaction(rec)
    assert store.retrieve_context("python", None) == []
    docs = store.retrieve_context("python", None, session_id="session")
    assert len(docs) == 1
    assert docs[0]["input_text"] == "[anonymous topics] python"
    assert docs[0]["ai_response"] == ""
    assert store.retrieve_context("python", None, session_id="other") == []


def test_offline_replay_idempotent_and_partial_failure(store):
    user_id = enroll(store)
    rec = record(user_id)
    store.store_interaction(rec)
    real_put = store.mongo.put

    def failed(*args):
        raise OSError("offline")

    store.mongo.put = failed
    store.replay()
    assert store.local.depth() == 2
    assert store.retrieve_context("python", user_id)
    store.mongo.put = real_put
    store.replay()
    store.replay()
    assert store.local.depth() == 0
    assert store.mongo.db.interactions.count_documents({"_id": rec._id}) == 1


def test_delete_offline_survives_restart_and_late_write(store):
    user_id = enroll(store)
    other = enroll(store)
    store.store_interaction(record(user_id))
    store.store_interaction(record(other))
    store.associate_face(FaceSignature([1.0, 0.0], user_id), user_id)
    store.replay()
    store.delete_user_data(user_id)
    assert store.store_interaction(record(user_id)) == ""
    assert store.get_user_profile(user_id) is None
    reopened = ResilientMemoryStore(store.config, store.mongo)
    try:
        assert reopened.local.is_deleted(user_id)
        reopened.replay()
        assert store.mongo.db.user_profiles.find_one({"_id": user_id}) is None
        assert store.mongo.db.interactions.count_documents({"user_id": user_id}) == 0
        assert store.mongo.db.face_signatures.count_documents({"user_id": user_id}) == 0
        assert reopened.get_user_profile(other)
    finally:
        reopened.close()


def test_delete_racing_remote_upsert_cannot_resurrect(store):
    user_id = enroll(store)
    store.replay()
    store.store_interaction(record(user_id))
    entered, release = threading.Event(), threading.Event()
    put = store.mongo.put

    def slow_put(*args):
        entered.set()
        assert release.wait(2)
        put(*args)

    store.mongo.put = slow_put
    worker = threading.Thread(target=store.replay)
    worker.start()
    assert entered.wait(2)
    store.delete_user_data(user_id)
    release.set()
    worker.join(2)
    store.replay()
    assert store.mongo.db.interactions.count_documents({"user_id": user_id}) == 0


def test_stale_ack_cannot_drop_new_revision(store):
    enroll(store)
    seq, col, _, doc = store.local.pending()[0]
    doc["updated_at"] = now()
    store.local.put(col, doc)
    store.local.ack(seq)
    assert store.local.depth() == 1


def test_expiry_purges_outbox_and_prevents_recall(store):
    rec = record()
    rec.timestamp = now() - timedelta(days=91)
    store.store_interaction(rec)
    assert store.retrieve_context("python", session_id="session") == []
    assert store.purge_expired() == 1
    assert store.local.depth() == 0


def test_callbacks_capture_consent_at_turn_start(store):
    presence = PresenceState()
    ingestor = MemoryIngestor(store, presence)
    user_id = enroll(store)
    try:
        ingestor.on_user("private name")
        presence.set(Presence(user_id, True, True, True, True))
        ingestor.on_agent("response")
        ingestor.queue.join()
        assert store.local.list("interactions", all_users=True) == []
        ingestor.on_user("python")
        ingestor.on_gemini("some object")
        ingestor.on_agent("robotics")
        ingestor.queue.join()
        docs = store.retrieve_context("python", user_id)
        assert len(docs) == 1 and docs[0]["gemini_analysis"] == "some object"
    finally:
        ingestor.close()


def test_recall_timeout_does_not_queue_or_spawn_unbounded(store):
    user_id = enroll(store)
    presence = PresenceState()
    presence.set(Presence(user_id, True, True, True))
    retriever = MemoryRetriever(store, presence, "session")
    release = threading.Event()
    original = store.retrieve_context
    store.retrieve_context = lambda *a, **k: (release.wait(3) and []) or []
    try:
        start = time.monotonic()
        assert retriever.recall("python", user_id) == ""
        assert time.monotonic() - start < 0.6
        start = time.monotonic()
        for _ in range(50):
            assert retriever.recall("python", user_id) == ""
        assert time.monotonic() - start < 0.1
    finally:
        release.set()
        store.retrieve_context = original
        retriever.close()
        time.sleep(0.02)


def test_corrupt_remote_uses_local_copy(store):
    user_id = enroll(store)
    rec = record(user_id)
    store.store_interaction(rec)
    store.replay()
    raw = store.mongo.db.interactions.find_one({"_id": rec._id})
    raw["private"] = "corrupt"
    assert store._decode("interactions", raw)["input_text"] == rec.input_text


def test_consent_requires_boolean_and_current_face(store):
    presence = PresenceState()
    identifier = FaceIdentifier(store, presence)
    consent = ConsentManager(store, presence, identifier)
    for value in [False, "false", "true", 1, None]:
        consent.remember(value)
    assert store.local.list("user_profiles", all_users=True) == []
    consent.remember(True)
    assert presence.user_id is None
    identifier.current_signature = [1.0, 0.0]
    assert "remember you" in consent.remember(True, "Ada")
    assert presence.user_id
    user_id = presence.user_id
    assert store.identify_user([1.0, 0.0])[0] == user_id
    consent.forget()
    assert presence.user_id is None
    assert store.identify_user([1.0, 0.0]) is None


def test_sensitive_not_embedded_and_no_personalization_without_consent(store):
    calls = []
    store.embedder = SimpleNamespace(
        embed=lambda text, **kwargs: calls.append(text) or [1.0, 0.0]
    )
    user_id = enroll(store)
    store.store_interaction(record(user_id, "My medical diagnosis and python"))
    assert calls == []
    profile = store.get_user_profile(user_id)
    profile["consents"]["use_for_personalization"] = False
    store.local.put(
        "user_profiles",
        {k: v for k, v in profile.items() if k not in ["display_name", "preferences"]},
    )
    assert store.retrieve_context("python", user_id) == []


def test_concurrent_writes_have_no_duplicates(store):
    user_id = enroll(store)
    records = [record(user_id, f"python {i}") for i in range(30)]
    threads = [
        threading.Thread(target=store.store_interaction, args=(rec,)) for rec in records
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    store.replay()
    assert store.mongo.db.interactions.count_documents({}) == len(records)


def test_face_requires_two_agreeing_matches_and_clears_on_absence(store):
    import numpy as np

    user_id = enroll(store)
    store.associate_face(FaceSignature([1.0, 0.0], user_id), user_id)
    presence = PresenceState()
    identifier = FaceIdentifier(
        store, presence, SimpleNamespace(signature=lambda crop: [1.0, 0.0])
    )
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    identifier.submit(frame, (0, 0, 100, 100))
    assert identifier.busy.acquire(timeout=1)
    identifier.busy.release()
    assert presence.user_id is None
    identifier.last_run = 0
    identifier.submit(frame, (0, 0, 100, 100))
    assert identifier.busy.acquire(timeout=1)
    identifier.busy.release()
    assert presence.user_id == user_id
    identifier.last_seen = 0
    identifier.submit(frame, None)
    assert presence.user_id is None
    assert identifier.current_signature is None


def test_camera_does_not_wait_for_consent_lock(store):
    identifier = FaceIdentifier(store, PresenceState())
    held, release = threading.Event(), threading.Event()

    def hold():
        with identifier.lock:
            held.set()
            release.wait(2)

    worker = threading.Thread(target=hold)
    worker.start()
    assert held.wait(1)
    try:
        start = time.monotonic()
        identifier.submit(None, None)
        assert time.monotonic() - start < 0.01
    finally:
        release.set()
        worker.join()


def test_hydrate_recovers_profiles_and_respects_local_deletion(store, tmp_path):
    user_id = enroll(store)
    store.associate_face(FaceSignature([1.0, 0.0], user_id), user_id)
    store.replay()
    from dataclasses import replace

    fresh = ResilientMemoryStore(
        replace(store.config, local_path=str(tmp_path / "fresh.sqlite3")), store.mongo
    )
    try:
        fresh.hydrate_profiles()
        assert fresh.identify_user([1.0, 0.0])[0] == user_id
        fresh.delete_user_data(user_id)
        fresh.hydrate_profiles()
        assert fresh.get_user_profile(user_id) is None
    finally:
        fresh.close()


def test_schema_rejects_missing_timestamp(store):
    from jarvis.memory.schemas import upgrade, validate

    user_id = enroll(store)
    rec = record(user_id)
    store.store_interaction(rec)
    doc = store.local.get("interactions", rec._id)
    del doc["timestamp"]
    with pytest.raises(ValidationError):
        validate("interactions", doc)
    with pytest.raises(ValidationError):
        upgrade({"schema_version": "future"})


def test_embedding_failure_is_backfilled_without_private_text(store):
    user_id = enroll(store)

    def unavailable(*a, **k):
        raise TimeoutError

    store.embedder = SimpleNamespace(embed=unavailable)
    rec = record(user_id, "Alice likes python")
    store.store_interaction(rec)
    assert store.local.get("interactions", rec._id)["embedding_pending"]
    calls = []
    store.embedder = SimpleNamespace(
        embed=lambda text: calls.append(text) or [1.0, 0.0]
    )
    store.backfill()
    doc = store.local.get("interactions", rec._id)
    assert not doc["embedding_pending"]
    assert calls == ["python"]


def test_local_keyword_search_finds_older_records_beyond_recent_window(store):
    user_id = enroll(store)
    old = record(user_id, "music")
    old.timestamp = now() - timedelta(days=2)
    store.store_interaction(old)
    for _ in range(110):
        store.store_interaction(record(user_id, "python"))
    assert store.retrieve_context("music", user_id)[0]["_id"] == old._id


def test_backfill_finds_pending_records_beyond_recent_window(store):
    user_id = enroll(store)
    old = record(user_id)
    old.timestamp = now() - timedelta(days=2)
    store.store_interaction(old)
    doc = store.local.get("interactions", old._id)
    doc["embedding_pending"] = True
    store.local.put("interactions", doc)
    for _ in range(110):
        store.store_interaction(record(user_id))
    store.embedder = SimpleNamespace(embed=lambda text: [1.0, 0.0])
    store.backfill()
    assert not store.local.get("interactions", old._id)["embedding_pending"]


def test_callback_enqueue_latency_is_bounded():
    ingestor = MemoryIngestor(
        SimpleNamespace(store_interaction=lambda rec: None), PresenceState()
    )
    try:
        samples = []
        for _ in range(100):
            start = time.perf_counter()
            ingestor.enqueue(record())
            samples.append(time.perf_counter() - start)
        assert sorted(samples)[94] < 0.005
    finally:
        ingestor.close()
