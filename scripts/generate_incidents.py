"""Generate a reproducible synthetic corpus; never index held-out labels or resolutions."""

import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED = 20261006
# Templates describe independent operational failure families, not real GitHub incidents.
FAMILIES = [
    (
        "pool_exhaustion",
        "sqlalchemy.exc.TimeoutError",
        "QueuePool limit reached; connection checkout timed out",
        "database.py",
        "checkout",
        "Connections were not returned after failed transactions.",
        (
            "Use context-managed sessions and rollback on failure; verify pool "
            "checkout recovers under load."
        ),
    ),
    (
        "event_loop_blocked",
        "asyncio.exceptions.TimeoutError",
        "event loop lag=2400ms; heartbeat missed during synchronous requests.get",
        "gateway.py",
        "fetch",
        "Blocking network I/O stalled the asyncio event loop.",
        (
            "Replace synchronous I/O with an async client or asyncio.to_thread; "
            "test concurrent heartbeat latency."
        ),
    ),
    (
        "schema_drift",
        "sqlalchemy.exc.ProgrammingError",
        "UndefinedColumn: column accounts.billing_region does not exist",
        "repository.py",
        "load_account",
        "Application rollout preceded the required database migration.",
        (
            "Apply the reviewed compatible migration before rollout or roll back "
            "the application; verify schema compatibility."
        ),
    ),
    (
        "memory_leak",
        "MemoryError",
        "RSS grew continuously; unbounded response_cache entries; allocation failed",
        "cache.py",
        "store_response",
        "An unbounded cache retained request payloads indefinitely.",
        (
            "Bound cache size and expiration; load-test RSS stabilization and "
            "preserve eviction metrics."
        ),
    ),
    (
        "missing_configuration",
        "KeyError",
        "required environment variable DATABASE_URL missing at startup",
        "settings.py",
        "load_settings",
        "Deployment omitted required database configuration.",
        (
            "Restore DATABASE_URL through the secret/config store; validate "
            "required configuration before accepting traffic."
        ),
    ),
    (
        "filesystem_permission",
        "PermissionError",
        "[Errno 13] Permission denied: /var/lib/service/uploads",
        "storage.py",
        "save_upload",
        "The runtime user could not write to the mounted upload directory.",
        (
            "Correct mount ownership for the runtime UID with least privilege; "
            "verify an upload without granting world-write access."
        ),
    ),
    (
        "dns_failure",
        "socket.gaierror",
        "[Errno -3] Temporary failure in name resolution for inventory.internal",
        "client.py",
        "resolve",
        "Service discovery failed to resolve the upstream hostname.",
        (
            "Restore the DNS/service-discovery record and validate resolution from "
            "the workload; use bounded retries with backoff."
        ),
    ),
    (
        "dependency_incompatibility",
        "TypeError",
        ("Client.__init__() got an unexpected keyword argument 'proxies' after httpx upgrade"),
        "transport.py",
        "build_client",
        "An SDK passed an argument removed by the upgraded HTTP client.",
        (
            "Pin a compatible SDK/httpx pair or upgrade the SDK; verify client "
            "initialization in the dependency lockfile test."
        ),
    ),
    (
        "concurrent_mutation",
        "RuntimeError",
        ("dictionary changed size during iteration while background refresh removed keys"),
        "registry.py",
        "snapshot",
        "A concurrent writer mutated the registry while readers iterated it.",
        (
            "Synchronize registry access or iterate an immutable snapshot; "
            "reproduce concurrent refresh and read operations."
        ),
    ),
    (
        "disk_full",
        "OSError",
        "[Errno 28] No space left on device; WAL append failed on /data",
        "wal.py",
        "append",
        "Retained logs exhausted the data volume.",
        (
            "Expand the volume or rotate reviewed disposable logs; verify free "
            "space and WAL durability before resuming writes."
        ),
    ),
]


def generate() -> list[dict[str, object]]:
    rng = random.Random(SEED)
    rows = []
    for family, exception, symptom, filename, function, cause, fix in FAMILIES:
        for i in range(25):
            held_out = i >= 20
            service = rng.choice(["checkout", "catalog", "notifications", "worker", "billing"])
            if held_out:
                log = (
                    f"2026-09-{i:02d}T13:21:47Z pod={service}-{rng.randrange(100, 999)} "
                    "severity=ERROR\n"
                    f"request failed after retry; {symptom}\n"
                    f'  File "/srv/{service}/{filename}", line {rng.randrange(30, 190)}, '
                    f"in {function}\n"
                    f"{exception}: {symptom}\nWARN health probe failed; investigating rollout"
                )
            else:
                log = (
                    f"2026-08-{i + 1:02d}T08:12:03Z ERROR service={service} "
                    f"request_id=req-{rng.randrange(10000, 99999)}\n"
                    "Traceback (most recent call last):\n"
                    f'  File "/app/{filename}", line {rng.randrange(10, 150)}, in {function}\n'
                    f"{exception}: {symptom}\nINFO restart scheduled; upstream latency elevated"
                )
            rows.append(
                {
                    "id": f"INC-{len(rows) + 1:04d}",
                    "split": "test" if held_out else "history",
                    "service": service,
                    "log": log,
                    "root_cause_label": family,
                    "root_cause": cause,
                    "resolution": fix,
                    "provenance": "synthetic-v1; scripts/generate_incidents.py",
                    "expected_search_query": f"{exception}: {symptom}\n"
                    + log.splitlines()[2].strip(),
                }
            )
    rng.shuffle(rows)
    return rows


def main() -> None:
    target = ROOT / "evals/data/incidents.json"
    target.write_text(json.dumps(generate(), indent=2) + "\n", encoding="utf-8")
    print(f"Generated {target}")


if __name__ == "__main__":
    main()
