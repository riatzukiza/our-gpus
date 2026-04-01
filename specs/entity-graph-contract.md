# Entity Graph Contract

## Status
Draft — design phase

## Contract

Sintel produces graph-compatible entities and relationships that Graph Weaver, Threat Radar, and eta-mu can consume. Sintel is a source, not an owner, of the graph.

## Entity Types

```python
@dataclass(frozen=True)
class GraphNode:
    node_type: str        # host | block | asn | org | country | group | workflow | strategy | alert
    node_id: str          # stable identifier
    display_name: str
    properties: dict
    observed_at: datetime
    source_system: str    # "sintel"


@dataclass(frozen=True)
class GraphEdge:
    edge_type: str        # in_block | belongs_asn | in_country | in_org | in_group | discovered_by | workflow_member | geospatial_near
    source_node: str
    target_node: str
    properties: dict
    observed_at: datetime
    source_system: str    # "sintel"
```

## Node Types

### Host

```python
GraphNode(
    node_type="host",
    node_id=f"host:{ip}:{port}",
    display_name=f"{ip}:{port}",
    properties={
        "ip": ip,
        "port": port,
        "status": "online | timeout | error | non_ollama | discovered",
        "models": ["llama3:70b", ...],
        "gpu_available": True,
        "last_observed": "2026-03-30T...",
        "discovery_strategies": ["masscan", "tor-connect"],
    },
)
```

### Block

```python
GraphNode(
    node_type="block",
    node_id=f"block:{cidr}",
    display_name=cidr,
    properties={
        "cidr": cidr,
        "avg_lat": float,
        "avg_lon": float,
        "country": str | None,
        "host_count": int,
        "yield_count": int,
        "last_scanned": datetime | None,
    },
)
```

### ASN

```python
GraphNode(
    node_type="asn",
    node_id=f"asn:{number}",
    display_name=f"AS{number} {owner}",
    properties={
        "number": int,
        "owner": str,
        "host_count": int,
        "country": str | None,
    },
)
```

### Country

```python
GraphNode(
    node_type="country",
    node_id=f"country:{code}",
    display_name=f"{name} ({code})",
    properties={
        "code": str,
        "name": str,
        "host_count": int,
        "lat": float | None,
        "lon": float | None,
    },
)
```

### Group

```python
GraphNode(
    node_type="group",
    node_id=f"group:{group_id}",
    display_name=name,
    properties={
        "name": str,
        "description": str | None,
        "country_filter": str | None,
        "system_filter": str | None,
        "host_count": int,
        "created_at": datetime,
    },
)
```

### Workflow

```python
GraphNode(
    node_type="workflow",
    node_id=f"workflow:{workflow_id}",
    display_name=f"{strategy}:{target}:{port}",
    properties={
        "strategy": str,
        "target": str,
        "port": str,
        "status": str,
        "started_at": datetime,
        "completed_at": datetime | None,
        "host_count": int,
        "exclude_snapshot_hash": str,
        "operator_id": str | None,
    },
)
```

### Strategy

```python
GraphNode(
    node_type="strategy",
    node_id=f"strategy:{name}",
    display_name=name,
    properties={
        "name": str,
        "risk_tier": "passive | bounded | unrestricted",
    },
)
```

## Edge Types

| Edge type          | Source    | Target    | Meaning                      |
|--------------------|-----------|-----------|------------------------------|
| `in_block`         | host      | block     | host IP falls within block   |
| `belongs_asn`      | host      | asn       | host IP resolved to ASN      |
| `in_country`       | host      | country   | host geocoded to country     |
| `in_org`           | asn       | org       | ASN owned by organization    |
| `in_group`         | host      | group     | host is member of group      |
| `discovered_by`    | host      | strategy  | observation from strategy    |
| `workflow_member`  | host      | workflow  | host discovered in workflow  |
| `geospatial_near`  | block     | block     | geospatially adjacent blocks |
| `same_owner`       | asn       | asn       | same owner/operator          |
| `workflow_chain`   | workflow  | workflow  | one workflow's output fed another |

## Graph Emission

Every completed workflow emits observations into the graph:

```python
def emit_workflow_to_graph(workflow: Workflow, observations: list[HostObservation]):
    # 1. create workflow node
    # 2. create strategy node if not exists
    # 3. for each observation:
    #    a. create/update host node
    #    b. create block node if not exists
    #    c. create edges: in_block, in_country, discovered_by, workflow_member
    #    d. resolve ASN → create asn node + belongs_asn edge
    #    e. resolve groups → create in_group edges
    # 4. create geospatial_near edges between adjacent blocks
```

## Integration Points

Sintel emits to:

- **Graph Weaver**: full node/edge set
- **Threat Radar**: host observations as `SignalEvent` objects
- **eta-mu**: workflow completion events as orchestrator signals

Sintel receives from:

- **Graph Weaver**: graph neighborhood queries for UI
- **Threat Radar**: risk labels and alert classifications
- **shuvcrawl**: additional surface observations (future)
- **eta-mu**: workflow triggers and dependency chains (future)
