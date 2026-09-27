import hashlib
import json

from cryptography.fernet import Fernet

from .errors import PrivacyError


class FieldCipher:
    """Encrypt the entire private payload, including Gemini output and preferences."""

    def __init__(self, key):
        self.fernet = Fernet(key.encode())
        self.key_id = hashlib.sha256(key.encode()).hexdigest()[:16]

    def encrypt_fields(self, doc, fields):
        result = dict(doc)
        private = {key: result.pop(key) for key in fields if key in result}
        raw = json.dumps(
            private, sort_keys=True, ensure_ascii=False, allow_nan=False
        ).encode()
        # Checksum stays inside authenticated ciphertext; plaintext hashes can leak short values.
        payload = {"data": private, "checksum": hashlib.sha256(raw).hexdigest()}
        result["private"] = self.fernet.encrypt(
            json.dumps(payload, ensure_ascii=False).encode()
        ).decode()
        result["key_id"] = self.key_id
        return result

    def decrypt_fields(self, doc):
        try:
            payload = json.loads(self.fernet.decrypt(doc["private"].encode()))
            raw = json.dumps(
                payload["data"], sort_keys=True, ensure_ascii=False, allow_nan=False
            ).encode()
            if hashlib.sha256(raw).hexdigest() != payload["checksum"]:
                raise ValueError("checksum")
            return {**doc, **payload["data"]}
        except Exception:
            raise PrivacyError(
                "Encrypted document failed integrity verification"
            ) from None
