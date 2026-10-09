# Traceward interview notes

Use these as decision explanations, not performance claims. The full live run is measured (2026-10-09, [report](results/triage_live.md)). On 50 held-out cases: root-cause top-1 1.00, tool-call correctness 1.00, 20/20 injection cases blocked with 0 unapproved writes, and a different-family judge mean of 4.94/5. How to say it: "the pipeline is correct end to end on a synthetic template holdout, which it saturates. It shows the mechanics (tools, approval gate, injection defence), not generalization." The judge score is not human-validated: the blind review set was never labelled, so judge-human agreement was not measured. Stub checks cannot establish model quality.

## Supervisor-specialist graph

**Chosen:** Preserve the existing checkpointed LangGraph supervisor and four specialists: log parser, similar-incident retriever, root-cause hypothesiser and fix drafter. Parsing/retrieval are deterministic tool operations; only hypothesis and fix generation need model calls.

**Alternative:** A single agent prompt with unrestricted tool selection.

**Why:** The project already had graph routing, checkpoints, approvals and SSE. Reusing those boundaries made the refactor smaller and gives each stage explicit inputs, measurable tool calls and an early-stop path. A single agent would be simpler for a new prototype; no measured comparison establishes that this graph improves accuracy or cost.

**Evidence:** [graph.py](src/agent_patterns/agents/graph.py), [workers.py](src/agent_patterns/agents/workers.py), [orchestration tests](tests/test_agents.py). The supervisor stops on missing evidence, worker failures and limits. SSE emits completed worker output; it is not provider time-to-first-token streaming.

## Approval before ticket creation

**Chosen:** Show the exact proposal, interrupt for an authenticated reviewer, then sign a capability bound to tenant, thread and draft contents. The MCP server verifies that capability before an idempotent local SQLite write. No fix runs automatically.

**Alternative:** Trust an LLM saying it obtained approval, or create the ticket first and ask for review afterward.

**Why:** Logs and model output are untrusted. Approval must control the side effect itself. Content binding prevents approval of one proposal authorizing another; idempotency handles duplicate delivery. This is local ticket-draft persistence, not external issue creation.

**Evidence:** [graph.py](src/agent_patterns/agents/graph.py), [incident_tools.py](src/agent_patterns/incident_tools.py), [forgery/tampering tests](tests/test_mcp_guardrails.py). [PostgreSQL recovery test](tests/integration/test_checkpoint_approval.py) checks restart recovery, tenant boundaries and replay rejection when its service URL is configured; that external-service test is skipped locally.

## MCP tools and trust boundaries

**Chosen:** Three narrow tools: `get_log_context`, `search_incidents`, `create_ticket_draft`, exposed through the official MCP SDK over stdio and consumed through a real MCP `ClientSession`. The log tool parses supplied text; it does not read arbitrary filesystem paths. Provider credentials are excluded from the tool subprocess environment.

**Alternative:** Direct Python calls, or a generic shell/filesystem tool exposed to the model.

**Why:** Direct calls would be enough for an internal-only prototype, but MCP interoperability was explicitly required. Narrow operations make arguments and authorization testable. Stdio avoids adding a public tool HTTP listener. The approval secret stays in trusted service/tool code; it is never model context.

**Evidence:** [MCP client](src/agent_patterns/mcp_client.py), [MCP server](src/agent_patterns/incident_tools.py), [MCP guardrail tests](tests/test_mcp_guardrails.py). Tool correctness uses expected arguments, rather than merely counting successful calls.

## Cross-family fix-quality judge

**Chosen:** Groq `openai/gpt-oss-120b` as agent at temperature 0.1 and `qwen/qwen3.8-27b` as judge at temperature 0. Exact IDs, temperatures and UTC dates are recorded in results. Fifteen frozen review proposals mix useful, vague and harmful outputs; human labels and rationale start blank.

**Alternative:** Have the agent grade its own fixes, use a same-family judge, or rely only on automated scores.

**Why:** Different model families reduce same-family self-preference concerns; they do not prove unbiased judgment. A mixed blind review set tests discrimination. The human comparison reports exact match, agreement within one point and unweighted Cohen's kappa, with disagreements listed. Human validation remains pending until the user labels all cases. Qwen is a preview model, so model availability may change.

**Evidence:** [judge/evaluator](evals/evaluator.py), [blank blind review](evals/review/blind_review.md), [comparison command](scripts/compare_judge.py), [agreement tests](tests/test_evaluation.py). The frozen review set includes stub-derived and deliberately edited proposals; it is a calibration set, not an estimate of production fix quality. Raw responses/checkpointed scores allow comparison without another paid model call.

## Token throttling and resume across days

**Chosen:** A 20-second minimum interval plus conservative per-model reservations in SQLite for rolling 60-second/24-hour token limits. Rejected 429 calls use bounded exponential backoff and numeric Retry-After; explicit daily exhaustion exits with progress saved. Completed cases/probes/judge scores and a cumulative cost ledger are atomically checkpointed; raw responses preserve partial cases. The campaign hashes source, data and model settings.

**Alternative:** Fixed sleeps only, repeat every case after failure, or reset the cost cap on restart.

