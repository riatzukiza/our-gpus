# Workflow Engine

## Status
Draft — design phase

## Contract

The workflow engine is the operator-facing execution model for Sintel.

Operators start, inspect, pause, stop, rerun, and compare **workflows**. The engine owns the full stage chain:

```
discover
  → ingest
    → verify
      → geocode
        → graph-emit
          → classify
            → alert
```

Jobs, Celery tasks, subprocesses, and scans are implementation details under the workflow.

## Core Types

```python
@dataclass(frozen=True)
class WorkflowSpec:
    workflow_id: str
    workflow_kind: str          # one-off | continuous-block | replay | chained
    target: str                 # CIDR, range, or passive query scope
    port: str
    strategy: str               # shodan | tor-connect | masscan
    operator_id: str | None
    created_at: datetime
    requested_config: dict      # strategy + scheduler + policy knobs
    exclude_snapshot_hash: str
    policy_snapshot_hash: str
    parent_workflow_id: str | None
    tags: dict[str, str]


@dataclass(frozen=True)
class WorkflowRun:
    workflow_id: str
    status: str                 # pending | validating | running | blocked | stopping | completed | failed | cancelled
    current_stage: str | None
    started_at: datetime | None
    completed_at: datetime | None
    summary: WorkflowSummary
    last_error: str | None


@dataclass(frozen=True)
class WorkflowStageReceipt:
    receipt_id: str
    workflow_id: str
    stage_name: str             # discover | ingest | verify | geocode | graph-emit | classify | alert
    status: str                 # started | completed | failed | skipped | blocked
    started_at: datetime
    finished_at: datetime | None
    operator_id: str | None
    input_refs: list[str]       # file paths, DB ids, task ids, query ids
    output_refs: list[str]
    metrics: dict               # host_count, duration, error_count, etc.
    evidence_refs: list[str]    # logs, result files, API responses, graph receipts
    policy_decisions: list[str] # policy decision ids used at this stage
    error: str | None


@dataclass(frozen=True)
class WorkflowSummary:
    attempted_hosts: int
    discovered_hosts: int
    verified_hosts: int
    geocoded_hosts: int
    emitted_nodes: int
    emitted_edges: int
    classified_hosts: int
    alerts_created: int
```

## Workflow Rules

Every workflow must:

- have a stable `workflow_id` before any network activity occurs
- snapshot both exclusions and policy before execution starts
- record stage receipts as append-only evidence
- fail closed if validation, exclusions, or policy checks fail
- expose operator-visible status without requiring log inspection
- support one-off execution and continuous scheduler-driven execution through the same model

## Lifecycle

### 1. Validation

Before a workflow can enter `running`, the engine validates:

- target syntax
- strategy availability
- exclusion snapshot exists and is non-empty
- policy snapshot exists
- egress mode permits the selected strategy
- operator confirmation requirements for high-risk strategies

Validation failure moves the workflow to `blocked` or `failed` with a receipt.

### 2. Execution

The engine executes stages in order. Each stage receives the prior stage outputs plus the immutable workflow context.

### 3. Completion

A workflow completes only when all required stages either:

- succeed, or
- are explicitly skipped by policy or workflow type with a recorded receipt

### 4. Replay

Workflows can be replayed against the same or newer policy set, but replay creates a **new** workflow with a `parent_workflow_id` link.

## Stage Contract

### discover

Purpose: produce raw host-level discoveries from a strategy.

Inputs:
- target
- port
- strategy
- exclusion snapshot
- strategy config

Outputs:
- raw discovery file(s)
- minimal host observations
- discover receipt

### ingest

Purpose: normalize raw discovery output into append-only observations.

Inputs:
- discovery file(s)
- workflow context

Outputs:
- structured observation rows
- ingest receipt

### verify

Purpose: probe discovered hosts for service identity and signal quality.

Inputs:
- observations from ingest

Outputs:
- verification evidence
- enriched observations
- verify receipt

### geocode

Purpose: resolve location, ASN, owner, and provider metadata.

Outputs:
- geocoded observation enrichments
- geocode receipt

### graph-emit

Purpose: push workflow outputs into Graph Weaver and related graph consumers.

Outputs:
- node and edge emission receipts
- external reference ids
- graph-emit receipt

### classify

Purpose: attach groups, labels, policy classifications, and risk hints.

Outputs:
- classification updates
- classify receipt

### alert

Purpose: open operator-visible alerts from classified observations and workflow anomalies.

Outputs:
- alert ids
- downstream notification receipts
- alert receipt

## State Machine

```
pending
  → validating
    → running
      → completed
      → failed
      → stopping → cancelled
    → blocked
    → failed
```

Stage-level failures do not disappear into logs. They must be reflected in workflow state and receipt history.

## Continuous Scheduler Model

The ACO block scheduler does not replace the workflow engine. It feeds it.

The scheduler is a workflow producer:

- chooses the next block
- constructs `WorkflowSpec`
- submits it to the engine
- observes completion receipts
- updates pheromones and revisit timing from outcomes

This keeps one-off and continuous runs structurally identical.

## Current Mapping

The current implementation already has partial workflow pieces:

- `Scan` is the nearest existing `WorkflowRun`
- `TaskJob` is the nearest existing stage job record
- ACO dashboard data is the current scheduler snapshot
- result files and logs are existing receipt evidence refs

The engine should evolve these into explicit workflow records rather than introducing a second parallel execution system.

## Storage Model

Minimum new tables:

```sql
CREATE TABLE workflows (
    workflow_id TEXT PRIMARY KEY,
    workflow_kind TEXT NOT NULL,
    target TEXT NOT NULL,
    port TEXT NOT NULL,
    strategy TEXT NOT NULL,
    status TEXT NOT NULL,
    operator_id TEXT,
    exclude_snapshot_hash TEXT NOT NULL,
    policy_snapshot_hash TEXT NOT NULL,
    parent_workflow_id TEXT,
    requested_config_json TEXT NOT NULL,
    summary_json TEXT,
    last_error TEXT,
    created_at DATETIME NOT NULL,
    started_at DATETIME,
    completed_at DATETIME
);

CREATE TABLE workflow_stage_receipts (
    receipt_id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    stage_name TEXT NOT NULL,
    status TEXT NOT NULL,
    input_refs_json TEXT NOT NULL,
    output_refs_json TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    evidence_refs_json TEXT NOT NULL,
    policy_decisions_json TEXT NOT NULL,
    error TEXT,
    started_at DATETIME NOT NULL,
    finished_at DATETIME
);
```

## Observability Requirements

The admin UI must expose, per workflow:

- current stage
- elapsed time per stage
- receipt history
- discovered/verified/geocoded/classified counts
- exact strategy used
- exact exclusion snapshot hash
- exact policy snapshot hash
- evidence links for failures and outputs

This is the missing bridge between the current scanner dashboard and the intended command center.

## Integration Points

- **eta-mu** receives workflow state transitions and completion events
- **Graph Weaver** receives graph-emit stage outputs and emission receipts
- **Threat Radar** receives classify and alert outputs as signal events
- **shuvcrawl** can produce upstream discoveries that enter at `discover` or `ingest`
