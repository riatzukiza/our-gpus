"""
ACO-guided masscan block scanner.

Decomposes the IPv4 space into blocks, uses ant colony optimization
to prioritize which blocks to scan, and runs masscan per-block
with a max duration of 5 minutes each.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
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
    get_default_blocks,
    optimal_prefix_for_target_duration,
)

logger = logging.getLogger(__name__)


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
    exclude_file: str = "/app/excludes.conf"
    router_mac: str = "00:21:59:a0:cf:c1"
    interface: str = os.environ.get("MASSCAN_INTERFACE", "eth0")
    state_file: str = "/workspace/imports/masscan/aco-state.json"
    breathing_room_s: float = 2.0  # pause between blocks

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

        aco_config = ACOConfig(
            alpha=self.config.aco_alpha,
            beta=self.config.aco_beta,
            decay=self.config.aco_decay,
            reinforcement=self.config.aco_reinforcement,
            penalty=self.config.aco_penalty,
        )
        self.aco = AntColony(aco_config)

        # Determine optimal prefix for target duration
        self.prefix_len = optimal_prefix_for_target_duration(
            target_seconds=self.config.max_block_duration_s,
            rate=self.config.rate,
        )
        self.estimated_block_duration_s = estimate_scan_duration(
            1 << (32 - self.prefix_len),
            self.config.rate,
        )
        logger.info(
            "ACO scheduler: prefix_len=%d (~%ds per block at %d rate)",
            self.prefix_len,
            round(self.estimated_block_duration_s),
            self.config.rate,
        )

        # Blocks loaded lazily in _scan_loop
        self._blocks_loaded = False
        self.blocks: list[str] = []

        # Load persisted state (fast, just reads JSON)
        self._load_state()

    def _ensure_blocks_loaded(self) -> None:
        """Load blocks lazily on first scan."""
        if self._blocks_loaded:
            return
        logger.info("Loading blocks (prefix /%d)...", self.prefix_len)
        self.blocks = get_default_blocks(self.prefix_len, self.config.exclude_file)
        self._blocks_loaded = True
        logger.info("Loaded %d blocks (prefix /%d)", len(self.blocks), self.prefix_len)

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

        with self._state_lock:
            selected = self.aco.select(candidates, now)
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

    def _run_masscan_block(self, cidr: str) -> BlockScanResult:
        """Run masscan against a single CIDR block."""
        Path(self.config.results_dir).mkdir(parents=True, exist_ok=True)
        scan_uuid = str(uuid.uuid4())[:8]
        output_file = f"{self.config.results_dir}/block-{scan_uuid}.json"
        log_file = f"{self.config.results_dir}/block-{scan_uuid}.log"
        started_at = datetime.utcnow()

        cmd = [
            "masscan",
            cidr,
            "-p",
            self.config.port,
            "--interface",
            self.config.interface,
            "--rate",
            str(self.config.rate),
            "--exclude-file",
            self.config.exclude_file,
            "--router-mac",
            self.config.router_mac,
            "-oJ",
            output_file,
            "--wait",
            "10",
            "--retries",
            "2",
        ]

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

        try:
            with open(log_file, "w") as log:
                process = subprocess.Popen(
                    cmd,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
                try:
                    process.wait(timeout=self.config.max_block_duration_s + 30)
                except subprocess.TimeoutExpired:
                    process.kill()
                    success = False
                    error_msg = f"timeout after {self.config.max_block_duration_s}s"
        except Exception as e:
            success = False
            error_msg = str(e)

        duration_ms = (time.time() * 1000) - start_ms
        completed_at = datetime.utcnow()

        # Count hosts found
        hosts_found = 0
        try:
            with open(output_file) as f:
                for line in f:
                    if '"ip":' in line:
                        hosts_found += 1
        except FileNotFoundError:
            pass

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
            self.current_job = None
            self.recent_results.appendleft(result)

        return result

    def _save_state(self) -> None:
        """Persist ACO state to disk."""
        try:
            Path(self.config.state_file).parent.mkdir(parents=True, exist_ok=True)
            with self._state_lock:
                data = self.aco.to_dict()
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
            with self._state_lock:
                self.aco = AntColony.from_dict(data)
            logger.info(
                "ACO state loaded: %d blocks, %d scanned",
                len(self.aco.blocks),
                sum(1 for b in self.aco.blocks.values() if b.scan_count > 0),
            )
        except FileNotFoundError:
            logger.info("No persisted ACO state found, starting fresh")
        except Exception as e:
            logger.error("Failed to load ACO state: %s", e)
