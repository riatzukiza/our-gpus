#!/usr/bin/env python3
"""
CLI utility to ingest JSON/JSONL files into the Ollama discovery database
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime

from sqlmodel import Session

from app.db import Scan, engine, init_db
from app.ingest import IngestService


def main():
    parser = argparse.ArgumentParser(
        description="Ingest JSON/JSONL data into Ollama discovery database"
    )
    parser.add_argument("file", help="Path to JSON/JSONL file")
    parser.add_argument("--mapping", type=str, help="JSON string of field mappings")
    parser.add_argument("--auto-detect", action="store_true", help="Auto-detect field mappings")
    parser.add_argument("--batch-size", type=int, default=1000, help="Batch size for processing")
    parser.add_argument("--dry-run", action="store_true", help="Preview without importing")

    args = parser.parse_args()

    if not os.path.exists(args.file):
        print(f"Error: File '{args.file}' not found")
        sys.exit(1)

    # Initialize database
    init_db()

    with Session(engine) as session:
        # Read file
        with open(args.file, "rb") as f:
            file_data = f.read()

        service = IngestService(session)

        # Infer schema
        print("Analyzing file schema...")
        schema = service.infer_schema(file_data, limit=20)

        print(f"Found fields: {', '.join(schema['fields'].keys())}")
        print(f"Sample records: {len(schema['sample_records'])}")

        # Determine mapping
        mapping = {}
        if args.mapping:
            mapping = json.loads(args.mapping)
        elif args.auto_detect:
            # Auto-detect common fields
            fields = schema["fields"].keys()
            if "ip" in fields:
                mapping["ip"] = "ip"
            elif "host" in fields:
                mapping["ip"] = "host"

            if "port" in fields:
                mapping["port"] = "port"

            if "country" in fields:
                mapping["geo_country"] = "country"
            if "city" in fields:
                mapping["geo_city"] = "city"

            print(f"Auto-detected mapping: {json.dumps(mapping)}")
        else:
            # Interactive mapping
            print("\nConfigure field mapping:")
            target_fields = ["ip", "port", "geo_country", "geo_city"]

            for target in target_fields:
                print(f"\n{target} (required={'ip' in target}):")
                print("Available source fields:")
                for i, field in enumerate(schema["fields"].keys(), 1):
                    print(f"  {i}. {field}")
                print("  0. Skip")

                choice = input("Select field number: ").strip()
                if choice and choice != "0":
                    try:
                        idx = int(choice) - 1
                        source_field = list(schema["fields"].keys())[idx]
                        mapping[target] = source_field
                    except (ValueError, IndexError):
                        print("Invalid selection")

        if "ip" not in mapping:
            print("Error: IP field mapping is required")
            sys.exit(1)

        print(f"\nUsing mapping: {json.dumps(mapping, indent=2)}")

        if args.dry_run:
            print("\nDry run - previewing first 10 records:")
            for count, record in enumerate(service.parse_stream(file_data, mapping), 1):
                print(f"  {record}")
                if count >= 10:
                    break
            print("\nDry run complete. No data was imported.")
            return

        # Create scan record
        scan = Scan(
            source_file=args.file,
            mapping_json=json.dumps(mapping),
            status="processing",
            started_at=datetime.utcnow(),
        )
        session.add(scan)
        session.commit()

        # Process file
        print(f"\nProcessing file with batch size {args.batch_size}...")
        total_success = 0
        total_failed = 0
        batch = []

        for i, record in enumerate(service.parse_stream(file_data, mapping)):
            batch.append(record)

            if len(batch) >= args.batch_size:
                success, failed = service.process_batch(batch, scan.id, auto_probe_new_hosts=True)
                total_success += success
                total_failed += failed
                batch = []

                if (i + 1) % 10000 == 0:
                    print(f"  Processed {i + 1} records...")

        # Process remaining
        if batch:
            success, failed = service.process_batch(batch, scan.id, auto_probe_new_hosts=True)
            total_success += success
            total_failed += failed

        # Complete scan
        scan.status = "completed"
        scan.completed_at = datetime.utcnow()
        scan.processed_rows = total_success + total_failed
        scan.stats = {"success": total_success, "failed": total_failed}
        session.commit()

        print("\nIngestion complete!")
        print(f"  Success: {total_success}")
        print(f"  Failed: {total_failed}")
        print(f"  Scan ID: {scan.id}")


if __name__ == "__main__":
    main()
