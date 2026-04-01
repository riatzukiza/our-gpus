# Command Center UI

## Status
Draft — design phase

## Contract

The Sintel command center is a workflow-first operator surface. It is not a generic CRUD admin page and not a toy dashboard.

The UI exists to help an operator:

- understand what is happening now
- decide what to do next
- inspect why the system did or did not act
- see evidence before taking risk-bearing actions

## Layout Model

The canonical desktop layout is a six-surface control room.

### Surface 1: Workflow Rail

Purpose: show the active workflow, recent workflows, queued workflows, and blocked workflows.

Must display:

- workflow id
- strategy
- target and port
- current stage
- stage progress
- status
- last error or policy block reason

### Surface 2: World Map

Purpose: geographic theater view of discovered and classified infrastructure.

Must display:

- host points
- country aggregates
- workflow-scoped highlights
- group overlays
- alert overlays

Future target: Mercator-style projection with high-density clustering and workflow replay mode.

### Surface 3: Graph View

Purpose: neighborhood exploration for hosts, blocks, ASNs, orgs, groups, workflows, and alerts.

Must support:

- expanding related entities
- switching between host/block/ASN/group focus
- seeing which workflow produced an edge
- highlighting recent graph emissions

### Surface 4: Evidence Ledger

Purpose: prove what the system saw and what it did.

Must display:

- stage receipts
- logs
- query plans
- exclusion snapshot hash
- policy snapshot hash
- evidence files and external refs

Operators should never need to guess whether a result is real or merely summarized.

### Surface 5: Control Console

Purpose: shared workflow configuration and action entrypoint.

This is the existing `ScannerWorkbench` concept expanded into the canonical control surface.

Must include one shared config panel for:

- strategy selection
- target and port
- strategy-specific knobs
- continuous scheduler knobs
- validation status
- action buttons

Rules:

- every action reads from this same config
- Tor is the default selected strategy
- dangerous actions expose clear risk language
- no duplicate config panels elsewhere in the UI

### Surface 6: Alert / Group / Policy Tray

Purpose: give operators the context needed to act.

Must display:

- host groups
- policy matches
- alert queue
- monitored regions/providers
- quick workflow filters by group, country, system, status

## Core Screens

### Command Center

The default `/admin` experience. Shows all six surfaces in one integrated layout.

### Explore

Host-centric browse and slice view. Supports country, group, system, model, GPU, and status filters.

### Workflow Detail

Single workflow page or drawer with:

- stage timeline
- receipts
- logs
- outputs
- related graph nodes
- policy decisions

### Alert Detail

Shows why an alert exists, what evidence backs it, and what workflow produced it.

## Interaction Rules

### Workflow-first actions

Buttons should describe workflows, not implementation details.

Prefer:

- `Run One-off Workflow`
- `Start Continuous Workflow`
- `Stop Active Workflow`
- `Replay Workflow`

Avoid exposing backend jargon like raw task names as the primary action language.

### Evidence before escalation

Before an operator confirms a risky action or escalates an alert, the UI must surface:

- why this action is allowed
- which policy applies
- what evidence supports it

### Clear risk signaling

Strategies must be visually distinct:

- `shodan` as passive / lowest risk
- `tor-connect` as bounded / medium risk
- `masscan` as unrestricted / highest risk

The current API may still return `tor`; the UI should treat it as a compatibility alias for `tor-connect` until the backend naming is normalized.

### No hidden state

Anything that affects workflow behavior should be inspectable:

- exclusions snapshot
- policy snapshot
- strategy availability
- Tor health
- Shodan API availability
- scheduler health

## Responsiveness

### Desktop

All six surfaces are visible without route switching.

### Tablet

The map, workflow rail, and control console stay on the main canvas. Graph and evidence can collapse into tabs or drawers.

### Mobile

The primary mobile stack is:

1. active workflow
2. control console
3. map
4. alerts/groups/policies
5. evidence

Mobile is for inspection and bounded control, not dense graph editing.

## Current Mapping

The current admin UI already contains early versions of several surfaces:

- `ScannerWorkbench` → Control Console
- `ScannerWorldMap` → World Map
- `WorkflowHistoryPanel` + `CurrentWorkflowCard` → Workflow Rail fragments
- `LiveLogsCard` + jobs panels → Evidence Ledger fragments
- `HostGroupsPanel` → Alert / Group / Policy Tray fragment

What is still missing is the unification into a real command-center layout with explicit policy, receipts, graph, and alert surfaces.

## Design Language

The UI should feel like an operations room:

- high information density without clutter
- clear status hierarchy
- strong contrast between safe, warning, blocked, and active states
- map and graph views treated as first-class, not decorative widgets
- evidence and provenance visible by default

## Data Requirements

The UI contract depends on backend support for:

- workflow and receipt APIs
- policy decision APIs
- graph neighborhood APIs
- alert APIs
- richer geography aggregation

The current dashboard endpoints are a base layer, not the final contract.
