"""Hardware-free facade smoke check; never uses the user's Atlas database."""

import os
import tempfile
from unittest.mock import patch

from cryptography.fernet import Fernet

from jarvis.memory import build_memory


def main():
    with tempfile.TemporaryDirectory() as directory:
        base = {
            "MEMORY_ENABLED": "true",
            "ENCRYPTION_KEY": Fernet.generate_key().decode(),
            "LOCAL_FALLBACK_PATH": directory + "/smoke.sqlite3",
        }
        for label, changes, enabled in [
            ("local", {}, True),
            ("disabled", {"MEMORY_ENABLED": "false"}, False),
            ("bad-key", {"ENCRYPTION_KEY": "invalid"}, False),
        ]:
            with patch.dict(os.environ, {**base, **changes}, clear=True):
                memory = build_memory()
                assert memory.enabled is enabled
                memory.close()
                print(label, "OK")


if __name__ == "__main__":
    main()
