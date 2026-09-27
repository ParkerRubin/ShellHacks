"""Optional memory facade. Importing it requires no camera, API, or database."""

import logging
import os

from .models import PresenceState


class NullMemory:
    enabled = False

    def __init__(self):
        self.presence = PresenceState()
        self.identifier = self.ingestor = self.retriever = self.consent = self

    def submit(self, *args, **kwargs):
        pass

    def on_user(self, *args):
        pass

    def on_agent(self, *args):
        pass

    def on_gemini(self, *args):
        pass

    def close(self):
        pass

    def recall(self, *args):
        return ""

    def remember(self, *args, **kwargs):
        return "Memory is disabled; I cannot save personal data."

    def forget(self, *args):
        return (
            "Memory is disabled; ask the operator to delete any previously saved data."
        )


class Memory:
    enabled = True

    def __init__(self, store, provider=None):
        from .consent import ConsentManager
        from .faces import FaceIdentifier
        from .ingestor import MemoryIngestor
        from .retriever import MemoryRetriever

        self.store = store
        self.presence = PresenceState()
        self.identifier = FaceIdentifier(store, self.presence, provider)
        self.ingestor = MemoryIngestor(store, self.presence)
        self.retriever = MemoryRetriever(store, self.presence, self.ingestor.session_id)
        self.consent = ConsentManager(store, self.presence, self.identifier)
        store.start()

    def close(self):
        self.identifier.close()
        self.retriever.close()
        self.ingestor.close()
        if not self.ingestor.worker.is_alive():
            self.store.close()


def build_memory():
    # Keep kill switch usable without optional persistence dependencies installed.
    if os.getenv("MEMORY_ENABLED", "true").lower() == "false":
        return NullMemory()
    try:
        from .config import MemoryConfig
        from .store import ResilientMemoryStore

        config = MemoryConfig.from_env()
        connection = mongo = embedder = provider = None
        if config.uri:
            from .connection import ConnectionManager
            from .mongo_store import MongoStore

            connection = ConnectionManager(config)
            mongo = MongoStore(connection.database)
        if config.embedding_model and os.getenv("GEMINI_API_KEY"):
            try:
                from .embeddings import GeminiEmbedder

                embedder = GeminiEmbedder(config, os.environ["GEMINI_API_KEY"])
            except Exception:
                logging.warning("memory_embeddings_disabled initialization_failed=true")
        if os.path.isfile(config.face_detection_model) and os.path.isfile(
            config.face_recognition_model
        ):
            try:
                from .faces import OpenCVSFaceProvider

                provider = OpenCVSFaceProvider(config)
            except Exception:
                logging.warning("memory_faces_disabled initialization_failed=true")
        else:
            logging.warning(
                "memory_faces_disabled models_missing=true; run scripts/fetch_models.py"
            )
        return Memory(
            ResilientMemoryStore(config, mongo, connection, embedder), provider
        )
    except Exception as exc:
        # Configuration validation messages are safe; SDK exceptions may contain URIs.
        from .errors import ValidationError

        detail = str(exc) if isinstance(exc, ValidationError) else type(exc).__name__
        logging.error("memory_disabled reason=%s", detail)
        return NullMemory()
