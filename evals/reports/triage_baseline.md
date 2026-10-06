# Traceward measured results

Synthetic known-family template holdout, not real-world model generalization. Latency includes MCP process startup under concurrent load. Ticket checks inspect SQLite persistence. A Gemini judge shares the agent's family: self-preference bias is possible.

Provider: `deterministic-stub`. Usage unit: UTF-8 byte counters (not LLM tokens).

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
| mean_latency_seconds | 3.5279256459998214 |
| p95_latency_seconds | 4.800488099999711 |
| mean_estimated_cost_usd | 0.0 |
| injection_cases | 20 |
| injection_pass_rate | 1 |
| unauthorized_persisted_tickets | 0 |
| approved_ticket_positive_control | True |
| approval_replay_rejected | True |

Judge validation: `pending_live_provider_and_human_labels`.
