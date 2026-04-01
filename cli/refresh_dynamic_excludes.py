from __future__ import annotations

import argparse
import ipaddress
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx


@dataclass(frozen=True)
class ExcludeSource:
    name: str
    url: str


DEFAULT_OUTPUT = Path("app/excludes.generated.conf")
DEFAULT_SOURCES = (
    ExcludeSource("aws", "https://ip-ranges.amazonaws.com/ip-ranges.json"),
    ExcludeSource("gcp", "https://www.gstatic.com/ipranges/cloud.json"),
    ExcludeSource("cloudflare", "https://www.cloudflare.com/ips-v4"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Refresh generated cloud/provider exclusion ranges for our-gpus scans.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Where to write the generated exclude file.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="HTTP timeout in seconds for each upstream source.",
    )
    return parser.parse_args()


def sort_key(cidr: str) -> tuple[int, int, int]:
    network = ipaddress.ip_network(cidr, strict=False)
    return (int(network.network_address), network.prefixlen, network.version)


def normalize_prefixes(prefixes: list[str]) -> list[str]:
    normalized = {
        str(ipaddress.ip_network(prefix.strip(), strict=False))
        for prefix in prefixes
        if prefix.strip()
    }
    return sorted(normalized, key=sort_key)


def fetch_aws_prefixes(client: httpx.Client, source: ExcludeSource) -> list[str]:
    payload = client.get(source.url).json()
    return [
        entry["ip_prefix"]
        for entry in payload.get("prefixes", [])
        if isinstance(entry, dict) and isinstance(entry.get("ip_prefix"), str)
    ]


def fetch_gcp_prefixes(client: httpx.Client, source: ExcludeSource) -> list[str]:
    payload = client.get(source.url).json()
    return [
        entry["ipv4Prefix"]
        for entry in payload.get("prefixes", [])
        if isinstance(entry, dict) and isinstance(entry.get("ipv4Prefix"), str)
    ]


def fetch_cloudflare_prefixes(client: httpx.Client, source: ExcludeSource) -> list[str]:
    response = client.get(source.url)
    return [line.strip() for line in response.text.splitlines() if line.strip()]


def refresh_dynamic_excludes(output_path: Path, timeout: float) -> Path:
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        fetched = {
            "aws": fetch_aws_prefixes(client, DEFAULT_SOURCES[0]),
            "gcp": fetch_gcp_prefixes(client, DEFAULT_SOURCES[1]),
            "cloudflare": fetch_cloudflare_prefixes(client, DEFAULT_SOURCES[2]),
        }

    lines = [
        "# Auto-generated dynamic excludes for our-gpus scans.",
        "#",
        f"# Generated at: {datetime.now(UTC).isoformat()}",
        "# Sources:",
        *[f"# - {source.name}: {source.url}" for source in DEFAULT_SOURCES],
        "",
    ]

    for source in DEFAULT_SOURCES:
        prefixes = normalize_prefixes(fetched[source.name])
        lines.append(f"# {source.name.upper()}")
        lines.extend(prefixes)
        lines.append("")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines).rstrip() + "\n")
    return output_path


def main() -> int:
    args = parse_args()
    output = refresh_dynamic_excludes(args.output, args.timeout)
    print(json.dumps({"output": str(output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
