"""
ACO-guided masscan block scanner.

Decomposes the IPv4 space into blocks, uses ant colony optimization
to prioritize which blocks to scan, and runs masscan per-block
with a max duration of 5 minutes each.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.aco import ACOConfig, AntColony
from app.cidr_split import (
    estimate_scan_duration,
    optimal_prefix_for_target_duration,
)
from app.geocode import GeoService

logger = logging.getLogger(__name__)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    from math import asin, cos, radians, sin, sqrt

    earth_radius_km = 6371.0
    lat1_rad, lon1_rad, lat2_rad, lon2_rad = map(radians, (lat1, lon1, lat2, lon2))
    delta_lat = lat2_rad - lat1_rad
    delta_lon = lon2_rad - lon1_rad
    a = sin(delta_lat / 2) ** 2 + cos(lat1_rad) * cos(lat2_rad) * sin(delta_lon / 2) ** 2
    return 2 * earth_radius_km * asin(sqrt(a))


def _cidr_prefix_len(value: str) -> int | None:
    """Extract the CIDR prefix length from a persisted block key."""
    try:
        return int(value.rsplit("/", 1)[1])
    except (IndexError, ValueError):
        return None


@dataclass
class BlockScanResult:
    """Result of scanning a single block."""

    cidr: str
    scan_uuid: str
    started_at: datetime
    completed_at: datetime
    output_file: str
    log_file: str
    hosts_found: int
    duration_ms: float
    success: bool
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "cidr": self.cidr,
            "scan_uuid": self.scan_uuid,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "output_file": self.output_file,
            "log_file": self.log_file,
            "hosts_found": self.hosts_found,
            "duration_ms": round(self.duration_ms, 2),
            "success": self.success,
            "error": self.error,
        }


@dataclass
class CurrentScanJob:
    """Current running block scan."""

    cidr: str
    scan_uuid: str
    started_at: datetime
    output_file: str
    log_file: str
    port: str
    rate: int
    estimated_duration_s: float

    def to_dict(self) -> dict:
        return {
            "cidr": self.cidr,
            "scan_uuid": self.scan_uuid,
            "started_at": self.started_at.isoformat(),
            "output_file": self.output_file,
            "log_file": self.log_file,
            "port": self.port,
            "rate": self.rate,
            "estimated_duration_s": round(self.estimated_duration_s, 2),
        }


@dataclass
class SchedulerConfig:
    """Configuration for the ACO block scheduler."""

    port: str = "11434"
    rate: int = 100_000
    max_block_duration_s: float = 120.0  # timeout buffer (target is ~60s)
    min_scan_interval_s: float = 3600.0  # don't re-scan within 1 hour
    results_dir: str = "/workspace/imports/masscan"
    exclude_file: str = os.environ.get(
        "OUR_GPUS_EXCLUDE_FILES",
        "/app/excludes.conf,/app/excludes.generated.conf",
    )
    router_mac: str = "00:21:59:a0:cf:c1"
    interface: str = os.environ.get("MASSCAN_INTERFACE", "eth0")
    state_file: str = "/workspace/imports/masscan/aco-state.json"
    breathing_room_s: float = 2.0  # pause between blocks
    strategy: str = os.environ.get(
        "OUR_GPUS_DEFAULT_STRATEGY", "tor-connect"
    )  # tor-connect is the safest default path
    tor_max_hosts: int = int(os.environ.get("ACO_TOR_MAX_HOSTS", "256"))  # Smaller for ACO blocks
    tor_concurrency: int = int(os.environ.get("TOR_SCAN_CONCURRENCY", "32"))

    # ACO tuning
    aco_alpha: float = 0.6
    aco_beta: float = 0.4
    aco_decay: float = 0.05
    aco_reinforcement: float = 0.3
    aco_penalty: float = 0.2


class ACOMasscanScheduler:
    """
    ACO-guided masscan scheduler.

    Splits IPv4 into blocks (computed lazily on first start),
    uses ant colony optimization to prioritize scanning order.
    """

    def __init__(
        self,
        config: SchedulerConfig | None = None,
        on_result: Callable[[BlockScanResult], None] | None = None,
    ):
        self.config = config or SchedulerConfig()
        self.on_result = on_result
        self._running = False
        self._thread: threading.Thread | None = None
        self._state_lock = threading.Lock()
        self._scan_lock = threading.Lock()
        self.started_at: datetime | None = None
        self.current_job: CurrentScanJob | None = None
        self.last_error: str | None = None
        self.recent_results: deque[BlockScanResult] = deque(maxlen=40)
        self.block_sampled_hosts: dict[str, set[str]] = {}
        self.block_discovered_hosts: dict[str, set[str]] = {}
        self.geo_service = GeoService()
        self.ip_geo_cache: dict[str, dict[str, object]] = {}
        self.block_geo_cache: dict[str, dict[str, object]] = {}

        aco_config = ACOConfig(
            alpha=self.config.aco_alpha,
            beta=self.config.aco_beta,
            decay=self.config.aco_decay,
            reinforcement=self.config.aco_reinforcement,
            penalty=self.config.aco_penalty,
        )
        self.aco = AntColony(aco_config)

        # Determine optimal prefix based on strategy
        # For tor-connect, we use /16 blocks and let the strategy cap hosts
        # The strategy's build_allowed_host_targets respects tor_max_hosts (default 4096)
        # For masscan/shodan, we use duration-based calculation
        from app.masscan import TOR_CONNECT_STRATEGY, normalize_scan_strategy_name

        strategy_name = normalize_scan_strategy_name(self.config.strategy)
        if strategy_name == TOR_CONNECT_STRATEGY:
            # Use /16 blocks - strategy caps at tor_max_hosts (default 4096)
            # This gives us ~65K blocks which is manageable for ACO
            self.prefix_len = 16
        else:
            # For masscan/shodan, use duration-based calculation
            self.prefix_len = optimal_prefix_for_target_duration(
                target_seconds=self.config.max_block_duration_s,
                rate=self.config.rate,
            )

        self.estimated_block_duration_s = estimate_scan_duration(
            1 << (32 - self.prefix_len),
            self.config.rate,
        )

        self.estimated_block_duration_s = estimate_scan_duration(
            1 << (32 - self.prefix_len),
            self.config.rate,
        )

        logger.info(
            "ACO scheduler: prefix_len=%d (~%d hosts per block, ~%ds at %d rate) strategy=%s",
            self.prefix_len,
            1 << (32 - self.prefix_len),
            round(self.estimated_block_duration_s),
            self.config.rate,
            strategy_name,
        )

        # Blocks loaded lazily in _scan_loop
        self._blocks_loaded = False
        self.blocks: list[str] = []

        # Load persisted state (fast, just reads JSON)
        self._load_state()

    def _ensure_blocks_loaded(self) -> None:
        """Load blocks lazily on first scan.

        For on-the-fly block generation, we don't pre-compute all blocks.
        Instead, we generate candidate blocks as needed and check them against excludes.
        """
        if self._blocks_loaded:
            return

        # Load excludes once for fast checking
        import ipaddress

        from app.cidr_split import collapse_networks, load_exclude_list

        excludes_raw = load_exclude_list(self.config.exclude_file)
        exclude_nets = []
        for e in excludes_raw:
            try:
                net = ipaddress.ip_network(e, strict=False)
                if net.version == 4:
                    exclude_nets.append(net)
            except ValueError:
                continue

        self._collapsed_excludes = collapse_networks(exclude_nets) if exclude_nets else []
        self._blocks_loaded = True

        # Generate a pool of candidate blocks (not all, just a working set)
        self._candidate_pool = self._generate_candidate_pool()
        self.blocks = list(self._candidate_pool.keys())

        logger.info(
            "Loaded %d candidate blocks (prefix /%d) from pool of %d",
            len(self.blocks),
            self.prefix_len,
            len(self._candidate_pool),
        )

    def _generate_candidate_pool(self) -> dict[str, bool]:
        """Generate a pool of candidate blocks, excluding known-bad ranges.

        Returns a dict of cidr -> is_excluded for fast lookup.
        """
        import ipaddress
        import random

        # Generate a diverse set of candidate blocks across the IP space
        candidates = {}
        # Sample blocks across different /8 ranges to ensure diversity
        for first_octet in range(1, 256):
            if first_octet in (0, 10, 100, 127, 169, 172, 192, 198, 203, 224, 240, 255):
                continue  # Skip obvious reserved ranges

            # Generate a few /16 blocks per /8 range
            for _ in range(3):
                second_octet = random.randint(0, 255)
                cidr = f"{first_octet}.{second_octet}.0.0/{self.prefix_len}"
                try:
                    net = ipaddress.ip_network(cidr, strict=False)
                    is_excluded = any(net.overlaps(ex) for ex in self._collapsed_excludes)
                    if not is_excluded:
                        candidates[cidr] = True
                except ValueError:
                    continue

            # Cap the pool size to avoid memory issues
            if len(candidates) >= 10000:
                break

        return candidates

    def _tracked_block_keys_locked(self) -> list[str]:
        """Return the block keys that belong to the current scan space."""
        if self._blocks_loaded:
            return self.blocks
        return [key for key in self.aco.blocks if _cidr_prefix_len(key) == self.prefix_len]

    def _tracked_stats_locked(self) -> dict:
        """Compute stats for the active scan space only."""
        keys = self._tracked_block_keys_locked()
        total = len(keys)
        scanned = 0
        total_yield = 0
        pheromone_total = 0.0

        for key in keys:
            block = self.aco.blocks.get(key)
            if block is None:
                pheromone_total += self.aco.config.initial_pheromone
                continue

            if block.scan_count > 0:
                scanned += 1
            total_yield += block.cumulative_yield
            pheromone_total += block.pheromone

        avg_pheromone = pheromone_total / total if total > 0 else 0.0
        return {
            "total_blocks": total,
            "scanned_blocks": scanned,
            "unscanned_blocks": total - scanned,
            "total_yield": total_yield,
            "avg_pheromone": round(avg_pheromone, 4),
        }

    def start(self) -> None:
        """Start the scanning loop in a background thread."""
        if self._running:
            logger.warning("Scheduler already running")
            return

        self.started_at = datetime.utcnow()
        self._running = True
        self._thread = threading.Thread(target=self._scan_loop, daemon=True, name="aco-masscan")
        self._thread.start()
        logger.info("ACO scheduler started")

    def stop(self) -> bool:
        """Stop the scanning loop."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=30)
        self._save_state()
        logger.info("ACO scheduler stopped")
        return not self.is_busy() and not self.is_alive()

    def scan_one_block(self) -> BlockScanResult | None:
        """Run a single block scan (for manual/testing use)."""
        if not self._scan_lock.acquire(blocking=False):
            raise RuntimeError("block scan already in progress")
        try:
            return self._select_and_scan()
        finally:
            self._scan_lock.release()

    def is_alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def is_busy(self) -> bool:
        with self._state_lock:
            return self.current_job is not None

    def get_stats(self) -> dict:
        """Get current ACO stats."""
        with self._state_lock:
            return self._tracked_stats_locked()

    def get_top_blocks(self, n: int = 20) -> list[dict]:
        """Get top N blocks by pheromone score."""
        results = []
        with self._state_lock:
            ranked_keys = sorted(
                self._tracked_block_keys_locked(),
                key=lambda key: (
                    self.aco.blocks.get(key, None).pheromone
                    if self.aco.blocks.get(key) is not None
                    else self.aco.config.initial_pheromone
                ),
                reverse=True,
            )
            for key in ranked_keys[:n]:
                block = self.aco.blocks.get(key)
                pheromone = (
                    block.pheromone if block is not None else self.aco.config.initial_pheromone
                )
                results.append(
                    {
                        "cidr": key,
                        "pheromone": round(pheromone, 4),
                        "scan_count": block.scan_count if block is not None else 0,
                        "cumulative_yield": block.cumulative_yield if block is not None else 0,
                        "last_scan": (
                            block.last_scan_at.isoformat()
                            if block is not None and block.last_scan_at
                            else None
                        ),
                    }
                )
        return results

    def dashboard_snapshot(self, result_limit: int = 20, block_limit: int = 20) -> dict:
        """Get a UI-friendly dashboard snapshot."""
        with self._state_lock:
            stats = self._tracked_stats_locked()
            current_job = self.current_job.to_dict() if self.current_job else None
            recent_results = [
                result.to_dict() for result in list(self.recent_results)[:result_limit]
            ]

        now = datetime.utcnow()
        if self._running:
            status = "running"
            if not self._blocks_loaded:
                status = "initializing"
        elif current_job or self.is_alive():
            status = "stopping"
        else:
            status = "stopped"

        return {
            "status": status,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "uptime_seconds": (
                round((now - self.started_at).total_seconds(), 2) if self.started_at else None
            ),
            "prefix_len": self.prefix_len,
            "estimated_block_duration_s": round(self.estimated_block_duration_s, 2),
            "config": {
                "port": self.config.port,
                "rate": self.config.rate,
                "max_block_duration_s": self.config.max_block_duration_s,
                "min_scan_interval_s": self.config.min_scan_interval_s,
                "breathing_room_s": self.config.breathing_room_s,
                "router_mac": self.config.router_mac,
                "interface": self.config.interface,
                "exclude_file": self.config.exclude_file,
                "aco_alpha": self.config.aco_alpha,
                "aco_beta": self.config.aco_beta,
                "aco_decay": self.config.aco_decay,
                "aco_reinforcement": self.config.aco_reinforcement,
                "aco_penalty": self.config.aco_penalty,
            },
            "stats": stats,
            "current_job": current_job,
            "recent_results": recent_results,
            "top_blocks": self.get_top_blocks(block_limit) if self._blocks_loaded else [],
            "last_error": self.last_error,
        }

    # -- Internal --

    def _scan_loop(self) -> None:
        """Main scanning loop."""
        # Load blocks lazily on first iteration
        self._ensure_blocks_loaded()

        sweep_count = 0

        while self._running:
            self._scan_lock.acquire()
            try:
                result = self._select_and_scan()
            except Exception as e:
                self.last_error = str(e)
                logger.error("ACO scan loop failed: %s", e)
                time.sleep(max(10.0, self.config.breathing_room_s))
                continue
            finally:
                self._scan_lock.release()

            if result is None:
                # All blocks recently scanned — wait and retry
                logger.info("All blocks recently scanned, waiting 60s")
                time.sleep(60)
                continue

            # Persist state periodically
            sweep_count += 1
            if sweep_count % 10 == 0:
                self._save_state()
                # Evaporate pheromones every 10 scans
                self.aco.evaporate_all()

            if self.config.breathing_room_s > 0:
                time.sleep(self.config.breathing_room_s)

    def _select_and_scan(self) -> BlockScanResult | None:
        """Select a block via ACO and scan it."""
        now = datetime.utcnow()
        candidates = self._eligible_blocks(now)

        if not candidates:
            return None

        geo_weights = self._geo_proximity_weights(candidates)
        with self._state_lock:
            selected = self.aco.select_weighted(candidates, weights=geo_weights, now=now)
        result = self._run_masscan_block(selected)

        # Record in ACO
        with self._state_lock:
            self.aco.record_scan(selected, result.hosts_found, result.duration_ms)
            self.last_error = result.error

        # Notify callback
        if self.on_result:
            try:
                self.on_result(result)
            except Exception as e:
                logger.error("on_result callback failed: %s", e)

        logger.info(
            "Block %s: %d hosts in %.1fs (pheromone=%.3f)",
            selected,
            result.hosts_found,
            result.duration_ms / 1000,
            self.aco.blocks[selected].pheromone,
        )

        return result

    def _eligible_blocks(self, now: datetime) -> list[str]:
        """Return blocks eligible for scanning (not scanned recently)."""
        cutoff = now.timestamp() - self.config.min_scan_interval_s
        eligible = []
        with self._state_lock:
            for block_key in self.blocks:
                block = self.aco.get_or_create(block_key)
                if block.last_scan_at is None or block.last_scan_at.timestamp() < cutoff:
                    eligible.append(block_key)
        return eligible

    def _representative_ip_for_block(self, cidr: str) -> str | None:
        try:
            network = ipaddress.ip_network(cidr, strict=False)
        except ValueError:
            return None

        if network.version != 4:
            return None

        if network.prefixlen >= 31:
            return str(network.network_address)

        usable_hosts = max(network.num_addresses - 2, 1)
        midpoint = int(network.network_address) + 1 + (usable_hosts // 2)
        return str(ipaddress.IPv4Address(midpoint))

    def _lookup_ip_geo(self, ip: str) -> dict[str, object] | None:
        cached = self.ip_geo_cache.get(ip)
        if cached is not None:
            return cached

        try:
            geo = self.geo_service.lookup_ip(ip)
        except Exception as error:  # noqa: BLE001
            logger.debug("Geo lookup failed for %s: %s", ip, error)
            geo = {"status": "failed", "reason": str(error)}

        self.ip_geo_cache[ip] = geo
        return geo

    def _get_block_geo_hint(self, cidr: str) -> dict[str, object] | None:
        cached = self.block_geo_cache.get(cidr)
        if cached is not None:
            return cached

        anchor_ip = self._representative_ip_for_block(cidr)
        if not anchor_ip:
            return None

        geo = self._lookup_ip_geo(anchor_ip) or {}
        block_geo = {
            "ip": anchor_ip,
            "country": geo.get("country"),
            "city": geo.get("city"),
            "lat": geo.get("lat"),
            "lon": geo.get("lon"),
            "status": geo.get("status", "failed"),
        }
        self.block_geo_cache[cidr] = block_geo
        return block_geo

    def _db_geo_anchors(self, limit: int = 128) -> list[dict[str, object]]:
        try:
            from sqlmodel import Session, select

            from app.db import Host, engine

            if engine is None:
                return []

            with Session(engine) as session:
                rows = session.exec(
                    select(Host.ip, Host.geo_country, Host.geo_lat, Host.geo_lon)
                    .where(Host.geo_lat.is_not(None), Host.geo_lon.is_not(None))
                    .order_by(Host.last_seen.desc())
                    .limit(limit)
                ).all()
        except Exception as error:  # noqa: BLE001
            logger.debug("Failed to load DB geo anchors: %s", error)
            return []

        anchors: list[dict[str, object]] = []
        for ip, country, lat, lon in rows:
            if lat is None or lon is None:
                continue
            anchors.append(
                {
                    "ip": ip,
                    "country": country or None,
                    "lat": float(lat),
                    "lon": float(lon),
                }
            )
        return anchors

    def _get_geo_proximity_anchors(self) -> list[dict[str, object]]:
        anchors: list[dict[str, object]] = []
        seen_ips: set[str] = set()

        with self._state_lock:
            discovered_ips = [
                ip
                for hosts in self.block_discovered_hosts.values()
                for ip in sorted(hosts)
                if ip not in seen_ips
            ]

        for ip in discovered_ips[:128]:
            seen_ips.add(ip)
            geo = self._lookup_ip_geo(ip) or {}
            country = geo.get("country")
            lat = geo.get("lat")
            lon = geo.get("lon")
            if country is None and (lat is None or lon is None):
                continue
            anchors.append(
                {
                    "ip": ip,
                    "country": country,
                    "lat": float(lat) if lat is not None else None,
                    "lon": float(lon) if lon is not None else None,
                }
            )

        for anchor in self._db_geo_anchors(limit=128):
            ip = str(anchor.get("ip") or "")
            if not ip or ip in seen_ips:
                continue
            seen_ips.add(ip)
            anchors.append(anchor)

        return anchors

    def _geo_proximity_weights(self, candidates: list[str]) -> dict[str, float] | None:
        anchors = self._get_geo_proximity_anchors()
        if not anchors:
            return None

        weights: dict[str, float] = {}
        for cidr in candidates:
            block_geo = self._get_block_geo_hint(cidr)
            if not block_geo:
                continue

            country = block_geo.get("country")
            latitude = block_geo.get("lat")
            longitude = block_geo.get("lon")
            nearest_km: float | None = None
            nearby_hits = 0
            same_country_hits = sum(
                1 for anchor in anchors if country and anchor.get("country") == country
            )

            if latitude is None or longitude is None:
                if same_country_hits > 0:
                    weights[cidr] = round(1.0 + min(same_country_hits, 3) * 0.25, 4)
                continue

            for anchor in anchors:
                anchor_lat = anchor.get("lat")
                anchor_lon = anchor.get("lon")
                if anchor_lat is None or anchor_lon is None:
                    continue

                distance_km = _haversine_km(
                    float(latitude),
                    float(longitude),
                    float(anchor_lat),
                    float(anchor_lon),
                )
                if nearest_km is None or distance_km < nearest_km:
                    nearest_km = distance_km
                if distance_km <= 750:
                    nearby_hits += 1

            if nearest_km is None:
                if same_country_hits > 0:
                    weights[cidr] = round(1.0 + min(same_country_hits, 3) * 0.25, 4)
                continue

            proximity_boost = 1.0 + max(0.0, (2500.0 - min(nearest_km, 2500.0)) / 2500.0)
            country_boost = 1.0 + min(same_country_hits, 3) * 0.08
            local_density_boost = 1.0 + min(nearby_hits, 4) * 0.12
            weights[cidr] = round(proximity_boost * country_boost * local_density_boost, 4)

        return weights or None

    def _run_scan_block(self, cidr: str) -> BlockScanResult:
        """Run scan against a single CIDR block using configured strategy."""
        from app.masscan import (
            TOR_CONNECT_STRATEGY,
            TOR_SAMPLE_MODE_SPREAD,
            MasscanScanStrategy,
            ScanContext,
            ScanPaths,
            ScanRequest,
            ShodanScanStrategy,
            TorScanStrategy,
            normalize_scan_strategy_name,
        )

        Path(self.config.results_dir).mkdir(parents=True, exist_ok=True)
        scan_uuid = str(uuid.uuid4())[:8]
        log_file = f"{self.config.results_dir}/block-{scan_uuid}.log"
        started_at = datetime.utcnow()

        strategy_name = normalize_scan_strategy_name(self.config.strategy)
        strategy_map = {
            "masscan": MasscanScanStrategy,
            "shodan": ShodanScanStrategy,
            "tor-connect": TorScanStrategy,
        }
        strategy_cls = strategy_map.get(strategy_name)
        if strategy_cls is None:
            raise RuntimeError(f"Unknown strategy: {strategy_name}")
        strategy = strategy_cls()
        previously_sampled_hosts: tuple[str, ...] = ()
        if strategy_name == TOR_CONNECT_STRATEGY:
            with self._state_lock:
                previously_sampled_hosts = tuple(self.block_sampled_hosts.get(cidr, set()))

        output_file = f"{self.config.results_dir}/block-{scan_uuid}{strategy.output_suffix}"

        with self._state_lock:
            self.current_job = CurrentScanJob(
                cidr=cidr,
                scan_uuid=scan_uuid,
                started_at=started_at,
                output_file=output_file,
                log_file=log_file,
                port=self.config.port,
                rate=self.config.rate,
                estimated_duration_s=self.estimated_block_duration_s,
            )

        start_ms = time.time() * 1000
        success = True
        error_msg = None
        hosts_found = 0
        log_path = Path(log_file)

        def append_log_lines(*lines: str) -> None:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a") as handle:
                for line in lines:
                    handle.write(f"{line}\n")

        try:
            # Create scan context directly without database commit
            context = ScanContext(
                scan_id=0,  # Not persisted for ACO blocks
                scan_uuid=scan_uuid,
                request=ScanRequest(
                    target=cidr,
                    port=self.config.port,
                    rate=self.config.rate,
                    router_mac=self.config.router_mac,
                    strategy=strategy_name,
                    tor_max_hosts=self.config.tor_max_hosts,
                    tor_concurrency=self.config.tor_concurrency,
                    tor_sample_mode=(
                        TOR_SAMPLE_MODE_SPREAD if strategy_name == TOR_CONNECT_STRATEGY else None
                    ),
                    tor_sample_seed=(
                        f"{cidr}:{scan_uuid}" if strategy_name == TOR_CONNECT_STRATEGY else None
                    ),
                    tor_seen_hosts=(
                        previously_sampled_hosts if strategy_name == TOR_CONNECT_STRATEGY else None
                    ),
                ),
                paths=ScanPaths(
                    output_file=output_file,
                    log_file=log_file,
                ),
                exclude_file=self.config.exclude_file,
            )

            result = strategy.execute(context)
            hosts_found = result.discovered_hosts

            if strategy_name == TOR_CONNECT_STRATEGY and result.sampled_hosts:
                with self._state_lock:
                    sampled_hosts = self.block_sampled_hosts.setdefault(cidr, set())
                    sampled_hosts.update(result.sampled_hosts)
                    if result.discovered_targets:
                        discovered_hosts = self.block_discovered_hosts.setdefault(cidr, set())
                        discovered_hosts.update(result.discovered_targets)

            append_log_lines(
                f"strategy={strategy_name}",
                f"target={cidr}",
                f"port={self.config.port}",
                f"output_file={output_file}",
                f"sample_mode={context.request.tor_sample_mode or 'n/a'}",
                f"previously_sampled_hosts={len(previously_sampled_hosts)}",
                f"tracked_sampled_hosts={len(self.block_sampled_hosts.get(cidr, set())) if strategy_name == TOR_CONNECT_STRATEGY else 0}",
                f"attempted_hosts={result.attempted_hosts}",
                f"discovered_hosts={hosts_found}",
            )

        except Exception as e:
            success = False
            error_msg = str(e)
            append_log_lines(f"strategy={strategy_name}", f"target={cidr}", f"error={error_msg}")

        duration_ms = (time.time() * 1000) - start_ms
        completed_at = datetime.utcnow()

        with self._state_lock:
            self.current_job = None

        result = BlockScanResult(
            cidr=cidr,
            scan_uuid=scan_uuid,
            started_at=started_at,
            completed_at=completed_at,
            output_file=output_file,
            log_file=log_file,
            hosts_found=hosts_found,
            duration_ms=duration_ms,
            success=success,
            error=error_msg,
        )

        with self._state_lock:
            self.recent_results.appendleft(result)

        return result

    def _run_masscan_block(self, cidr: str) -> BlockScanResult:
        """Run scan against a single CIDR block (uses configured strategy, not raw masscan)."""
        return self._run_scan_block(cidr)

    def _save_state(self) -> None:
        """Persist ACO state to disk."""
        try:
            Path(self.config.state_file).parent.mkdir(parents=True, exist_ok=True)
            with self._state_lock:
                data = {
                    "version": 2,
                    "aco": self.aco.to_dict(),
                    "block_sampled_hosts": {
                        cidr: sorted(hosts)
                        for cidr, hosts in self.block_sampled_hosts.items()
                        if hosts
                    },
                    "block_discovered_hosts": {
                        cidr: sorted(hosts)
                        for cidr, hosts in self.block_discovered_hosts.items()
                        if hosts
                    },
                }
            with open(self.config.state_file, "w") as f:
                json.dump(data, f, indent=2)
            logger.debug("ACO state saved to %s", self.config.state_file)
        except Exception as e:
            logger.error("Failed to save ACO state: %s", e)

    def _load_state(self) -> None:
        """Load persisted ACO state from disk."""
        try:
            with open(self.config.state_file) as f:
                data = json.load(f)

            if "aco" in data:
                aco_data = data.get("aco", {})
                sampled_hosts = data.get("block_sampled_hosts", {})
                discovered_hosts = data.get("block_discovered_hosts", {})
            else:
                aco_data = data
                sampled_hosts = {}
                discovered_hosts = {}

            with self._state_lock:
                self.aco = AntColony.from_dict(aco_data)
                self.block_sampled_hosts = {
                    cidr: set(hosts)
                    for cidr, hosts in sampled_hosts.items()
                    if isinstance(hosts, list)
                }
                self.block_discovered_hosts = {
                    cidr: set(hosts)
                    for cidr, hosts in discovered_hosts.items()
                    if isinstance(hosts, list)
                }
            logger.info(
                "ACO state loaded: %d blocks, %d scanned, %d blocks with sampled-host memory",
                len(self.aco.blocks),
                sum(1 for b in self.aco.blocks.values() if b.scan_count > 0),
                len(self.block_sampled_hosts),
            )
        except FileNotFoundError:
            logger.info("No persisted ACO state found, starting fresh")
        except Exception as e:
            logger.error("Failed to load ACO state: %s", e)
