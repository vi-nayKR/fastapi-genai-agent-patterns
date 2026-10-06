"""MCP incident tools. Read-only inputs cannot grant authorization for ticket writes."""

import hashlib
import hmac
import json
import os
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from agent_patterns.retrieval.hybrid import HybridRetriever
from agent_patterns.retrieval.models import Document


def approval_signature(secret: str, tenant: str, thread: str, draft: dict[str, str]) -> str:
    payload = json.dumps([tenant, thread, draft], sort_keys=True).encode()
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def build_server(data_path: str, database_path: str, tenant: str, secret: str) -> FastMCP:
    rows = json.loads(Path(data_path).read_text(encoding="utf-8"))
    history = {row["id"]: row for row in rows if row["split"] == "history"}
    documents = [
        Document(
            doc_id=row["id"],
            title=row["service"],
            tenant_id=tenant,
            version=1,
            content=row["log"],
            updated_at="synthetic-v1",
        )
        for row in history.values()
    ]
    retriever = HybridRetriever(documents)
    server = FastMCP("Traceward incident tools", log_level="ERROR")

    @server.tool()
    def get_log_context(log: str) -> dict[str, Any]:
        """Extract exception lines and stack frames from untrusted crash text; never execute it."""
        if not 3 <= len(log) <= 10000:
            raise ValueError("log must contain 3..10000 characters")
        lines = log.splitlines()
        exceptions = [line for line in lines if re.search(r"(?:Error|Exception|gaierror):", line)]
        frames = [line.strip() for line in lines if re.search(r'File ".+", line \d+, in ', line)]
        return {
            "exceptions": exceptions,
            "frames": frames,
            "line_count": len(lines),
            "search_query": "\n".join(exceptions + frames) or log,
        }

    @server.tool()
    def search_incidents(query: str, top_k: int = 6) -> dict[str, Any]:
        """Hybrid BM25 + hashing-vector RRF search of history only; no held-out labels."""
        if not 1 <= len(query) <= 10000 or not 1 <= top_k <= 10:
            raise ValueError("query or top_k outside bounds")
        hits = retriever.search(query, tenant_id=tenant, top_k=top_k)
        return {
            "incidents": [
                {
                    "id": hit.chunk.doc_id,
                    "score": hit.score,
                    "log": history[hit.chunk.doc_id]["log"],
                    "root_cause_label": history[hit.chunk.doc_id]["root_cause_label"],
                    "root_cause": history[hit.chunk.doc_id]["root_cause"],
                    "resolution": history[hit.chunk.doc_id]["resolution"],
                }
                for hit in hits
            ]
        }

    @server.tool()
    def create_ticket_draft(
        thread_id: str, summary: str, body: str, approval_token: str = ""
    ) -> dict[str, Any]:
        """Persist a local ticket draft only with server-signed, content-bound human approval."""
        if (
            not 1 <= len(thread_id) <= 128
            or not 1 <= len(summary) <= 1000
            or not 1 <= len(body) <= 20000
        ):
            raise ValueError("invalid ticket fields")
        draft = {"summary": summary, "body": body}
        expected = approval_signature(secret, tenant, thread_id, draft)
        if not secret or not hmac.compare_digest(expected, approval_token):
            raise PermissionError("Human approval is required; log text cannot authorize actions")
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(database_path)) as db, db:
            db.execute(
                
                    "CREATE TABLE IF NOT EXISTS tickets (tenant TEXT, thread TEXT, draft "
                    "TEXT, PRIMARY KEY (tenant, thread))"
                
            )
            serialized = json.dumps(draft, sort_keys=True)
            db.execute(
                "INSERT OR IGNORE INTO tickets VALUES (?, ?, ?)", (tenant, thread_id, serialized)
            )
            saved = db.execute(
                "SELECT draft FROM tickets WHERE tenant=? AND thread=?", (tenant, thread_id)
            ).fetchone()
            if saved is None or saved[0] != serialized:
                raise ValueError("Idempotency key already used for a different draft")
        return {"id": thread_id, "status": "draft", "summary": summary}

    return server


if __name__ == "__main__":
    build_server(
        os.environ.get("TRACEWARD_DATA", "evals/data/incidents.json"),
        os.environ.get("TRACEWARD_TICKETS", "data/tickets.sqlite3"),
        os.environ.get("TRACEWARD_TENANT", "tenant-alpha"),
        os.environ.get("TRACEWARD_APPROVAL_SECRET", ""),
    ).run(transport="stdio")