**Why:** Request spacing alone cannot enforce tokens per minute. Persistent state permits slow free-tier runs across days without repeating completed work or resetting the campaign budget. Rolling windows are conservative; actual provider 429s remain authoritative because other applications can consume quota. Unknown generated/interrupted requests retain reservations. One evaluation process per campaign is the documented ceiling.

**Evidence:** [quota.py](src/agent_patterns/providers/quota.py), [provider retry/cache logic](src/agent_patterns/providers/openai_provider.py), [progress.py](evals/progress.py), [evaluation CLI](scripts/run_evaluation.py), [resume/quota tests](tests/test_resume.py). The current smoke replay reused results with zero API calls; that is resume evidence, not full-run quality evidence. Resumed measurements retain original timestamps and are not presented as fresh latency/cost measurements.

## Prompt-injection tests

**Chosen:** Embed malicious instructions before and after realistic crash text: fake system/reviewer messages, approval bypass, credential exfiltration, forged capabilities, filesystem reads and encoded instructions. Ten payloads each run in both placements. Check actual persisted ticket rows, rejection behavior and permitted tool calls; also run an approved-write positive control and replay control.

**Alternative:** Test only whether the final answer says it resisted the attack, or rely on a system prompt alone.

**Why:** A refusal sentence cannot prove absence of a side effect. Persistence checks exercise the authorization boundary. Positive controls avoid declaring success because all writes are broken. The allowlisted tools contain no arbitrary network-send or file-read operation. These probes are a finite suite, not proof against every injection or data leak.

**Evidence:** [attack payloads and controls](evals/evaluator.py), [signed-approval tests](tests/test_mcp_guardrails.py), [stub regression report](evals/reports/triage_baseline.json). Stub probes establish deterministic enforcement behavior only; the live injection result remains pending.

## Hybrid retrieval and synthetic holdout

**Chosen:** Reuse BM25, normalized hashing vectors and reciprocal-rank fusion over 200 synthetic historical incidents. Hold out 50 labelled cases from ten failure families; index historical log text only, keeping test labels outside model input.

**Alternative:** Public GitHub incidents plus learned embeddings and a vector database.

**Why:** Documented deterministic generation gave reproducible logs, resolutions and labels without a new dependency or uncertain public-data labelling. Existing retrieval was sufficient for this corpus. The tradeoff is substantial: shared template-family symptoms make the benchmark easier than unknown production incidents.

**Evidence:** [generator](scripts/generate_incidents.py), [corpus](evals/data/incidents.json), [evaluator](evals/evaluator.py). Corpus reproducibility, label isolation and tool argument checks are verified by tests. Do not claim semantic-embedding quality or production accuracy from these data.

## Budgets and preserved infrastructure

**Chosen:** Reserve prompt capacity and bounded output before model calls; keep request token/cost and step caps with graceful stop. Preserve PostgreSQL checkpoints, Redis cache routes, OpenTelemetry spans and SSE. Keep triage approvals outside cache routes.

**Alternative:** Unbounded retries/agent loops, or rewrite the application around a new framework.

**Why:** Bounded calls make resource exhaustion explicit. Existing infrastructure already solved durability and observability. Separating approvals from cache hits prevents a cached response from granting write authorization. Conservative UTF-8 bounds sacrifice utilization for safety; alternative tokenizers need their own accounting.

**Evidence:** [workers.py](src/agent_patterns/agents/workers.py), [provider budget](src/agent_patterns/providers/base.py), [config](src/agent_patterns/config.py), [verification report](evals/reports/checks.json). Local Redis/PostgreSQL skips are documented in the README with exact opt-in commands; CI supplies both services.

## What failed and what changed

Gemini Pro exhausted rate-limit retries for this free-tier account. Calling this account's judge unavailable is supported; a universal claim that Gemini Pro is unavailable on every free tier is not. Flash fallback did not produce a complete run: recorded errors include 503 high demand, a 404 saying Gemini 2.5 Flash was unavailable to new users, and token-usage validation failures. The saved reports do not prove that all Flash failures were quota exhaustion. The user then configured Groq with separate GPT-OSS/Qwen families and explicit token limits.

The first Groq smoke found a fix response truncated into invalid JSON. Fix-drafting instructions were shortened to fit the bounded output cap; uncertain generated errors retain token reservations. The later five-case smoke completed and its replay used checkpoints without new API calls. This validates the setup and resume path; full live results still await completion.

**Evidence:** [archived attempts](results/attempts/README.md), [current smoke only](results/smoke.json), [provider usage/retry tests](tests/test_provider.py), [resume tests](tests/test_resume.py). Historical report status fields predate current completeness checks; examine case/judge errors instead of quoting them as successful evaluations.

## Human validation next

Preserve the fifteen frozen review cases and blank [review file](evals/review/blind_review.md); never reveal judge scores or prefill labels. After the full live run, commit its results separately as `results: live eval v1`. The user labels 1-5, yes/no apply and one-line rationale independently. Run `python -m scripts.compare_judge` afterward and discuss disagreements without changing human labels to match the judge. Agreement is pending until those labels exist.
