"""Optional best-effort ClickHouse mirror. SQL remains the source of truth."""
import json
import logging
import re
from urllib.parse import urlparse
from .db import utc

logger = logging.getLogger(__name__)


def mirror_events(settings, events):
    if not settings.clickhouse_url or not events:
        return
    client = None
    try:
        import clickhouse_connect
        database = settings.clickhouse_database
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", database):
            raise ValueError("invalid ClickHouse database identifier")
        parsed = urlparse(settings.clickhouse_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("CLICKHOUSE_URL must be an http(s) URL")
        client = clickhouse_connect.get_client(
            host=parsed.hostname, port=parsed.port or (8443 if parsed.scheme == "https" else 8123),
            secure=parsed.scheme == "https", username=settings.clickhouse_username,
            password=settings.clickhouse_password, connect_timeout=3, send_receive_timeout=5,
        )
        client.command(f"CREATE DATABASE IF NOT EXISTS {database}")
        client.command(f"""CREATE TABLE IF NOT EXISTS {database}.events (
            project_id String, event_id String, conversation_id String, timestamp DateTime64(6, 'UTC'),
            role LowCardinality(String), payload String
        ) ENGINE = MergeTree ORDER BY (project_id, timestamp, event_id)""")
        rows = [[e["project_id"], e["id"], e["conversation_id"], utc(e["datetime"]), e["role"],
                 json.dumps(e["payload"], allow_nan=False)] for e in events]
        client.insert(f"{database}.events", rows,
                      column_names=["project_id", "event_id", "conversation_id", "timestamp", "role", "payload"])
    except Exception as error:
        # Never log event payloads, URLs, credentials, or exception messages.
        logger.warning("ClickHouse mirror failed (%s); SQL events remain available. No retry queue configured.",
                       type(error).__name__)
    finally:
        if client is not None:
            client.close()
