"""Idempotent collection, validator, TTL and Atlas search-index provisioning."""

import json
from copy import deepcopy

from dotenv import load_dotenv
from pymongo.operations import SearchIndexModel

from jarvis.memory.config import MemoryConfig
from jarvis.memory.connection import ConnectionManager
from jarvis.memory.schemas import SCHEMAS


def mongo_schema(schema):
    schema = deepcopy(schema)
    if isinstance(schema, dict):
        schema.pop("format", None)
        if "const" in schema:
            schema["enum"] = [schema.pop("const")]
        schema = {k: mongo_schema(v) for k, v in schema.items()}
    elif isinstance(schema, list):
        schema = [mongo_schema(v) for v in schema]
    return schema


def provision(db, dim, search=True):
    for name, schema in SCHEMAS.items():
        schema = mongo_schema(schema)
        for field in ("timestamp", "expires_at", "updated_at", "created_at"):
            if field in schema.get("properties", {}) or field in schema.get(
                "required", []
            ):
                schema.setdefault("properties", {})[field] = {"bsonType": "date"}
        validator = {"$jsonSchema": schema}
        if name not in db.list_collection_names():
            db.create_collection(name, validator=validator)
        else:
            db.command(
                {"collMod": name, "validator": validator, "validationAction": "error"}
            )
    db.interactions.create_index([("user_id", 1), ("timestamp", -1)])
    db.interactions.create_index("expires_at", expireAfterSeconds=0)
    db.user_profiles.create_index("updated_at")
    db.face_signatures.create_index("user_id")
    definitions = {
        "interactions_vec": {
            "fields": [
                {
                    "type": "vector",
                    "path": "embedding",
                    "numDimensions": dim,
                    "similarity": "cosine",
                },
                {"type": "filter", "path": "user_id"},
                {"type": "filter", "path": "privacy_level"},
            ]
        },
        "interactions_text": {
            "mappings": {
                "dynamic": False,
                "fields": {
                    "context": {
                        "type": "document",
                        "fields": {
                            "topics": {"type": "string"},
                            "entities": {"type": "string"},
                        },
                    }
                },
            }
        },
    }
    if search:
        try:
            existing = {
                item["name"]: item for item in db.interactions.list_search_indexes()
            }
            for name, definition in definitions.items():
                if name not in existing:
                    db.interactions.create_search_index(
                        SearchIndexModel(
                            name=name,
                            definition=definition,
                            type="vectorSearch" if name.endswith("vec") else "search",
                        )
                    )
                elif existing[name].get("latestDefinition") != definition:
                    db.interactions.update_search_index(name, definition)
        except Exception as exc:
            print(
                f"Search index creation unavailable ({type(exc).__name__}). In Atlas, open the interactions collection,"
            )
            print(
                "Search & Vector Search → Create Index → JSON Editor, then use these names and definitions:"
            )
            print(json.dumps(definitions, indent=2))
    db.system_config.replace_one(
        {"_id": "schema"},
        {"_id": "schema", "schema_version": "1.0", "settings": {"embedding_dim": dim}},
        upsert=True,
    )
    return definitions


def main():
    load_dotenv()
    config = MemoryConfig.from_env()
    if not config.enabled or not config.uri:
        raise SystemExit(
            "Set MEMORY_ENABLED=true, ENCRYPTION_KEY and MONGODB_ATLAS_URI first"
        )
    # Provisioning issues collection/validator/index-management commands that
    # can legitimately take longer than the runtime's 2s operation budget.
    connection = ConnectionManager(config, timeout_ms=20000)
    try:
        provision(
            connection.database,
            config.embedding_dim,
            search=bool(config.embedding_model),
        )
        print(
            "Provisioned validators and indexes. Search indexes build asynchronously; wait for READY in Atlas."
        )
    finally:
        connection.close()


if __name__ == "__main__":
    main()
