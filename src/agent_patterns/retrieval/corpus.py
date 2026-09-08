"""Versioned reference operational corpus for tenant-scoped retrieval and evaluation."""

from agent_patterns.retrieval.models import Document

OPERATIONAL_CORPUS: list[Document] = [
    Document(
        doc_id="DOC-SEC-001",
        title="API Key and Credential Rotation Policy",
        tenant_id="tenant-alpha",
        version=2,
        status="active",
        tags=["security", "auth", "credentials"],
        updated_at="2026-08-15T00:00:00Z",
        content=(
            "Section 1: Scope and Requirements\n"
            "All enterprise service API keys and credentials must be rotated at least every "
            "90 days. Production keys must use at least 256-bit entropy. Ed25519 or RSA-4096 "
            "is required for asymmetric keys. Multi-factor authentication (MFA) is strictly "
            "required for generating or revoking keys.\n\n"
            "Section 2: Rotation Procedure\n"
            "Operators must create a new key version, verify downstream service connectivity, "
            "update the key vault secret, and revoke the previous key version within a 24-hour "
            "grace window. Immediate emergency revocation must be executed through the security "
            "team if a secret leak is suspected."
        ),
    ),
    Document(
        doc_id="DOC-SEC-001-v1",
        title="Legacy API Authentication Guidelines (Deprecated)",
        tenant_id="tenant-alpha",
        version=1,
        status="deprecated",
        tags=["security", "auth", "legacy"],
        updated_at="2024-01-10T00:00:00Z",
        content=(
            "Section 1: Legacy Authentication\n"
            "Legacy API authentication uses static HMAC-SHA1 tokens without mandatory expiration. "
            "MFA is optional for service accounts. Tokens do not require periodic rotation unless "
            "compromised.\n"
            "Notice: This specification is DEPRECATED and superseded by DOC-SEC-001 v2."
        ),
    ),
    Document(
        doc_id="DOC-OPS-002",
        title="Production Incident Escalation Runbook",
        tenant_id="tenant-alpha",
        version=1,
        status="active",
        tags=["operations", "incidents", "escalation"],
        updated_at="2026-07-20T00:00:00Z",
        content=(
            "Section 1: Incident Severity Levels\n"
            "P1: Complete customer outage or data corruption. Incident Commander must be assigned "
            "within 15 minutes. Create Slack channel #incidents-p1 and page on-call engineers via "
            "PagerDuty.\n"
            "P2: Degraded service performance or major feature failure affecting >10% of users. "
            "Response deadline is 45 minutes.\n"
            "P3: Minor operational issue with available workaround. Response deadline is "
            "4 hours.\n\n"
            "Section 2: Communication and Status Updates\n"
            "Public status page must be updated within 30 minutes of a P1 declaration. "
            "Updates must be published every 30 minutes until resolution."
        ),
    ),
    Document(
        doc_id="DOC-OPS-003",
        title="Database Migration and Automated Backup Runbook",
        tenant_id="tenant-alpha",
        version=2,
        status="active",
        tags=["database", "migrations", "backup"],
        updated_at="2026-08-01T00:00:00Z",
        content=(
            "Section 1: Schema Migrations\n"
            "Database migrations must be executed via automated migration tooling (Alembic). "
            "Manual DDL execution on production databases is strictly prohibited. Every "
            "migration must support backward-compatible rollout and forward rollback.\n\n"
            "Section 2: Backup and Retention\n"
            "Point-in-time recovery (PITR) is enabled with a 30-day retention window. Automated "
            "full snapshots occur every 24 hours at 02:00 UTC and are stored in immutable "
            "multi-region cloud storage."
        ),
    ),
    Document(
        doc_id="DOC-OPS-003-v1",
        title="Manual Database Maintenance Scripts (Deprecated)",
        tenant_id="tenant-alpha",
        version=1,
        status="deprecated",
        tags=["database", "maintenance", "legacy"],
        updated_at="2024-03-15T00:00:00Z",
        content=(
            "Section 1: Direct SQL Execution\n"
            "Database maintenance scripts may be executed manually by operators using direct "
            "psql sessions. Backups are captured manually before major script execution.\n"
            "Notice: This practice is DEPRECATED and strictly forbidden by DOC-OPS-003 v2."
        ),
    ),
    Document(
        doc_id="DOC-BILL-004",
        title="Customer Refund and Billing Dispute Policy",
        tenant_id="tenant-alpha",
        version=1,
        status="active",
        tags=["billing", "refunds", "disputes"],
        updated_at="2026-06-10T00:00:00Z",
        content=(
            "Section 1: Eligibility Window\n"
            "Refund requests are eligible within 30 calendar days of invoice date for unused "
            "platform credits or verified service outages. Subscriptions that have consumed "
            "more than 20% of quota are non-refundable.\n\n"
            "Section 2: Approval Matrix\n"
            "Customer Support Agents can authorize refunds up to $100. Billing Managers must "
            "approve refunds between $101 and $500. Director of Finance authorization is "
            "required for any refund exceeding $500."
        ),
    ),
    Document(
        doc_id="DOC-SLA-005",
        title="Enterprise Customer SLA Commitments",
        tenant_id="tenant-alpha",
        version=1,
        status="active",
        tags=["sla", "support", "contracts"],
        updated_at="2026-05-01T00:00:00Z",
        content=(
            "Section 1: Uptime Commitments\n"
            "The platform guarantees 99.95% monthly service availability for Enterprise Tier "
            "accounts. Scheduled maintenance windows are excluded if announced at least 5 "
            "business days in advance.\n\n"
            "Section 2: Support Response Times\n"
            "Severity 1 (P1): Initial response within 30 minutes, 24x7x365 coverage.\n"
            "Severity 2 (P2): Initial response within 2 hours during business hours.\n"
            "Severity 3 (P3): Initial response within 24 hours during business hours."
        ),
    ),
    Document(
        doc_id="DOC-PAY-006",
        title="Payment Gateway Webhook and Integration Standards",
        tenant_id="tenant-alpha",
        version=1,
        status="active",
        tags=["payments", "webhooks", "integration"],
        updated_at="2026-07-05T00:00:00Z",
        content=(
            "Section 1: Webhook Signature Verification\n"
            "Inbound payment webhooks must verify the HMAC-SHA256 signature in the "
            "X-Signature-SHA256 header using the tenant webhook secret. Requests with invalid "
            "or missing signatures must be rejected with HTTP 401.\n\n"
            "Section 2: Timeout and Retry Standards\n"
            "Outbound payment requests have a strict timeout of 5.0 seconds. A maximum of 3 "
            "retries with exponential backoff (1s, 2s, 4s) is permitted for transient network "
            "errors. Webhook processing must be idempotent."
        ),
    ),
    Document(
        doc_id="DOC-DATA-007",
        title="Customer Data Deletion and GDPR Erasure Runbook",
        tenant_id="tenant-alpha",
        version=1,
        status="active",
        tags=["compliance", "gdpr", "data-privacy"],
        updated_at="2026-04-18T00:00:00Z",
        content=(
            "Section 1: Erasure Request Processing\n"
            "Right-to-be-forgotten requests must be verified through the Privacy Portal. "
            "A 14-day soft-delete grace period applies before permanent erasure. Two-person "
            "authorization is required before initiating permanent purge.\n\n"
            "Section 2: Retention and Audit Exclusions\n"
            "Financial transaction records and security audit logs must be retained for 7 years "
            "per regulatory mandates and are legally exempt from customer deletion requests."
        ),
    ),
    Document(
        doc_id="DOC-DEP-008",
        title="Production Deployment Gates and Rollback Policy",
        tenant_id="tenant-alpha",
        version=1,
        status="active",
        tags=["deployment", "ci-cd", "release"],
        updated_at="2026-08-20T00:00:00Z",
        content=(
            "Section 1: Deployment Gates\n"
            "All production releases require: (a) passing automated CI test suite, (b) container "
            "image vulnerability scan with zero critical CVEs, and (c) a 10-minute canary "
            "evaluation at 5% traffic.\n\n"
            "Section 2: Automated Rollback Triggers\n"
            "Canary deployments automatically roll back if HTTP 5xx error rate exceeds 0.5% "
            "or latency p95 increases by more than 20% compared to baseline."
        ),
    ),
    Document(
        doc_id="DOC-BETA-SEC-001",
        title="Tenant Beta Secret Management Specification",
        tenant_id="tenant-beta",
        version=1,
        status="active",
        tags=["security", "secrets", "tenant-beta"],
        updated_at="2026-08-01T00:00:00Z",
        content=(
            "Section 1: Dedicated KMS Key\n"
            "Tenant Beta secrets are isolated under dedicated KMS alias 'alias/tenant-beta-cmk'. "
            "Under no circumstances may Tenant Beta secrets be accessed with Tenant Alpha "
            "credentials or roles.\n\n"
            "Section 2: Access Auditing\n"
            "All decrypt calls are logged to CloudTrail with tenant_id attribute validation."
        ),
    ),
    Document(
        doc_id="DOC-BETA-OPS-002",
        title="Tenant Beta Support Escalation Matrix",
        tenant_id="tenant-beta",
        version=1,
        status="active",
        tags=["support", "tenant-beta"],
        updated_at="2026-08-01T00:00:00Z",
        content=(
            "Section 1: Contact Channels\n"
            "Tenant Beta incidents are routed to support@beta.internal. P1 phone bridge is "
            "+1-800-555-BETA. Dedicated Slack channel is #tenant-beta-ops."
        ),
    ),
]
