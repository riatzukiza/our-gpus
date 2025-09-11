# OurGPU Claude

A production-ready platform for discovering, cataloging, and monitoring Ollama instances at scale. Successfully tracks 3,400+ hosts with their models, GPU capabilities, and availability status.

## Features

- **Large-scale data ingestion**: Stream process multi-GB JSON/JSONL files with dynamic schema detection
- **Intelligent Ollama detection**: Probe `/api/tags`, `/api/version`, `/api/ps` endpoints with async Celery workers
- **Smart GPU detection**: Infers GPU availability from VRAM usage, model sizes, and parameter counts
- **Advanced search & filtering**: By model family, GPU capabilities, location, latency, version, and status
- **Pagination support**: Handle large datasets with configurable page sizes (10/25/50/100 items)
- **Real-time monitoring**: Track host availability, model deployments, and system resources
- **Export capabilities**: CSV/JSON export of filtered results
- **Dark mode UI**: Full dark mode support across all pages
- **RESTful API**: Comprehensive API with pagination metadata

## Quick Start

1. **Clone and setup**:
```bash
cd our-opus-v1
cp .env.example .env
```

2. **Start services**:
```bash
docker compose up -d --build
```

3. **Access the platform**:
- Web UI: http://localhost:5173
- API: http://localhost:8000
- API Docs: http://localhost:8000/docs

4. **Upload data**:
- Navigate to Upload page
- Select your JSON/JSONL file
- Map fields (auto-detection available)
- Start ingestion and monitor progress

5. **Explore hosts**:
- Use filters to find specific Ollama instances
- Click on any host for detailed information
- Trigger re-probes for updated status
- Export results as CSV or JSON

## API Endpoints

- `POST /api/ingest` - Start data ingestion
- `GET /api/scans/:id` - Check ingestion progress  
- `POST /api/probe` - Trigger async host probing via Celery
- `GET /api/hosts` - List hosts with filters and pagination
- `GET /api/hosts/:id` - Get host details with model information
- `GET /api/models` - List available models
- `GET /api/export` - Export filtered data
- `GET /healthz` - Health check
- `GET /metrics` - Prometheus metrics

## CLI Tools

```bash
# Ingest JSON file
python cli/ingest_json.py data/sample.json --auto-detect

# Re-probe hosts
python cli/rescan_hosts.py --status offline --limit 100

# Probe GPU-enabled hosts
python cli/rescan_hosts.py --gpu --concurrency 50
```

## Architecture

- **Backend**: FastAPI + SQLModel + SQLAlchemy
- **Worker**: Celery + Redis
- **Frontend**: React + TypeScript + Vite + Tailwind
- **Database**: SQLite (easily upgradeable to PostgreSQL)
- **Containerization**: Docker Compose with health checks

## Development

```bash
# Install dependencies
pip install -r requirements.txt
cd web && npm install

# Run tests
pytest tests/

# Start development servers
make dev
```

## Configuration

Key environment variables in `.env`:

- `PROBE_TIMEOUT_SECS`: Timeout for each probe (default: 5)
- `PROBE_CONCURRENCY`: Max concurrent probes (default: 200)
- `UPLOAD_MAX_MB`: Max upload size (default: 4096)
- `BATCH_SIZE`: Processing batch size (default: 1000)

## Performance

- Handles multi-GB files with streaming parsing
- Sub-second search on 3,400+ hosts with pagination
- Concurrent probing up to 200 hosts simultaneously via Celery workers
- Memory-bounded processing (< 500MB for 100k records)
- Real-time probe results with proper database connection handling

## Security

- CORS configuration for API access
- Input validation and size limits
- Rate limiting on probe operations
- No logging of sensitive data by default

## Current System Status

### Working Features
- ✅ Async host probing with real Celery workers
- ✅ Model extraction from Ollama `/api/tags` endpoint
- ✅ Smart GPU detection based on VRAM usage and model characteristics
- ✅ Pagination with metadata (total hosts, pages)
- ✅ Page size selection (10, 25, 50, 100 items)
- ✅ Dark mode support across all UI components
- ✅ Host detail view with full model information
- ✅ Version and latency tracking

### Known Limitations
- Ollama API doesn't directly expose GPU hardware info
- GPU detection is inferential based on model characteristics
- Model data may be truncated if payload is very large
- No built-in authentication (add for production)
- SQLite database (upgrade to PostgreSQL for production scale)

### System Scale
- Currently tracking **3,457+ hosts** in production
- Supports concurrent probing of 200+ hosts
- Handles multi-GB JSON ingestion files

## License

MIT