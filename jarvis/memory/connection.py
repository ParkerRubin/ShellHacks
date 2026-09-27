import threading

from pymongo import MongoClient
from pymongo.errors import AutoReconnect, ConnectionFailure, NetworkTimeout

from .models import HealthStatus


class ConnectionManager:
    def __init__(self, config):
        self.client = MongoClient(
            config.uri,
            tls=True,
            connect=False,
            tz_aware=True,
            serverSelectionTimeoutMS=2000,
            connectTimeoutMS=2000,
            socketTimeoutMS=2000,
            timeoutMS=2000,
        )
        self.database = self.client[config.database]
        self.state = "OFFLINE"
        self.failures = 0
        self.stop = threading.Event()

    def ping(self):
        try:
            self.client.admin.command("ping")
            self.state, self.failures = "ONLINE", 0
            return True
        except Exception:
            self.failed()
            return False

    def failed(self):
        self.failures += 1
        self.state = "OFFLINE" if self.failures >= 3 else "DEGRADED"

    def with_retry(self, fn):
        for attempt in range(3):
            try:
                return fn()
            except (AutoReconnect, ConnectionFailure, NetworkTimeout):
                self.failed()
                if attempt == 2 or self.stop.wait(1.5**attempt):
                    raise

    def health(self):
        return HealthStatus(self.state, consecutive_failures=self.failures)

    def close(self):
        self.stop.set()
        self.client.close()
