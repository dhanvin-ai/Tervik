from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    database_url: str = "sqlite:///./.data/tervik.db"
    admin_token: str | None = None
    demo_enabled: bool = True
    cors_origins: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173")
    max_body_bytes: int = 4 * 1024 * 1024
    clickhouse_url: str | None = None
    clickhouse_username: str = "default"
    clickhouse_password: str = ""
    clickhouse_database: str = "tervik"

    @classmethod
    def from_env(cls):
        token = os.getenv("TERVIK_ADMIN_TOKEN") or None
        demo_default = "false" if token else "true"
        url = os.getenv("DATABASE_URL", "sqlite:///./.data/tervik.db")
        if url.startswith("postgres://"):
            url = "postgresql+psycopg://" + url[len("postgres://"):]
        elif url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url[len("postgresql://"):]
        return cls(
            database_url=url,
            admin_token=token,
            demo_enabled=os.getenv("TERVIK_DEMO_ENABLED", demo_default).lower() == "true",
            cors_origins=tuple(x.strip() for x in os.getenv(
                "TERVIK_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
            ).split(",") if x.strip()),
            max_body_bytes=int(os.getenv("TERVIK_MAX_BODY_BYTES", str(4 * 1024 * 1024))),
            clickhouse_url=os.getenv("CLICKHOUSE_URL") or None,
            clickhouse_username=os.getenv("CLICKHOUSE_USER", "default"),
            clickhouse_password=os.getenv("CLICKHOUSE_PASSWORD", ""),
            clickhouse_database=os.getenv("CLICKHOUSE_DATABASE", "tervik"),
        )
