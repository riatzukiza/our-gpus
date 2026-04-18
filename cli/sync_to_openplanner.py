#!/usr/bin/env python
"""CLI command to sync discovered GPU hosts to OpenPlanner.

Usage:
    # Sync all online hosts with GPU
    uv run python cli/sync_to_openplanner.py --status online --has-gpu

    # Sync first 100 discovered hosts
    uv run python cli/sync_to_openplanner.py --status discovered --limit 100

    # Sync all hosts (dry run)
    uv run python cli/sync_to_openplanner.py --dry-run

    # Sync without graph nodes (faster)
    uv run python cli/sync_to_openplanner.py --no-graph-nodes
"""

import argparse
import json
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlmodel import Session, select

from app.config import settings
from app.db import Host, HostModel, Model, init_db
from app.openplanner_sync import (
    host_to_event,
    host_to_graph_node_event,
    host_to_model_edge_events,
    sync_hosts_to_openplanner_sync,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Sync discovered GPU hosts to OpenPlanner")
    parser.add_argument(
        "--status",
        choices=["online", "offline", "discovered", "error", "unknown"],
        help="Filter hosts by status",
    )
    parser.add_argument(
        "--has-gpu",
        action="store_true",
        help="Only sync hosts with GPU detected",
    )
    parser.add_argument(
        "--no-gpu",
        action="store_true",
        help="Only sync hosts without GPU detected",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Maximum number of hosts to sync",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=settings.openplanner_batch_size,
        help="Batch size for OpenPlanner API calls",
    )
    parser.add_argument(
        "--no-graph-nodes",
        action="store_true",
        help="Skip graph.node and graph.edge events (faster)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be synced without sending to OpenPlanner",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON",
    )

    args = parser.parse_args()

    # Check configuration
    if not args.dry_run and not settings.openplanner_sync_enabled:
        logger.error("OpenPlanner sync is disabled. Set OPENPLANNER_SYNC_ENABLED=true")
        sys.exit(1)

    logger.info(f"OpenPlanner URL: {settings.openplanner_url}")
    logger.info(f"Sync enabled: {settings.openplanner_sync_enabled}")

    # Initialize database
    init_db()

    with Session(init_db.engine) as session:
        # Build query
        query = select(Host).order_by(Host.last_seen.desc())

        if args.status:
            query = query.where(Host.status == args.status)

        if args.has_gpu:
            query = query.where(Host.gpu != None)  # noqa: E711
        elif args.no_gpu:
            query = query.where(Host.gpu == None)  # noqa: E711

        if args.limit:
            query = query.limit(args.limit)

        hosts = list(session.exec(query).all())
        logger.info(f"Found {len(hosts)} hosts to sync")

        if not hosts:
            logger.info("No hosts to sync")
            return

        # Fetch models for each host
        host_models: dict[int, list[dict]] = {}
        for host in hosts:
            if host.id is None:
                continue
            host_model_records = session.exec(
                select(HostModel, Model)
                .join(Model, HostModel.model_id == Model.id)
                .where(HostModel.host_id == host.id)
            ).all()

            host_models[host.id] = [
                {
                    "name": model.name,
                    "family": model.family,
                    "parameters": model.parameters,
                    "loaded": hm.loaded,
                    "vram_usage_mb": hm.vram_usage_mb,
                }
                for hm, model in host_model_records
            ]

    if args.dry_run:
        # Show what would be synced
        events = []
        for host in hosts:
            models = host_models.get(host.id, [])
            events.append(host_to_event(host, models))
            if not args.no_graph_nodes:
                events.append(host_to_graph_node_event(host, models))
                events.extend(host_to_model_edge_events(host, models))

        logger.info(f"Dry run: would sync {len(events)} events for {len(hosts)} hosts")

        if args.json:
            print(json.dumps({"events": events[:5], "total": len(events)}, indent=2))
        else:
            # Show sample events
            print("\n=== Sample Events ===\n")
            for event in events[:3]:
                print(f"Event: {event['id']}")
                print(f"  Kind: {event['kind']}")
                print(f"  Text: {event.get('text', '')[:100]}...")
                print(f"  Meta: {json.dumps(event.get('meta', {}), indent=4)}")
                print()

        print(f"\nTotal: {len(events)} events for {len(hosts)} hosts")
        return

    # Perform sync
    result = sync_hosts_to_openplanner_sync(
        hosts,
        host_models=host_models,
        include_graph_nodes=not args.no_graph_nodes,
    )

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        logger.info(f"Sync result: {result}")

    # Exit with error code if sync failed
    if result.get("status") == "failed":
        sys.exit(1)


if __name__ == "__main__":
    main()
