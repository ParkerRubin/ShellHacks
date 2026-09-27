"""Generate once; keep the key outside Git and back it up securely.

Do not replace an existing key without decrypting/re-encrypting all local and
Atlas documents first. Old data cannot be recovered without its original key.
"""

from cryptography.fernet import Fernet

if __name__ == "__main__":
    print(Fernet.generate_key().decode())
