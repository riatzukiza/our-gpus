# Architecture Documentation

## System Overview

The Ollama Discovery Platform follows a microservices architecture with clear separation of concerns:

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Web UI    │────▶│   FastAPI   │────▶│   SQLite    │
│   (React)   │     │    (API)    │     │  Database   │
└─────────────┘     └─────────────┘     └─────────────┘
                           │
                           ▼
                    ┌─────────────┐
                    │    Redis    │
                    │   (Queue)   │
                    └─────────────┘
                           │
                           ▼
                    ┌─────────────┐
                    │   Celery    │
                    │   Workers   │
                    └─────────────┘
```

## Components

### 1. Web Frontend (React + TypeScript)

**Location**: `/web`

- **Framework**: React 18 with TypeScript
- **Build Tool**: Vite for fast development and optimized builds
- **Styling**: Tailwind CSS with comprehensive dark mode support
- **State Management**: React Context for dark mode, local state for data
- **Routing**: React Router v6

**Key Features**:
- File upload with drag-and-drop
- Dynamic field mapping UI
- Real-time progress tracking
- Advanced search with model family and GPU filtering
- Paginated data tables with size selector (10/25/50/100)
- Host detail view with model listings
- Dark mode toggle with persistent preferences

### 2. API Backend (FastAPI)

**Location**: `/app`

- **Framework**: FastAPI for high-performance async API
- **ORM**: SQLModel (SQLAlchemy + Pydantic)
- **Validation**: Pydantic models for request/response
- **Metrics**: Prometheus integration

**Core Modules**:
- `main.py`: API endpoints with pagination support
- `db.py`: Database models and session management
- `schemas.py`: Pydantic schemas for validation
- `ingest.py`: Data ingestion service
- `probe.py`: Enhanced Ollama probing with GPU detection logic

### 3. Async Workers (Celery)

**Location**: `/worker`

- **Task Queue**: Celery with Redis broker
- **Concurrency**: Process pool for CPU-bound tasks
- **Database**: Proper connection handling with get_db() context manager
- **Task Types**:
  - Data ingestion (streaming JSON processing)
  - Host probing (async HTTP requests with proper error handling)
  - Batch operations
  - Real-time model extraction from Ollama endpoints

### 4. Database (SQLite/PostgreSQL)

**Schema**:

```sql
-- Hosts table
CREATE TABLE hosts (
    id INTEGER PRIMARY KEY,
    ip VARCHAR NOT NULL,
    port INTEGER NOT NULL,
    status VARCHAR,
    last_seen TIMESTAMP,
    latency_ms FLOAT,
    api_version VARCHAR,
    gpu_vram_mb INTEGER,
    -- Additional fields...
    INDEX idx_ip_port (ip, port)
);

-- Models table
CREATE TABLE models (
    id INTEGER PRIMARY KEY,
    name VARCHAR UNIQUE,
    family VARCHAR,
    parameters VARCHAR,
    INDEX idx_family (family)
);

-- Host-Model associations
CREATE TABLE host_models (
    id INTEGER PRIMARY KEY,
    host_id INTEGER REFERENCES hosts(id),
    model_id INTEGER REFERENCES models(id),
    loaded BOOLEAN,
    vram_usage_mb INTEGER
);

-- Scans table for ingestion tracking
CREATE TABLE scans (
    id INTEGER PRIMARY KEY,
    source_file VARCHAR,
    status VARCHAR,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    mapping_json TEXT,
    stats_json TEXT
);

