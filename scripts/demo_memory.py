"""Offline demo by default. --atlas uses the configured DB and creates demo records."""

import argparse
import os
import tempfile

from cryptography.fernet import Fernet
from dotenv import load_dotenv

from jarvis.memory.config import MemoryConfig
from jarvis.memory.models import InteractionRecord, UserProfile
from jarvis.memory.store import ResilientMemoryStore


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--atlas", action="store_true")
    args = parser.parse_args()
    load_dotenv()
    with tempfile.TemporaryDirectory() as directory:
        connection = mongo = embedder = None
        if args.atlas:
            from jarvis.memory.connection import ConnectionManager
            from jarvis.memory.mongo_store import MongoStore

            config = MemoryConfig.from_env()
            if not config.uri or not config.enabled:
                raise SystemExit("Enable memory and configure Atlas first")
            connection = ConnectionManager(config)
            mongo = MongoStore(connection.database)
        else:
            config = MemoryConfig(
                key=Fernet.generate_key().decode(),
                local_path=directory + "/demo.sqlite3",
            )
        if args.atlas and config.embedding_model:
            from jarvis.memory.embeddings import GeminiEmbedder

            embedder = GeminiEmbedder(config, os.environ["GEMINI_API_KEY"])
        store = ResilientMemoryStore(config, mongo, connection, embedder)
        profile = UserProfile(
            display_name="Demo user",
            consents={
                "store_personal_data": True,
                "store_face_data": False,
                "use_for_personalization": True,
            },
        )
        user_id = store.store_user_profile(profile)
        try:
            store.store_interaction(
                InteractionRecord(
                    "We built a Python robot at the hackathon.",
                    "Let's add MongoDB memory.",
                    "demo",
                    user_id,
                )
            )
            print("Stored an encrypted sample exchange.")
            print(
                "Local lexical/recency:",
                [
                    d["input_text"]
                    for d in store.retrieve_context("robot python", user_id)
                ],
            )
            if connection:
                store.online = connection.ping()
                store.replay()
                print("Atlas health:", store.health())
                print("Atlas lexical:", len(mongo.search("python", user_id)))
                if embedder:
                    vector = embedder.embed("robotics python", query=True)
                    print(
                        "Atlas semantic:",
                        len(mongo.search("robotics python", user_id, vector)),
                    )
                else:
                    print("Semantic search disabled: configure EMBEDDING_MODEL first.")
        finally:
            print("Deletion:", store.delete_user_data(user_id))
            store.replay()
            store.close()


if __name__ == "__main__":
    main()
