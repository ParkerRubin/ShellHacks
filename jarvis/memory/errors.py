class MemoryStoreError(Exception):
    """A memory operation could not complete."""


class StoreConnectionError(MemoryStoreError):
    pass


class ValidationError(MemoryStoreError):
    pass


class PrivacyError(MemoryStoreError):
    pass


class FallbackError(MemoryStoreError):
    pass
