# AGENTS.md

## Build, Lint, and Test Commands

### Backend (Python)
- Build: `make build` or `docker compose build`
- Lint: `make lint` or `ruff check app/ worker/ cli/ tests/`
- Format: `make fmt` or `ruff format app/ worker/ cli/ tests/`
- Test: `make test` or `pytest tests/ -v`

### Frontend (React)
- Lint: `cd web && npm run lint`
- Format: `cd web && npm run format`

## Code Style Guidelines

### Python
- Use Ruff for linting and formatting (configured in ruff.toml)
- Follow PEP8 style guide
- Use type hints consistently
- Imports sorted with isort
- Line length: 100 characters
- Double quotes for strings

### TypeScript/React
- Follow Airbnb style guide for React/TS
- Use TypeScript types for all components and props
- Component names use PascalCase
- Follow Tailwind CSS best practices for styling

### Error Handling
- Use try/catch blocks for async operations
- Handle HTTP errors with proper status code checking
- Log errors appropriately without exposing sensitive data

### Naming Conventions
- Python: snake_case for variables and functions, PascalCase for classes
- TypeScript: camelCase for variables and functions, PascalCase for components