#!/usr/bin/env python3
"""
CLI utility to trigger re-probing of Ollama hosts
"""

import argparse
import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlmodel import Session, select

from app.db import Host, HostModel, Model, engine, init_db
from app.probe import ProbeService


async def probe_hosts(hosts, concurrency):
    """Probe multiple hosts with concurrency control"""
    service = ProbeService()
    service.concurrency = concurrency

    semaphore = asyncio.Semaphore(concurrency)

    async def probe_with_limit(host):
        async with semaphore:
            return await service.probe_host(host)

    tasks = [probe_with_limit(host) for host in hosts]
    return await asyncio.gather(*tasks)


def main():
    parser = argparse.ArgumentParser(description='Re-probe Ollama hosts')
    parser.add_argument('--all', action='store_true', help='Probe all hosts')
    parser.add_argument('--status', choices=['online', 'offline', 'error', 'unknown'],
                       help='Filter by status')
    parser.add_argument('--model', help='Filter by model name (partial match)')
    parser.add_argument('--family', help='Filter by model family')
    parser.add_argument('--gpu', action='store_true', help='Only GPU-enabled hosts')
    parser.add_argument('--stale', type=int, help='Hosts not seen in N hours')
    parser.add_argument('--limit', type=int, default=100, help='Maximum hosts to probe')
    parser.add_argument('--concurrency', type=int, default=50, help='Concurrent probes')

    args = parser.parse_args()

    if not any([args.all, args.status, args.model, args.family, args.gpu, args.stale]):
        print("Error: Specify at least one filter (--all, --status, --model, etc.)")
        sys.exit(1)

    # Initialize database
    init_db()

    with Session(engine) as session:
        # Build query
        query = select(Host)

        if args.status:
            query = query.where(Host.status == args.status)

        if args.model:
            query = query.join(HostModel).join(Model).where(
                Model.name.contains(args.model)
            )

        if args.family:
            query = query.join(HostModel).join(Model).where(
                Model.family == args.family
            )

        if args.gpu:
            query = query.where(Host.gpu_vram_mb > 0)

        if args.stale:
            cutoff = datetime.utcnow() - timedelta(hours=args.stale)
            query = query.where(Host.last_seen < cutoff)

        if not args.all:
            query = query.limit(args.limit)

        hosts = session.exec(query).all()

        if not hosts:
            print("No hosts match the criteria")
            return

        print(f"Found {len(hosts)} hosts to probe")
        print(f"Using {args.concurrency} concurrent connections")
        print()

        # Run probes
        loop = asyncio.get_event_loop()
        results = loop.run_until_complete(probe_hosts(hosts, args.concurrency))

        # Process results
        success_count = 0
        error_count = 0
        timeout_count = 0

        for host, probe in zip(hosts, results, strict=False):
            if probe.status == "success":
                success_count += 1
                print(f"✓ {host.ip}:{host.port} - {probe.duration_ms:.0f}ms")
            elif probe.status == "timeout":
                timeout_count += 1
                print(f"⏱ {host.ip}:{host.port} - timeout")
            else:
                error_count += 1
                print(f"✗ {host.ip}:{host.port} - {probe.error[:50]}")

            # Save probe result
            session.add(probe)

            # Update host status
            session.add(host)

        session.commit()

        print("\nProbe complete:")
        print(f"  Success: {success_count}")
        print(f"  Timeout: {timeout_count}")
        print(f"  Error: {error_count}")


if __name__ == "__main__":
    main()
