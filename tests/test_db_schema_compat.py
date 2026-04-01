import sqlite3
from pathlib import Path

from sqlalchemy import inspect

import app.db as db_module
from app.db import init_db


def test_init_db_adds_missing_host_geo_columns_for_legacy_sqlite(tmp_path: Path):
    db_path = tmp_path / "legacy.sqlite"
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            """
            CREATE TABLE hosts (
                id INTEGER PRIMARY KEY,
                ip TEXT NOT NULL,
                port INTEGER NOT NULL,
                last_seen TEXT,
                first_seen TEXT,
                latency_ms REAL,
                api_version TEXT,
                os TEXT,
                arch TEXT,
                ram_gb REAL,
                gpu TEXT,
                gpu_vram_mb INTEGER,
                geo_country TEXT,
                geo_city TEXT,
                status TEXT,
                last_error TEXT
            )
            """
        )
        connection.commit()
    finally:
        connection.close()

    init_db(f"sqlite:///{db_path}")

    inspector = inspect(db_module.engine)
    columns = {column["name"] for column in inspector.get_columns("hosts")}
    assert "geo_lat" in columns
    assert "geo_lon" in columns
