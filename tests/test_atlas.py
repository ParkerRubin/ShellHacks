"""Explicitly opt-in, isolated live Atlas tests. Never uses MONGODB_ATLAS_URI."""

import os
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from pymongo import MongoClient
from pymongo.errors import WriteError

from jarvis.memory.config import MemoryConfig
from jarvis.memory.models import InteractionRecord, UserProfile
from jarvis.memory.mongo_store import MongoStore
from jarvis.memory.store import ResilientMemoryStore
from scripts.provision import provision

pytestmark = pytest.mark.atlas


@pytest.fixture
def atlas(tmp_path):
    uri = os.getenv("MONGODB_ATLAS_URI_TEST")
    if not uri:
        pytest.skip("MONGODB_ATLAS_URI_TEST is not configured")
    client = MongoClient(uri, tls=True, tz_aware=True, serverSelectionTimeoutMS=3000)
    db = client["jarvis_test_" + uuid4().hex]
    store = None
    try:
        provision(db, 768, search=False)
        config = MemoryConfig(
            key=Fernet.generate_key().decode(),
            local_path=str(tmp_path / "atlas.sqlite3"),
        )
        store = ResilientMemoryStore(config, MongoStore(db))
        yield store
    finally:
        if store:
            store.close()
        client.drop_database(db.name)
        client.close()


def test_atlas_validation_ttl_replay_delete(atlas):
    db = atlas.mongo.db
    with pytest.raises(WriteError):
        db.interactions.insert_one({"_id": "invalid"})
    assert any(i.get("expireAfterSeconds") == 0 for i in db.interactions.list_indexes())
    user_id = atlas.store_user_profile(
        UserProfile(
            consents={
                "store_personal_data": True,
                "store_face_data": False,
                "use_for_personalization": True,
            }
        )
    )
    record = InteractionRecord("python robot", "mongodb", "atlas-test", user_id)
    atlas.store_interaction(record)
    atlas.replay()
    atlas.replay()
    assert db.interactions.count_documents({"_id": record._id}) == 1
    atlas.delete_user_data(user_id)
    atlas.replay()
    assert db.interactions.count_documents({"user_id": user_id}) == 0
