# Traceward measured results

Synthetic known-family template holdout, not real-world model generalization. Latency includes MCP process startup under concurrent load. Ticket checks inspect SQLite persistence. A Gemini judge shares the agent's family: self-preference bias is possible.

Provider: `gemini-3.7-flash`. Usage unit: provider_tokens.

| Metric | Measured result |
| --- | --- |
| history_incidents | 200 |
| held_out_cases | 5 |
| root_cause_top1 | 0.6 |
| root_cause_top3 | 0.6 |
| completed_cases | 0 |
| tool_calls | 10 |
| tool_call_correctness | 1.0 |
| unnecessary_tool_calls | 0 |
| mean_steps | 3.6 |
| mean_latency_seconds | 31.640952599999583 |
| p95_latency_seconds | 54.98598530000163 |
| mean_estimated_cost_usd | 0.1192536 |
| injection_cases | 0 |
| injection_pass_rate | None |
| unauthorized_persisted_tickets | 0 |
| approved_ticket_positive_control | False |
| approval_replay_rejected | False |

Judge validation: `pending_live_judge`.
