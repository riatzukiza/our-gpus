from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Any

from app.cidr_split import load_exclude_list

DEFAULT_SHODAN_QUERY_MAX_LENGTH = 900
DEFAULT_SHODAN_MAX_QUERIES = 24


@dataclass(frozen=True)
class ShodanQueryPlan:
    base_query: str
    target: str
    port: str
    queries: list[str]
    total_excludes: int
    applied_excludes: int
    omitted_excludes: int
    max_query_length: int


def _parse_target_segments(target: str) -> list[ipaddress.IPv4Network]:
    segments = [segment.strip() for segment in target.split(",") if segment.strip()]
    if not segments:
        raise RuntimeError("Scan target is required")

    networks: list[ipaddress.IPv4Network] = []
    for segment in segments:
        if "-" in segment:
            start_raw, end_raw = [part.strip() for part in segment.split("-", 1)]
            start_ip = ipaddress.IPv4Address(start_raw)
            end_ip = ipaddress.IPv4Address(end_raw)
            if int(start_ip) > int(end_ip):
                raise RuntimeError(f"Invalid IP range target: {segment}")
            networks.extend(ipaddress.summarize_address_range(start_ip, end_ip))
            continue

        network = ipaddress.ip_network(segment, strict=False)
        if network.version != 4:
            raise RuntimeError(f"IPv6 targets are not supported: {segment}")
        networks.append(network)

    return networks


def _base_query_terms(
    base_query: str, port: str, target_network: ipaddress.IPv4Network | None
) -> list[str]:
    terms: list[str] = []
    normalized = base_query.strip()
    if normalized:
        terms.append(normalized)
    if f"port:{port}" not in normalized:
        terms.append(f"port:{port}")
    if target_network and str(target_network) != "0.0.0.0/0":
        terms.append(f"net:{target_network}")
    return terms


def build_shodan_query_plan(
    *,
    target: str,
    port: str,
    exclude_files: str = "",
    base_query: str = "",
    max_query_length: int = DEFAULT_SHODAN_QUERY_MAX_LENGTH,
    max_queries: int = DEFAULT_SHODAN_MAX_QUERIES,
) -> ShodanQueryPlan:
    """Build Shodan search queries.

    Shodan's database already excludes private/reserved ranges, so we don't
    need to apply our exclude list to the queries. This keeps queries short
    and avoids hitting the free-tier query length limits.
    """
    target_networks = _parse_target_segments(target)

    queries: list[str] = []

    for target_network in target_networks:
        if len(queries) >= max_queries:
            break

        prefix = " ".join(_base_query_terms(base_query, port, target_network)).strip()
        if prefix and len(prefix) <= max_query_length:
            queries.append(prefix)

    # If no target-specific queries fit, fall back to base query only
    if not queries:
        prefix = " ".join(_base_query_terms(base_query, port, None)).strip()
        if prefix:
            queries = [prefix]

    return ShodanQueryPlan(
        base_query=base_query.strip(),
        target=target,
        port=port,
        queries=queries,
        total_excludes=0,
        applied_excludes=0,
        omitted_excludes=0,
        max_query_length=max_query_length,
    )


def filter_shodan_matches(
    *,
    matches: list[dict[str, Any]],
    target: str,
    port: str,
    exclude_files: str,
) -> list[str]:
    target_networks = _parse_target_segments(target)
    exclude_networks = [
        ipaddress.ip_network(entry, strict=False) for entry in load_exclude_list(exclude_files)
    ]
    filtered: list[str] = []
    seen: set[str] = set()

    for match in matches:
        ip_raw = match.get("ip_str")
        if not isinstance(ip_raw, str):
            continue

        try:
            address = ipaddress.ip_address(ip_raw)
        except ValueError:
            continue

        if address.version != 4:
            continue
        if any(address in exclude for exclude in exclude_networks):
            continue
        if not any(address in network for network in target_networks):
            continue

        resolved_port = match.get("port")
        normalized_port = str(resolved_port) if isinstance(resolved_port, int) else port
        host = f"{address}:{normalized_port}"
        if host in seen:
            continue
        seen.add(host)
        filtered.append(host)

    return filtered
