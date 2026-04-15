#!/usr/bin/env python
"""Sync selected our-gpus Ollama hosts into Proxx as dedicated `ollama-*` providers.

Why:
- Proxx can auto-discover providers whose ids start with `ollama-` from its SQL credential store.
- Once registered, Proxx will include these hosts in its Ollama catalog and route matching model
  requests to them (without using Factory).

Typical flow (local dev):
1) Ensure our-gpus API is running + hosts are probed so status/models are accurate.
2) Run this script to upsert providers into Proxx.
3) Restart Proxx so it re-discovers dynamic `ollama-*` routes.

Example:
  uv run python cli/sync_to_proxx.py \
    --proxx-url http://127.0.0.1:8790 \
    --proxx-token "$OPENPLANNER_PROXX_AUTH_TOKEN" \
    --status online --has-gpu --limit 10 \
    --allowed-cidr 10.0.0.0/8 --allowed-cidr 192.168.0.0/16
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import sys
from pathlib import Path

import httpx

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlmodel import Session, select

from app.config import settings
from app.db import Host, init_db


DEFAULT_ALLOWED_CIDRS = [
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "127.0.0.0/8",
]


def parse_cidrs(values: list[str]) -> list[ipaddress.IPv4Network]:
    cidrs: list[ipaddress.IPv4Network] = []
    for raw in values:
        raw = raw.strip()
        if not raw:
            continue
        net = ipaddress.ip_network(raw, strict=False)
        if isinstance(net, ipaddress.IPv6Network):
            # Ignore for now (Proxx+Ollama over v6 not part of this script yet)
            continue
        cidrs.append(net)
    return cidrs


def ip_allowed(ip: str, cidrs: list[ipaddress.IPv4Network]) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False

    if isinstance(addr, ipaddress.IPv6Address):
        return False

    return any(addr in net for net in cidrs)


def provider_id_for_host(prefix: str, ip: str, port: int) -> str:
    safe_ip = ip.replace(".", "-")
    return f"{prefix}-{safe_ip}-{port}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync our-gpus hosts into Proxx as ollama-* providers")
    parser.add_argument("--proxx-url", default=os.environ.get("PROXX_URL", "http://127.0.0.1:8790"))
    parser.add_argument("--proxx-token", default=os.environ.get("PROXX_AUTH_TOKEN", "").strip())
    parser.add_argument("--provider-prefix", default=os.environ.get("PROXX_OLLAMA_PROVIDER_PREFIX", "ollama-ourgpu"))
    parser.add_argument(
        "--dummy-api-key",
        default=os.environ.get("PROXX_OLLAMA_DUMMY_API_KEY", "ollama"),
        help="Non-empty bearer token sent upstream by Proxx (many Ollama servers ignore it).",
    )

    parser.add_argument(
        "--status",
        choices=["online", "offline", "discovered", "error", "unknown"],
        default="online",
        help="Host status filter (matches our-gpus Host.status)",
    )
    parser.add_argument("--has-gpu", action="store_true", help="Only sync hosts with GPU detected")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument(
        "--allowed-cidr",
        action="append",
        default=[],
        help="Allowed CIDR (repeatable). Defaults to RFC1918 + loopback when omitted.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")

    args = parser.parse_args()

    if not args.dry_run and not args.proxx_token:
        raise SystemExit("Missing --proxx-token (or env PROXX_AUTH_TOKEN)")

    allowed_raw: list[str] = args.allowed_cidr if args.allowed_cidr else DEFAULT_ALLOWED_CIDRS
    allowed_cidrs = parse_cidrs(allowed_raw)

    init_db()

    with Session(init_db.engine) as session:
        query = select(Host).where(Host.status == args.status)
        if args.has_gpu:
            query = query.where(Host.gpu != None)  # noqa: E711
        query = query.order_by(Host.latency_ms)
        if args.limit and args.limit > 0:
            query = query.limit(args.limit * 10)  # overfetch then CIDR-filter

        candidates = list(session.exec(query).all())

    selected: list[dict[str, object]] = []
    for host in candidates:
        if host.ip is None or host.port is None:
            continue
        if not ip_allowed(host.ip, allowed_cidrs):
            continue
        selected.append(
            {
                "id": host.id,
                "ip": host.ip,
                "port": host.port,
                "latency_ms": host.latency_ms,
                "gpu": host.gpu,
                "gpu_vram_mb": host.gpu_vram_mb,
                "status": host.status,
            }
        )
        if len(selected) >= args.limit:
            break

    if args.dry_run:
        payload = {
            "proxx_url": args.proxx_url,
            "provider_prefix": args.provider_prefix,
            "selected": selected,
            "selected_count": len(selected),
        }
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"Would sync {len(selected)} hosts into Proxx (dry-run).")
            for entry in selected[:10]:
                print(f"- {entry['ip']}:{entry['port']} (gpu={entry.get('gpu')}, latency_ms={entry.get('latency_ms')})")
        return

    headers = {
        "Authorization": f"Bearer {args.proxx_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    results: list[dict[str, object]] = []
    with httpx.Client(timeout=15.0) as client:
        for entry in selected:
            ip = str(entry["ip"])
            port = int(entry["port"])
            provider_id = provider_id_for_host(args.provider_prefix, ip, port)
            base_url = f"http://{ip}:{port}"

            body = {
                "providerId": provider_id,
                "baseUrl": base_url,
                "apiKey": args.dummy_api_key,
            }

            resp = client.post(f"{args.proxx_url.rstrip('/')}/api/v1/credentials/provider", headers=headers, json=body)
            ok = resp.status_code in (200, 201)
            results.append(
                {
                    "providerId": provider_id,
                    "baseUrl": base_url,
                    "ok": ok,
                    "status": resp.status_code,
                    "detail": resp.text[:500],
                }
            )

    payload = {
        "synced": len([r for r in results if r.get('ok')]),
        "attempted": len(results),
        "results": results,
        "note": "Restart Proxx after syncing so it re-discovers dynamic ollama-* routes.",
    }

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Synced {payload['synced']}/{payload['attempted']} providers into Proxx.")
        for r in results[:10]:
            status = "ok" if r.get("ok") else f"http {r.get('status')}"
            print(f"- {r['providerId']} -> {r['baseUrl']} ({status})")


if __name__ == "__main__":
    main()
