import os
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Config:
    crm_origin: str
    secret: str
    database: str = "/data/queue.sqlite3"
    max_jobs: int = 100000
    min_free_bytes: int = 268435456
    manifest_ttl: int = 300
    send_interval: float = 0.2

    def validate(self):
        origin = urlsplit(self.crm_origin)
        _ = origin.port
        if any(c.isspace() for c in self.crm_origin):
            raise ValueError("CRM_ORIGIN must not contain whitespace")
        if origin.scheme not in {"http", "https"} or not origin.hostname or origin.username or origin.password or origin.path or origin.query or origin.fragment:
            raise ValueError("CRM_ORIGIN must be an HTTP(S) origin, without path or credentials")
        if len(self.secret) < 32 or self.secret.startswith("REPLACE_"):
            raise ValueError("RELAY_SECRET must contain at least 32 characters")
        if self.max_jobs < 1 or self.min_free_bytes < 0 or not 30 <= self.manifest_ttl <= 3600 or self.send_interval < 0.05:
            raise ValueError("Invalid queue limits")

    @classmethod
    def from_env(cls):
        value = cls(crm_origin=os.environ["CRM_ORIGIN"].rstrip("/"), secret=os.environ["RELAY_SECRET"],
            database=os.getenv("QUEUE_DATABASE", "/data/queue.sqlite3"),
            max_jobs=int(os.getenv("QUEUE_MAX_JOBS", "100000")),
            min_free_bytes=int(os.getenv("QUEUE_MIN_FREE_BYTES", "268435456")),
            manifest_ttl=int(os.getenv("MANIFEST_TTL_SECONDS", "300")),
            send_interval=float(os.getenv("SEND_INTERVAL_SECONDS", "0.2")))
        value.validate()
        return value
