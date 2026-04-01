# Observation Schema

## Status
Draft — design phase

## Contract

Every observation is an append-only evidence record. Observations are immutable after creation. Updates to host state produce new observations, not mutations.

## Observation Types

```python
@dataclass(frozen=True)
class HostObservation:
    observation_id: str           # UUID
    host_ip: str
    host_port: int
    discovery_strategy: str       # masscan | tor-connect | shodan
    workflow_id: str              # owning workflow
    observed_at: datetime
    exclude_snapshot_hash: str    # SHA256 of exclusion set at observation time
    operator_id: str | None       # who triggered this, None if automation
    evidence: ObservationEvidence
    classification: HostClassification | None  # populated by classify stage


@dataclass(frozen=True)
class ObservationEvidence:
    # What we actually saw
    port_open: bool
    http_responds: bool | None
    http_status: int | None
    response_latency_ms: float | None
    is_ollama: bool | None
    ollama_version: str | None
    model_names: list[str]
    gpu_available: bool | None
    gpu_vram_mb: int | None
    raw_tags: dict | None
    raw_version: dict | None
    source_url: str | None        # Shodan result URL if applicable


@dataclass(frozen=True)
class HostClassification:
    country: str | None
    city: str | None
    asn: int | None
    asn_owner: str | None
    netblock: str | None
    provider: str | None          # cloud, residential, hosting, etc.
    group_ids: list[int]          # host group membership
    risk_label: str | None        # safe, suspicious, ignored, etc.
```

## Observation Pipeline Stages

Each stage can add fields to the observation, but never modifies existing fields.

```
discover    → produces HostObservation with minimal evidence
ingest      → parses discovery output into structured observations
verify      → enriches with http_responds, is_ollama, models, gpu
geocode     → enriches with country, city, asn, provider
graph-emit  → pushes observation into graph weaver / threat radar
classify    → enriches with group_ids, risk_label
```

## Observation Store

Observations are stored in a single append-only table:

```sql
CREATE TABLE observations (
    id              INTEGER PRIMARY KEY,
    observation_id  TEXT NOT NULL UNIQUE,
    host_ip         TEXT NOT NULL,
    host_port       INTEGER NOT NULL,
    discovery_strategy  TEXT NOT NULL,
    workflow_id     TEXT NOT NULL,
    observed_at     DATETIME NOT NULL,
    exclude_snapshot_hash TEXT NOT NULL,
    operator_id     TEXT,
    evidence_json   TEXT NOT NULL,  -- ObservationEvidence as JSON
    classification_json TEXT,       -- HostClassification as JSON, null until classify stage
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_observations_host ON observations(host_ip, host_port);
CREATE INDEX idx_observations_workflow ON observations(workflow_id);
CREATE INDEX idx_observations_strategy ON observations(discovery_strategy);
CREATE INDEX idx_observations_time ON observations(observed_at);
```

## Deduplication

The same host/port can be observed multiple times by different workflows. Each observation is a separate row.

The **current** state of a host is derived by taking the most recent observation for that host/port.

## Provenance Chain

Every observation carries a full provenance chain:

```
observation_id
├── workflow_id
│   ├── triggered_by: operator_id | automation_id
│   ├── triggered_at: timestamp
│   └── strategy: shodan | tor-connect | masscan
├── exclude_snapshot_hash
│   └── refs: merged exclusion file content hash
└── evidence
    └── source: strategy-specific output
```

This chain makes it possible to answer:
- "who triggered this observation?"
- "what strategy produced it?"
- "what exclusions were in effect?"
- "what evidence supports it?"
