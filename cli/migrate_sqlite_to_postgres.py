from __future__ import annotations

import argparse
from datetime import datetime

from sqlalchemy import MetaData, Table, create_engine, func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.sql.sqltypes import Boolean, DateTime, Float, Integer

from app.db import SQLModel

TABLE_ORDER = ["hosts", "models", "scans", "host_models", "probes"]


def _build_engine(database_url: str) -> Engine:
    kwargs = {"future": True, "pool_pre_ping": True}
    if database_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(database_url, **kwargs)


def _normalize_value(value, column):
    if value is None:
        return None

    if isinstance(column.type, Boolean) and not isinstance(value, bool):
        return bool(value)
    if isinstance(column.type, DateTime) and isinstance(value, str):
        return datetime.fromisoformat(value)
    if isinstance(column.type, Integer) and isinstance(value, bool):
        return int(value)
    if isinstance(column.type, Integer) and isinstance(value, str) and value.isdigit():
        return int(value)
    if isinstance(column.type, Float) and isinstance(value, str):
        return float(value)
    return value


def _copy_table(
    source_engine: Engine, target_engine: Engine, table_name: str, batch_size: int
) -> int:
    source_meta = MetaData()
    target_meta = MetaData()
    source_table = Table(table_name, source_meta, autoload_with=source_engine)
    target_table = Table(table_name, target_meta, autoload_with=target_engine)

    copied = 0
    with source_engine.connect() as source_conn, target_engine.begin() as target_conn:
        result = source_conn.execute(select(source_table))
        while True:
            rows = result.fetchmany(batch_size)
            if not rows:
                break

            payload = []
            for row in rows:
                row_mapping = row._mapping
                payload.append(
                    {
                        column.name: _normalize_value(row_mapping[column.name], column)
                        for column in target_table.columns
                        if column.name in row_mapping
                    }
                )

            target_conn.execute(target_table.insert(), payload)
            copied += len(payload)

    return copied


def _ensure_target_empty(target_engine: Engine) -> None:
    with target_engine.connect() as conn:
        for table_name in TABLE_ORDER:
            table = Table(table_name, MetaData(), autoload_with=target_engine)
            count = conn.execute(select(func.count()).select_from(table)).scalar_one()
            if count:
                raise RuntimeError(f"target table '{table_name}' is not empty ({count} rows)")


def _reset_sequences(target_engine: Engine) -> None:
    with target_engine.begin() as conn:
        for table_name in TABLE_ORDER:
            conn.execute(
                text(
                    f"SELECT setval(pg_get_serial_sequence('{table_name}', 'id'), "
                    f"COALESCE((SELECT MAX(id) FROM {table_name}), 1), true)"
                )
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Copy our-gpus data from SQLite into Postgres")
    parser.add_argument("--source", required=True, help="source database URL")
    parser.add_argument("--target", required=True, help="target database URL")
    parser.add_argument("--batch-size", type=int, default=1000, help="rows per insert batch")
    args = parser.parse_args()

    source_engine = _build_engine(args.source)
    target_engine = _build_engine(args.target)

    SQLModel.metadata.create_all(target_engine)
    _ensure_target_empty(target_engine)

    for table_name in TABLE_ORDER:
        copied = _copy_table(source_engine, target_engine, table_name, args.batch_size)
        print(f"copied {copied} rows into {table_name}")

    _reset_sequences(target_engine)
    print("sequence reset complete")


if __name__ == "__main__":
    main()
