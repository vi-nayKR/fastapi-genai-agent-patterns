# Traceward measured results

Synthetic known-family template holdout, not real-world model generalization. Latency includes MCP process startup under concurrent load. Ticket checks inspect SQLite persistence. Resumed rows retain their original timestamps, costs and latency; they are not fresh measurements. Different-family judges still need human validation.

Provider: `openai/gpt-oss-120b`. Usage unit: provider_tokens.

| Metric | Measured result |
| --- | --- |
| history_incidents | 200 |
| held_out_cases | 50 |
| root_cause_top1 | 1 |
| root_cause_top3 | 1 |
| completed_cases | 50 |
| tool_calls | 100 |
| tool_call_correctness | 1.0 |
| unnecessary_tool_calls | 0 |
| mean_steps | 4 |
| mean_latency_seconds | 78.98708968600003 |
| p95_latency_seconds | 120.3763639999961 |
| mean_estimated_cost_usd | 0.000628572 |
| injection_cases | 20 |
| injection_pass_rate | 1 |
| unauthorized_persisted_tickets | 0 |
| approved_ticket_positive_control | True |
| approval_replay_rejected | True |

Judge validation: `pending_human_labels`.
