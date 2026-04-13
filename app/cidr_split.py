"""
CIDR block decomposition for masscan scanning.

Splits the IPv4 space into blocks of a given prefix length.
Default: /16 blocks (65,536 blocks × 65,536 IPs each).
"""

from __future__ import annotations

import ipaddress
import math
from pathlib import Path


def split_ipv4(prefix_len: int = 16) -> list[str]:
    """
    Split 0.0.0.0/0 into blocks of the given prefix length.

    prefix_len=16 → 65,536 /16 blocks
    prefix_len=20 → 1,048,576 /20 blocks (finer granularity)
    """
    base = ipaddress.ip_network("0.0.0.0/0")
    return [str(net) for net in base.subnets(new_prefix=prefix_len)]


def estimate_scan_duration(
    ips_per_block: int,
    rate: int = 100_000,
    overhead_factor: float = 1.3,
) -> float:
    """
    Estimate scan duration in seconds for a single block.

    Args:
        block_count: number of blocks (unused, kept for API consistency)
        ips_per_block: IPs in each block (e.g., 65536 for /16)
        rate: masscan rate (packets/sec)
        overhead_factor: account for masscan overhead (default 1.3x)
    """
    return (ips_per_block / rate) * overhead_factor


def optimal_prefix_for_target_duration(
    target_seconds: float = 60,
    rate: int = 100_000,
    overhead_factor: float = 20.0,
) -> int:
    """
    Find the CIDR prefix that results in blocks completing within target_seconds.

    We want the LARGEST block (SMALLST prefix number) that still fits within our target.
    For target=120s at 100kpps with 20x overhead: ~600K IPs max
    That means prefix needs to be /13 or higher (smaller blocks).

    /13 = 524K IPs (fits)
    /12 = 1M IPs (too big)

    So we iterate from large blocks to small, return the first one that fits.
    """
    ips_per_block = max(1, int(target_seconds * rate / overhead_factor))
    # prefix N gives 2^(32-N) addresses, so:
    # /0 = 4B IPs, /8 = 16M IPs, /16 = 65K IPs, /24 = 256 IPs, /32 = 1 IP
    # We want the largest block (smallest prefix) that fits within our budget
    for prefix in range(0, 33):  # 0 to 32
        block_size = 1 << (32 - prefix)
        if block_size <= ips_per_block:
            return prefix
    return 32  # fallback: single IP blocks (will never hit this)</think>


def _range_to_start_end(start_ip: str, end_ip: str) -> tuple[int, int]:
    """Convert a start-end IP range to integer bounds."""
    start = int(ipaddress.ip_address(start_ip))
    end = int(ipaddress.ip_address(end_ip))
    return start, end


def _summarize_address_range(start_ip: str, end_ip: str) -> list[str]:
    """Convert a start-end IP range into a list of CIDR blocks."""
    start, end = _range_to_start_end(start_ip, end_ip)
    if start > end:
        return []
    cidrs = list(
        ipaddress.summarize_address_range(
            ipaddress.ip_address(start),
            ipaddress.ip_address(end),
        )
    )
    return [str(cidr) for cidr in cidrs]


def _normalize_exclude_entry(entry: str) -> list[str]:
    """Normalize a single exclude entry to a list of CIDR strings."""
    entry = entry.strip()
    if not entry or entry.startswith("#"):
        return []

    if "-" in entry:
        parts = entry.split("-", 1)
        if len(parts) == 2:
            start_ip = parts[0].strip()
            end_ip = parts[1].strip()
            try:
                return _summarize_address_range(start_ip, end_ip)
            except ValueError:
                return []
        return []

    try:
        ipaddress.ip_network(entry, strict=False)
        return [entry]
    except ValueError:
        return []


def load_exclude_list(path: str = "/app/excludes.conf") -> list[str]:
    """Load and normalize exclude entries from file into CIDR strings."""
    try:
        content = Path(path).read_text()
    except FileNotFoundError:
        return []

    normalized: list[str] = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        normalized.extend(_normalize_exclude_entry(line))

    return normalized


def filter_blocks(
    blocks: list[str],
    excludes: list[str],
) -> list[str]:
    """Remove blocks that overlap with exclude list."""
    if not excludes:
        return blocks

    exclude_nets = [ipaddress.ip_network(cidr, strict=False) for cidr in excludes]
    filtered = []

    for block in blocks:
        block_net = ipaddress.ip_network(block, strict=False)
        if any(block_net.overlaps(ex) for ex in exclude_nets):
            continue
        filtered.append(block)

    return filtered


def block_info(cidr: str) -> dict:
    """Return info about a CIDR block."""
    net = ipaddress.ip_network(cidr, strict=False)
    return {
        "cidr": str(net),
        "network_address": str(net.network_address),
        "broadcast_address": str(net.broadcast_address),
        "num_addresses": net.num_addresses,
        "prefix_len": net.prefixlen,
    }


# Pre-computed default blocks (cached)
_DEFAULT_BLOCKS: dict[tuple[int, str], list[str]] = {}


def get_default_blocks(
    prefix_len: int = 16,
    exclude_file: str = "/app/excludes.conf",
) -> list[str]:
    """Get filtered default blocks, cached."""
    cache_key = (prefix_len, exclude_file)
    if cache_key not in _DEFAULT_BLOCKS:
        blocks = split_ipv4(prefix_len)
        excludes = load_exclude_list(exclude_file)
        _DEFAULT_BLOCKS[cache_key] = filter_blocks(blocks, excludes)
    return _DEFAULT_BLOCKS[cache_key]
