"""Validate/upgrade local encrypted records and queue updates to Atlas."""

from dotenv import load_dotenv

from jarvis.memory import build_memory
from jarvis.memory.schemas import upgrade, validate


def main():
    load_dotenv()
    memory = build_memory()
    if not memory.enabled:
        raise SystemExit("Memory is unavailable")
    try:
        for collection in ("interactions", "user_profiles", "face_signatures"):
            for doc in memory.store.local.list(
                collection, all_users=True, limit=100000
            ):
                migrated = upgrade(doc)
                validate(collection, migrated)
                if migrated != doc:
                    memory.store.local.put(
                        collection, migrated, pending=memory.store.mongo is not None
                    )
        print("Validated current schema. No historical migrations are registered yet.")
    finally:
        memory.close()


if __name__ == "__main__":
    main()
