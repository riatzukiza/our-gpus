# API Documentation

## Base URL

```
http://localhost:8000
```

## Authentication

Currently no authentication required (add in production).

## Endpoints

### Ingestion

#### POST /api/ingest

Start ingestion of JSON/JSONL data.

**Request Body** (multipart/form-data):
```json
{
  "file": "<file>",
  "field_map": {
    "ip": "source_ip_field",
    "port": "source_port_field",
    "geo_country": "country_field"
  },
  "source": "upload"
}
```

**Response**:
```json
{
  "scan_id": 1,
  "status": "queued",
  "task_id": "abc-123-def"
}
```

#### GET /api/scans/{scan_id}

Get scan progress and details.

**Response**:
```json
{
  "id": 1,
  "source_file": "data.json",
  "status": "processing",
  "started_at": "2024-01-01T00:00:00",
  "completed_at": null,
  "total_rows": 10000,
  "processed_rows": 5000,
  "mapping": {
    "ip": "host",
    "port": "port"
  },
  "stats": {
    "success": 4900,
    "failed": 100
  }
}
```

### Probing

#### POST /api/probe

Trigger async probing of hosts via Celery workers.

**Request Body**:
```json
{
  "host_id": 1,           // Required: specific host ID to probe
  "ip": "10.0.0.1",      // Required: host IP address
  "port": 11434          // Required: host port
}
```

**Response**:
```json
{
  "message": "Probe task queued",
  "task_id": "abc-123-def"
}
```

Note: The probe runs asynchronously. Results are stored in the database and reflected in subsequent GET requests.

### Hosts

#### GET /api/hosts

List hosts with filtering and pagination.

**Query Parameters**:
- `page` (int): Page number (default: 1)
- `page_size` (int): Page size (default: 50, max: 100)
- `model` (string): Filter by model name (partial match)
- `family` (string): Filter by model family
- `gpu` (boolean): Filter by GPU capability
- `status` (string): Filter by status (online/offline/error)
- `sort` (string): Sort by field (last_seen/latency)

**Response**:
```json
{
  "hosts": [
    {
      "id": 1,
      "ip": "10.0.0.1",
      "port": 11434,
      "status": "online",
      "last_seen": "2024-01-01T00:00:00",
      "latency_ms": 45.2,
      "api_version": "0.1.23",
      "gpu": "GPU Available",
      "gpu_vram_mb": 24576,
      "models": ["llama2:7b", "mistral:7b"]
    }
  ],
  "pagination": {
    "page": 1,
    "page_size": 50,
    "total_count": 3457,
    "total_pages": 70
  }
}
```

#### GET /api/hosts/{host_id}

Get detailed information about a specific host.

**Response**:
```json
{
  "id": 1,
  "ip": "10.0.0.1",
  "port": 11434,
  "status": "online",
  "last_seen": "2024-01-01T00:00:00",
  "first_seen": "2024-01-01T00:00:00",
  "latency_ms": 45.2,
  "api_version": "0.1.23",
  "os": "linux",
  "arch": "x86_64",
  "ram_gb": 32.0,
  "gpu": "NVIDIA RTX 3090",
  "gpu_vram_mb": 24576,
  "geo_country": "US",
  "geo_city": "San Francisco",
  "models": [
    {
      "name": "llama2:7b",
      "family": "llama",
      "parameters": "7B",
      "size": 3825819008,
      "digest": "78e26419b446...",
      "modified_at": "2024-01-01T00:00:00"
    }
  ],
  "probe_payload": {
    "tags": {...},      // Full response from /api/tags
    "ps": {...},        // Full response from /api/ps
    "version": {...}    // Full response from /api/version
  }
}
```

### Models

#### GET /api/models

List all discovered models with host counts.

**Response**:
```json
[
  {
    "id": 1,
    "name": "llama2:7b",
    "family": "llama",
    "parameters": "7B",
    "host_count": 42
  }
]
```

### Export

#### GET /api/export

Export filtered data as CSV or JSON.

**Query Parameters**:
- `format` (string): Export format (csv/json)
- `model` (string): Filter by model
- `family` (string): Filter by family
- `gpu` (boolean): Filter by GPU capability

**Response**: File download (CSV or JSON)

### Health

#### GET /healthz

Basic health check.

**Response**:
```json
{
  "status": "healthy",
  "timestamp": "2024-01-01T00:00:00"
}
```

#### GET /readyz

Readiness check (includes database connectivity).

**Response**:
```json
{
  "status": "ready",
  "timestamp": "2024-01-01T00:00:00"
}
```

#### GET /metrics

Prometheus-format metrics.

**Response**: Text format metrics
```
# HELP ingest_total Total ingests started
# TYPE ingest_total counter
ingest_total 42.0
```

## Error Responses

All endpoints return standard error responses:

```json
{
  "detail": "Error message here"
}
```

Common status codes:
- `400` - Bad Request (invalid parameters)
- `404` - Resource not found
- `422` - Validation error
- `500` - Internal server error
- `503` - Service unavailable