-- Probes table for audit trail
CREATE TABLE probes (
    id INTEGER PRIMARY KEY,
    host_id INTEGER REFERENCES hosts(id),
    status VARCHAR,
    duration_ms FLOAT,
    raw_payload TEXT,
    created_at TIMESTAMP
);
```

## Data Flow

### Ingestion Pipeline

1. **Upload**: User uploads JSON/JSONL via web UI
2. **Schema Detection**: Sample first N records to infer fields
3. **Field Mapping**: User maps source fields to target schema
4. **Queue Task**: Create Celery task for async processing
5. **Stream Processing**: Parse file in chunks, batch insert to DB
6. **Progress Updates**: Real-time updates via polling

### Probe Pipeline

1. **Trigger**: Manual probe via API or UI button
2. **Task Creation**: Celery task created with host information
3. **Concurrent Probing**: Async HTTP requests to Ollama endpoints
4. **Data Collection**: 
   - Fetch models from `/api/tags`
   - Get version from `/api/version`
   - Check running models from `/api/ps`
5. **GPU Detection**: Smart inference based on:
   - VRAM usage from running models
   - Model size thresholds (>10GB suggests GPU)
   - Parameter counts (13B+ typically needs GPU)
6. **Status Update**: Update host status, latency, and GPU availability
7. **Model Sync**: Store full model list with proper JSON handling

## Performance Optimizations

### Memory Management
- **Streaming Parsers**: Use ijson for memory-efficient JSON parsing
- **Batch Processing**: Process records in configurable batches
- **Connection Pooling**: Reuse HTTP connections for probing

### Concurrency
- **Async I/O**: FastAPI with async endpoints
- **Worker Pool**: Multiple Celery workers
- **Semaphore Control**: Limit concurrent probes
- **Database Connections**: Connection pooling

### Caching
- **Redis Cache**: Cache frequent queries
- **Frontend Cache**: React Query caching
- **Static Assets**: CDN-ready static file serving

## Scalability

### Horizontal Scaling
- **API Servers**: Load balance multiple FastAPI instances
- **Workers**: Scale Celery workers independently
- **Database**: Migrate to PostgreSQL for production

### Vertical Scaling
- **Worker Concurrency**: Adjust based on CPU cores
- **Connection Limits**: Tune based on available memory
- **Batch Sizes**: Optimize for workload

## Security Considerations

### Input Validation
- Pydantic models for type validation
- File size limits
- Rate limiting on expensive operations

### Network Security
- CORS configuration
- HTTPS support (configure reverse proxy)
- Firewall rules for internal services

### Data Privacy
- No logging of sensitive data
- Configurable data retention
- Export audit trails

## Monitoring & Observability

### Metrics
- Prometheus endpoints for metrics
- Request duration histograms
- Task queue depth monitoring

### Logging
- Structured JSON logging
- Request ID tracking
- Error aggregation

### Health Checks
- Liveness probes for containers
- Readiness checks including DB connectivity
- Service dependency monitoring

## Deployment

### Development
```bash
docker compose up -d
```

### Production
- Use environment-specific configs
- Enable HTTPS via reverse proxy
- Configure monitoring stack
- Set up backup strategy
- Implement log aggregation

## Recent Improvements

1. **Probe System**
   - Fixed 422 validation errors with proper request payloads
   - Implemented database connection handling in Celery workers
   - Added smart GPU detection logic based on model characteristics
   - Full model extraction from Ollama API responses

2. **UI Enhancements**
   - Added pagination with metadata display
   - Implemented page size selector
   - Complete dark mode support
   - Added version and latency columns to host table
   - Fixed "GPU Available" display for detected GPU hosts

3. **Data Handling**
   - Fixed JSON truncation issues for large model lists
   - Proper handling of probe_payload storage
   - Improved error handling and status updates

## Future Enhancements

1. **Authentication & Authorization**
   - JWT-based auth
   - Role-based access control
   - API key management

2. **Advanced Features**
   - Scheduled probing with cron-like syntax
   - Alerting on status changes
   - Historical trend analysis
   - Model performance benchmarking
   - Bulk operations UI

3. **Integrations**
   - Webhook notifications
   - Slack/Discord alerts
   - Grafana dashboards
   - External API integrations
   - Direct GPU hardware detection (if Ollama adds support)