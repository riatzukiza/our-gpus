# Claude Instructions for Ollama Discovery Platform

This file contains instructions and context for Claude to work effectively with this project.

## Project Overview
This is a comprehensive web-based platform for discovering and cataloging Ollama hosts from large-scale network scan data (e.g., Shodan exports). The system intelligently extracts host information, probes discovered Ollama instances for detailed capabilities, and provides a searchable database interface for analysis.

## Architecture
- **Microservices**: Node.js/TypeScript API Gateway, JSON Processor, Background Worker
- **Scanner Service**: Python FastAPI service based on existing scan_test_enhanced.py
- **Frontend**: Next.js/React application
- **Database**: SQLite with migration path to PostgreSQL
- **Infrastructure**: Docker Compose for development and production

## Key Commands

### Development
```bash
npm run dev           # Start all development services
npm run dev:tools     # Start with database admin tools
npm run setup         # Initialize project and install dependencies
```

### Testing & Quality
```bash
npm run test          # Run all test suites
npm run lint          # Lint all services
npm run typecheck     # TypeScript type checking
```

### Production
```bash
npm run prod          # Start production services
npm run clean         # Clean Docker resources
```

## Database Management
- **Schema**: Located in `database/schema.sql`
- **Migrations**: Handled by each service's database setup
- **Admin Interface**: Available at http://localhost:8080 with `npm run dev:tools`

## Service URLs (Development)
- Frontend: http://localhost:3000
- API Gateway: http://localhost:4000
- JSON Processor: http://localhost:4001
- Ollama Scanner: http://localhost:4002
- Redis: http://localhost:6379
- DB Admin: http://localhost:8080

## File Structure
```
ollama-scrape/
├── services/
│   ├── api-gateway/       # Main API server
│   ├── frontend/          # React/Next.js UI
│   ├── json-processor/    # JSON parsing service
│   ├── ollama-scanner/    # Python scanner service
│   └── background-worker/ # Job processing
├── database/schema.sql    # Database schema
├── docker-compose.yml     # Development setup
└── README-PLATFORM.md    # Comprehensive documentation
```

## Common Tasks

### Adding New API Endpoints
1. Add route handler in `services/api-gateway/src/routes/`
2. Update validation and error handling
3. Add corresponding database queries
4. Update TypeScript types if needed

### Modifying Database Schema
1. Update `database/schema.sql`
2. Update service database initialization
3. Consider migration scripts for existing data

### Debugging Services
- Check logs with `docker-compose logs <service-name>`
- Access service shells with `docker-compose exec <service-name> sh`
- Use health check endpoints for service status

## Testing Strategy
- **Unit Tests**: Individual components and functions
- **Integration Tests**: Service-to-service communication
- **E2E Tests**: Complete user workflows
- **Performance Tests**: Large dataset handling

## Performance Considerations
- Scanner can handle 200-1000+ hosts/second
- Database optimized for sub-second search on 10,000+ hosts
- File uploads support multi-GB JSON files with streaming processing
- Rate limiting prevents network abuse

## Security Notes
- Rate limiting on all API endpoints
- File upload size limits and type validation
- SQL injection prevention with parameterized queries
- CORS properly configured for frontend
- No sensitive data in logs

## Existing Assets
- High-performance Python scanner in `scan_test_enhanced.py`
- Sample host data in `hosts_and_ports.txt`
- Extraction script in `extract_hosts.py`
- Comprehensive README with usage examples

## When Working on This Project
1. Always run `npm run setup` when first setting up
2. Use `npm run lint` and `npm run typecheck` before committing
3. Test with sample data from `hosts_and_ports.txt`
4. Check service health endpoints when debugging
5. Refer to `README-PLATFORM.md` for detailed feature documentation