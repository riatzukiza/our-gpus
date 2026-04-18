# OpenPlanner Integration

This module syncs discovered Ollama GPU hosts to the OpenPlanner data lake, enabling:

1. **Semantic Search**: Search for GPU nodes by capabilities, location, models, etc.
2. **Graph-Based Discovery**: Link GPU nodes to models for federation routing
3. **Proxx Federation**: Register GPU nodes as compute providers for inference routing

## Configuration

Set these environment variables:

```bash
# OpenPlanner API endpoint
OPENPLANNER_URL=http://127.0.0.1:8788/api/openplanner

# API key for authentication (optional)
OPENPLANNER_API_KEY=your-api-key

# Enable/disable sync (default: true)
OPENPLANNER_SYNC_ENABLED=true

# Batch size for API calls (default: 100)
OPENPLANNER_BATCH_SIZE=100

# Request timeout in seconds (default: 30)
OPENPLANNER_TIMEOUT_SECS=30
```

## Usage

### CLI

Sync discovered GPU hosts to OpenPlanner:

```bash
# Sync all online hosts with GPU
uv run python cli/sync_to_openplanner.py --status online --has-gpu

# Sync first 100 discovered hosts (dry run)
uv run python cli/sync_to_openplanner.py --status discovered --limit 100 --dry-run

# Sync all hosts without graph nodes (faster)
uv run python cli/sync_to_openplanner.py --no-graph-nodes

# Output as JSON
uv run python cli/sync_to_openplanner.py --status online --json
```

### API

Trigger sync via REST API:

```bash
# Sync all online GPU hosts
curl -X POST "http://localhost:8000/api/admin/openplanner/sync" \
  -H "X-API-Key: your-admin-key" \
  -H "Content-Type: application/json" \
  -d '{"status": "online", "has_gpu": true}'

# Check integration status
curl "http://localhost:8000/api/admin/openplanner/status" \
  -H "X-API-Key: your-admin-key"
```

### Celery Task

The sync runs as a Celery task for background processing:

```python
from worker.tasks import sync_to_openplanner

# Sync all online GPU hosts
task = sync_to_openplanner.delay(
    status="online",
    has_gpu=True,
    limit=1000,
    include_graph_nodes=True
)

# Check task status
result = task.get(timeout=60)
print(result)
```

## Event Schema

### Primary Event: `gpu_node_discovered`

Emitted for each discovered host:

```json
{
  "schema": "openplanner.event.v1",
  "id": "our-gpus:host:123",
  "ts": "2024-04-15T12:00:00Z",
  "source": "our-gpus",
  "kind": "gpu_node_discovered",
  "text": "Ollama instance at 192.168.1.1:11434 (online) with GPU: NVIDIA RTX 4090. Location: San Francisco, US. models: llama3:70b, mixtral:8x7b.",
  "meta": {
    "gpu_available": true,
    "gpu_name": "NVIDIA RTX 4090",
    "gpu_vram_mb": 24576,
    "gpu_vram_gb": 24.0,
    "status": "online",
    "latency_ms": 42.5,
    "api_version": "0.1.26",
    "geo_country": "US",
    "geo_city": "San Francisco",
    "cloud_provider": "AWS",
    "model_count": 2
  },
  "extra": {
    "ip": "192.168.1.1",
    "port": 11434,
    "host_id": 123,
    "os": "linux",
    "arch": "x86_64",
    "ram_gb": 64.0,
    "models": [
      {"name": "llama3:70b", "family": "llama", "loaded": true, "vram_usage_mb": 40000}
    ]
  }
}
```

### Graph Node Event: `graph.node`

Emitted for graph-based linking:

```json
{
  "schema": "openplanner.event.v1",
  "id": "our-gpus:node:123",
  "ts": "2024-04-15T12:00:00Z",
  "source": "our-gpus",
  "kind": "graph.node",
  "source_ref": {
    "project": "our-gpus",
    "message": "gpu-node:192.168.1.1:11434"
  },
  "text": "192.168.1.1:11434 - NVIDIA RTX 4090 - US",
  "meta": {
    "node_type": "gpu_node",
    "status": "online",
    "gpu_available": true
  },
  "extra": {
    "node_id": "gpu-node:192.168.1.1:11434",
    "preview": "192.168.1.1:11434 (NVIDIA RTX 4090)"
  }
}
```

### Graph Edge Event: `graph.edge`

Links GPU nodes to models:

```json
{
  "schema": "openplanner.event.v1",
  "id": "our-gpus:edge:123:llama3:70b",
  "ts": "2024-04-15T12:00:00Z",
  "source": "our-gpus",
  "kind": "graph.edge",
  "meta": {
    "edge_type": "hosts_model",
    "loaded": true
  },
  "extra": {
    "source_node_id": "gpu-node:192.168.1.1:11434",
    "target_node_id": "model:llama3:70b",
    "edge_kind": "hosts_model",
    "vram_usage_mb": 40000
  }
}
```

## Integration with Proxx

To route inference requests to discovered GPU nodes:

1. **Register as Federation Peer**: Add `our-gpus` as a peer in proxx
2. **Query Graph**: Search OpenPlanner for GPU nodes matching model requirements
3. **Route Requests**: Send inference requests to selected nodes

Example query for GPU nodes with specific model:

```typescript
// In proxx federation logic
const gpuNodes = await openplanner.search({
  kind: "gpu_node_discovered",
  meta: {
    gpu_available: true,
    model_count: { $gt: 0 }
  },
  extra: {
    models: { $elemMatch: { name: "llama3:70b" } }
  }
});

// Select best node based on latency, VRAM, etc.
const bestNode = selectBestNode(gpuNodes);
await proxyRequest(bestNode, request);
```

## Testing

Run tests with:

```bash
uv run pytest tests/test_openplanner_sync.py -v
```
