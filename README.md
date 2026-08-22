# FastAPI and LangGraph Production Agent Patterns

A production-oriented reference implementation for stateful LangGraph agent
supervisors, human approval checkpoints, asynchronous token streaming, Redis 8
semantic caching, and end-to-end OpenTelemetry traces.

## Delivery roadmap

The project is implemented and committed in independently documented phases:

1. Service foundation: package layout, typed configuration, health contracts,
   request correlation, linting, type checking, and tests.
2. Agent runtime: a stateful LangGraph supervisor, specialist workers,
   human-in-the-loop interrupts, resumable runs, and async token events.
3. Semantic cache: Redis 8 exact and vector lookup, deterministic embeddings,
   invalidation, concurrency control, and a latency benchmark.
4. Production hardening: OpenTelemetry spans, Docker services, operational
   endpoints, integration tests, and complete runbooks.

Detailed implementation notes are stored in `docs/phaseN.md` after each phase.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
uvicorn main:app --app-dir src --host 0.0.0.0 --port 8002 --reload
```

Then open `http://localhost:8002/docs` or check the service:

```bash
curl http://localhost:8002/health
curl http://localhost:8002/ready
```

## Quality checks

```bash
ruff check .
mypy
pytest
```

## Design constraints

- Python 3.12 or newer and fully asynchronous integration boundaries.
- Dependency injection for external services and deterministic local behavior.
- Strict request schemas and versioned API contracts.
- No hidden network calls or paid model credentials in the default demo.
- Every resume-level performance claim is backed by a reproducible benchmark.

## Author

Vinay K R, Senior GenAI and Applied AI Systems Engineer

- Portfolio: [portfolio.vinaykr.workers.dev](https://portfolio.vinaykr.workers.dev/)
- LinkedIn: [linkedin.com/in/vi-naykr](https://linkedin.com/in/vi-naykr)
- GitHub: [github.com/vi-nayKR](https://github.com/vi-nayKR)
