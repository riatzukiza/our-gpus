"""
Ant Colony Optimization engine for block scanning and provider selection.

Shared across scanning (Python) and routing (TypeScript port).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import datetime


@dataclass
class ACOConfig:
    """Configuration for an ACO instance."""

    alpha: float = 0.6  # pheromone weight
    beta: float = 0.4  # heuristic weight
    decay: float = 0.05  # evaporation rate per cycle
    reinforcement: float = 0.3  # success bonus multiplier
    penalty: float = 0.2  # failure penalty
    initial_pheromone: float = 0.5


@dataclass
class BlockState:
    """ACO state for a single block (CIDR or provider-route)."""

    key: str
    pheromone: float = 0.5
    scan_count: int = 0
    last_scan_at: datetime | None = None
    last_yield: int = 0
    cumulative_yield: int = 0
    total_duration_ms: float = 0.0


class AntColony:
    """
    Core ACO engine. Manages pheromone trails, heuristic scoring,
    and softmax-based selection.
    """

    def __init__(self, config: ACOConfig | None = None):
        self.config = config or ACOConfig()
        self.blocks: dict[str, BlockState] = {}

    def get_or_create(self, key: str) -> BlockState:
        if key not in self.blocks:
            self.blocks[key] = BlockState(
                key=key,
                pheromone=self.config.initial_pheromone,
            )
        return self.blocks[key]

    def heuristic(self, block: BlockState, now: datetime | None = None) -> float:
        """
        Compute heuristic score for a block.

        Higher = more interesting to scan.
        Based on: recency (older = higher), discovery rate (more finds = higher).
        """
        now = now or datetime.utcnow()

        # Recency: 1/(1 + hours since last scan). Never-scanned blocks get max score.
        if block.last_scan_at is None:
            recency = 1.0
        else:
            hours_since = (now - block.last_scan_at).total_seconds() / 3600
            recency = 1.0 / (1.0 + hours_since)

        # Discovery rate: cumulative_yield / (scan_count + 1)
        discovery = block.cumulative_yield / (block.scan_count + 1)
        # Normalize to 0-1 range (cap at 100 hosts per scan)
        discovery_normalized = min(discovery / 100.0, 1.0)

        return recency * (0.5 + 0.5 * discovery_normalized)

    def score(self, key: str, now: datetime | None = None) -> float:
        """Combined pheromone + heuristic score for a block."""
        block = self.get_or_create(key)
        p = block.pheromone
        h = self.heuristic(block, now)
        return self.config.alpha * p + self.config.beta * h

    def select(self, candidates: list[str], now: datetime | None = None) -> str:
        """
        Select a candidate using softmax over ACO scores.

        Returns the key of the selected candidate.
        """
        if not candidates:
            raise ValueError("No candidates to select from")

        if len(candidates) == 1:
            return candidates[0]

        scores = [self.score(c, now) for c in candidates]
        selected = _softmax_select(candidates, scores)
        return selected

    def select_weighted(
        self,
        candidates: list[str],
        weights: dict[str, float] | None = None,
        now: datetime | None = None,
    ) -> str:
        """Select with optional per-candidate weight overrides."""
        if not candidates:
            raise ValueError("No candidates to select from")

        if len(candidates) == 1:
            return candidates[0]

        scores = []
        for c in candidates:
            s = self.score(c, now)
            if weights and c in weights:
                s *= weights[c]
            scores.append(s)

        return _softmax_select(candidates, scores)

    def reinforce(self, key: str, quality: float) -> None:
        """Strengthen pheromone for a successful candidate."""
        block = self.get_or_create(key)
        block.pheromone = min(1.0, block.pheromone + self.config.reinforcement * quality)

    def penalize(self, key: str) -> None:
        """Weaken pheromone for a failed candidate."""
        block = self.get_or_create(key)
        block.pheromone = max(0.0, block.pheromone - self.config.penalty)

    def evaporate_all(self) -> None:
        """Apply evaporation to all pheromone trails."""
        decay = self.config.decay
        for block in self.blocks.values():
            block.pheromone *= 1.0 - decay

    def record_scan(self, key: str, yield_count: int, duration_ms: float) -> None:
        """Update block state after a scan completes."""
        block = self.get_or_create(key)
        now = datetime.utcnow()
        block.scan_count += 1
        block.last_scan_at = now
        block.last_yield = yield_count
        block.cumulative_yield += yield_count
        block.total_duration_ms += duration_ms

        # Auto-reinforce based on yield
        if yield_count > 0:
            quality = min(yield_count / 50.0, 1.0)
            self.reinforce(key, quality)

    def top_blocks(self, n: int = 10) -> list[tuple[str, float]]:
        """Return top N blocks by pheromone."""
        return sorted(
            [(k, b.pheromone) for k, b in self.blocks.items()],
            key=lambda x: x[1],
            reverse=True,
        )[:n]

    def stats(self) -> dict:
        """Return aggregate stats."""
        total = len(self.blocks)
        scanned = sum(1 for b in self.blocks.values() if b.scan_count > 0)
        total_yield = sum(b.cumulative_yield for b in self.blocks.values())
        avg_pheromone = sum(b.pheromone for b in self.blocks.values()) / total if total > 0 else 0
        return {
            "total_blocks": total,
            "scanned_blocks": scanned,
            "unscanned_blocks": total - scanned,
            "total_yield": total_yield,
            "avg_pheromone": round(avg_pheromone, 4),
        }

    def to_dict(self) -> dict:
        """Serialize to dict for persistence."""
        return {
            "config": {
                "alpha": self.config.alpha,
                "beta": self.config.beta,
                "decay": self.config.decay,
                "reinforcement": self.config.reinforcement,
                "penalty": self.config.penalty,
            },
            "blocks": {
                k: {
                    "pheromone": b.pheromone,
                    "scan_count": b.scan_count,
                    "last_scan_at": b.last_scan_at.isoformat() if b.last_scan_at else None,
                    "last_yield": b.last_yield,
                    "cumulative_yield": b.cumulative_yield,
                    "total_duration_ms": b.total_duration_ms,
                }
                for k, b in self.blocks.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> AntColony:
        """Deserialize from dict."""
        config_data = data.get("config", {})
        config = ACOConfig(**config_data)
        colony = cls(config)
        for key, bd in data.get("blocks", {}).items():
            block = BlockState(
                key=key,
                pheromone=bd.get("pheromone", 0.5),
                scan_count=bd.get("scan_count", 0),
                last_scan_at=(
                    datetime.fromisoformat(bd["last_scan_at"]) if bd.get("last_scan_at") else None
                ),
                last_yield=bd.get("last_yield", 0),
                cumulative_yield=bd.get("cumulative_yield", 0),
                total_duration_ms=bd.get("total_duration_ms", 0.0),
            )
            colony.blocks[key] = block
        return colony


def _softmax_select(candidates: list[str], scores: list[float], temperature: float = 0.15) -> str:
    """
    Softmax selection with temperature.

    Lower temperature = more exploitation (pick the best).
    Higher temperature = more exploration (try everything).
    """
    if not candidates:
        raise ValueError("No candidates")

    # Shift scores for numerical stability
    max_score = max(scores)
    exp_scores = [math.exp((s - max_score) / temperature) for s in scores]
    total = sum(exp_scores)

    if total == 0:
        return random.choice(candidates)

    # Cumulative probability for sampling
    r = random.random() * total
    cumulative = 0.0
    for candidate, exp_s in zip(candidates, exp_scores, strict=False):
        cumulative += exp_s
        if cumulative >= r:
            return candidate

    return candidates[-1]
