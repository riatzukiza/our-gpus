import io
import json
import logging
import socket
import struct
from collections.abc import Generator
from datetime import datetime
from typing import Any

import ijson
from sqlmodel import Session

from app.config import settings
from app.db import Host

logger = logging.getLogger(__name__)


class IngestService:
    def __init__(self, session: Session):
        self.session = session
        self.batch_size = settings.batch_size

    def infer_schema(self, data: bytes, limit: int = 10) -> dict[str, Any]:
        """Sample first N records to infer schema"""
        schema = {"fields": {}, "sample_records": []}

        try:
            content = data.decode("utf-8").strip()
            lines = content.split("\n")

            # Check if this looks like a plain text list of ip:port
            first_line = lines[0].strip() if lines else ""
            if ":" in first_line and not (first_line.startswith("{") or first_line.startswith("[")):
                # This is a text file format
                schema["fields"] = {"ip": "str", "port": "int"}
                for _i, line in enumerate(lines[:limit]):
                    line = line.strip()
                    if line and ":" in line:
                        parts = line.split(":")
                        if len(parts) >= 2:
                            ip = parts[0].strip()
                            try:
                                port = int(parts[1].strip())
                                schema["sample_records"].append({"ip": ip, "port": port})
                            except ValueError:
                                continue
                return schema
        except UnicodeDecodeError:
            pass

        # Try JSON array first (since JSONL would parse '[' as invalid)
        try:
            content = data.decode("utf-8").strip()
            if content.startswith("["):
                parser = ijson.items(io.BytesIO(data), "item")
                for i, record in enumerate(parser):
                    if i >= limit:
                        break
                    schema["sample_records"].append(record)
                    for key, value in record.items():
                        if key not in schema["fields"]:
                            schema["fields"][key] = type(value).__name__
                return schema
        except Exception:
            pass

        # Try JSONL format
        try:
            lines = data.decode("utf-8").split("\n")[:limit]
            for line in lines:
                if line.strip():
                    record = json.loads(line)
                    schema["sample_records"].append(record)
                    for key, value in record.items():
                        if key not in schema["fields"]:
                            schema["fields"][key] = type(value).__name__
        except Exception:
            pass

        return schema

    def parse_stream(
        self, data: bytes, mapping: dict[str, str]
    ) -> Generator[dict[str, Any], None, None]:
        """Stream parse JSON/JSONL/TXT with field mapping"""
        # Try plain text format first (ip:port per line)
        try:
            content = data.decode("utf-8").strip()
            lines = content.split("\n")

            # Check if this looks like a plain text list of ip:port
            first_line = lines[0].strip() if lines else ""
            if ":" in first_line and not (first_line.startswith("{") or first_line.startswith("[")):
                for line in lines:
                    line = line.strip()
                    if line and ":" in line:
                        parts = line.split(":")
                        if len(parts) >= 2:
                            ip = parts[0].strip()
                            try:
                                port = int(parts[1].strip())
                                yield {"ip": ip, "port": port}
                            except ValueError:
                                logger.warning(f"Invalid port in line: {line}")
                                continue
                return
        except UnicodeDecodeError:
            pass

        # Try JSONL format
        try:
            for line in data.decode("utf-8").split("\n"):
                if line.strip():
                    record = json.loads(line)
                    yield self._map_record(record, mapping)
        except Exception:
            # Fall back to JSON array
            parser = ijson.items(io.BytesIO(data), "item")
            for record in parser:
                yield self._map_record(record, mapping)

    def _map_record(self, record: dict[str, Any], mapping: dict[str, str]) -> dict[str, Any]:
        """Map source fields to our schema"""
        if not mapping:
            ip = record.get("ip")
            if isinstance(ip, int):
                ip = self._ip_int_to_str(ip)

            port = record.get("port")
            if port is None:
                ports = record.get("ports")
                if isinstance(ports, list):
                    for port_entry in ports:
                        if isinstance(port_entry, dict) and port_entry.get("port") is not None:
                            port = port_entry["port"]
                            break

            return {
                "ip": ip,
                "port": port if port is not None else 11434,
                "geo_country": record.get("geo_country"),
                "geo_city": record.get("geo_city"),
            }

        result = {}

        for our_field, source_field in mapping.items():
            if source_field in record:
                value = record[source_field]

                # Convert IP integers to strings
                if our_field == "ip" and isinstance(value, int):
                    value = self._ip_int_to_str(value)

                result[our_field] = value

        # Set defaults
        result.setdefault("ip", None)
        result.setdefault("port", 11434)  # Ollama default port

        return result

    def _ip_int_to_str(self, ip_int: int) -> str:
        """Convert integer IP to string"""
        return socket.inet_ntoa(struct.pack("!I", ip_int))

    def process_batch(
        self,
        records: list,
        scan_id: int,  # noqa: ARG002
        auto_probe_new_hosts: bool = False,
    ) -> tuple[int, int]:
        """Process a batch of records"""
        success = 0
        failed = 0
        new_hosts: list[Host] = []

        for record in records:
            if not record.get("ip"):
                failed += 1
                continue

            # Upsert host
            existing = (
                self.session.query(Host)
                .filter(Host.ip == record["ip"], Host.port == record.get("port", 11434))
                .first()
            )

            if not existing:
                host = Host(
                    ip=record["ip"],
                    port=record.get("port", 11434),
                    geo_country=record.get("geo_country"),
                    geo_city=record.get("geo_city"),
                    status="discovered",
                )
                self.session.add(host)
                new_hosts.append(host)
                success += 1
            else:
                # Update geo if provided
                existing.last_seen = datetime.utcnow()
                if record.get("geo_country"):
                    existing.geo_country = record["geo_country"]
                if record.get("geo_city"):
                    existing.geo_city = record["geo_city"]
                success += 1

        self.session.commit()

        if auto_probe_new_hosts and new_hosts:
            from worker.tasks import queue_host_probes

            queue_host_probes([host.id for host in new_hosts if host.id is not None])

        return success, failed
