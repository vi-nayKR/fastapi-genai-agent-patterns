# Phase 1: Production Service Foundation

## Goal

Phase 1 turns the original single-file demonstration into a testable Python
service. It establishes the boundaries that later phases use for graph state,
Redis connections, telemetry providers, and API lifecycle management.

## Work completed

### Installable source package

Application code now lives in the `agent_patterns` package under `src`. The
top-level `src/main.py` remains a deliberately small ASGI entry point, so
Uvicorn can import the application while implementation modules remain reusable
from tests and scripts.

`pyproject.toml` is the dependency and tool configuration source of truth. The
legacy `requirements.txt` installs that project for platforms that only support
a requirements file. Runtime and development dependencies are separated so a
production image does not need test or static-analysis tools.

### Typed configuration

`Settings` uses Pydantic Settings to parse and validate environment variables.
All variables share the `AGENT_PATTERNS_` prefix, are immutable after startup,
and carry bounds for cache dimensions, TTL, and semantic distance. `.env.example`
documents the supported values without committing secrets.

The application factory accepts a `Settings` instance. Tests can therefore
construct an isolated app without mutating global environment state, while the
normal entry point uses a process-cached settings instance.

### API lifecycle and contracts

The FastAPI lifespan stores process resources on `app.state`; later phases will
open and close graph and Redis resources at this boundary. `/health` reports
process liveness and build metadata. `/ready` represents dependency readiness
and will gain Redis and graph checks as those dependencies are introduced.

Every request receives an `x-request-id`. A caller-provided identifier is
preserved, otherwise the service creates a UUID. Returning the identifier makes
logs, traces, and client failures correlatable across service boundaries.

Response models inherit from a strict base that rejects unknown fields. This
keeps accidental API changes visible and makes the generated OpenAPI document a
reliable contract.

### Quality gates

The project configures Ruff for formatting-independent lint rules, strict Mypy
checking for the application package, and Pytest for contract tests. Phase 1
tests cover settings validation and immutability, health metadata, readiness,
and request-ID propagation.

### Repository hygiene

Generated Python, test, type-checker, build, environment, and operating-system
files are ignored. The original emoji-heavy placeholder README was replaced so
the repository follows the explicit no-emoji requirement.

## Files introduced

- `src/agent_patterns/app.py`: application factory and correlation middleware.
- `src/agent_patterns/config.py`: validated environment configuration.
- `src/agent_patterns/schemas.py`: strict common transport models.
- `src/agent_patterns/api/health.py`: liveness and readiness routes.
- `tests/test_config.py`: configuration behavior tests.
- `tests/test_health.py`: HTTP foundation contract tests.
- `pyproject.toml`: packaging, dependencies, and tool configuration.
- `.env.example`: safe local configuration template.

## Verification

Run the complete Phase 1 gate from an activated virtual environment:

```bash
ruff check .
mypy
pytest
```

Start the API with:

```bash
uvicorn main:app --app-dir src --port 8002
```

The expected result is a healthy response from `/health`, a ready response from
`/ready`, and an `x-request-id` header on both responses.

## Next phase

Phase 2 will build the typed LangGraph state machine, supervisor routing,
specialist workers, persistent checkpoints, human approval resume flow, and
asynchronous execution events on top of this foundation.
