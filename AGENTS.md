# AGENTS.md

## Build, Lint, and Test Commands

### Backend (Python)
- Build: `make build` or `docker compose build`
- Install deps: `uv sync --dev`
- Lint: `make lint` or `uv run ruff check app/ worker/ cli/ tests/`
- Format: `make fmt` or `uv run ruff format app/ worker/ cli/ tests/`
- Test: `make test` or `uv run pytest tests/ -v`

### Frontend (React)
- Lint: `cd web && bun run lint`
- Format: `cd web && bun run format`

Note: Requires Bun to be installed (https://bun.sh/)

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
