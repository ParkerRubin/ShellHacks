"""Hardware/network-free 10,000-record benchmark in a disposable database."""

import statistics
import tempfile
import time
from datetime import timedelta

from cryptography.fernet import Fernet

from jarvis.memory.config import MemoryConfig
from jarvis.memory.models import InteractionRecord, UserProfile, now, uid
from jarvis.memory.store import ResilientMemoryStore


def main():
    with tempfile.TemporaryDirectory() as directory:
        store = ResilientMemoryStore(
            MemoryConfig(
                key=Fernet.generate_key().decode(),
                local_path=directory + "/bench.sqlite3",
            )
        )
        try:
            user_id = store.store_user_profile(
                UserProfile(
                    consents={
                        "store_personal_data": True,
                        "store_face_data": False,
                        "use_for_personalization": True,
                    }
                )
            )
            rec = InteractionRecord("python robotics", "mongodb", "benchmark", user_id)
            store.store_interaction(rec)
            template = store.local.get("interactions", rec._id)
            for i in range(9999):
                store.local.put(
                    "interactions",
                    {
                        **template,
                        "_id": uid(),
                        "timestamp": now() - timedelta(seconds=i),
                    },
                    pending=False,
                )
            timings = []
            for _ in range(30):
                start = time.perf_counter()
                assert store.retrieve_context("python", user_id)
                timings.append((time.perf_counter() - start) * 1000)
            print(
                f"10,000 records: local recall p50={statistics.median(timings):.1f}ms p95={sorted(timings)[28]:.1f}ms"
            )
        finally:
            store.close()


if __name__ == "__main__":
    main()
