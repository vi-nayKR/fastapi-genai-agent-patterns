# Traceward measured results

Synthetic known-family template holdout, not real-world model generalization. Latency includes MCP process startup under concurrent load. Ticket checks inspect SQLite persistence. Resumed rows retain their original timestamps, costs and latency; they are not fresh measurements. Different-family judges still need human validation.

Provider: `openai/gpt-oss-120b`. Usage unit: provider_tokens.

| Metric | Measured result |
| --- | --- |
| history_incidents | 200 |
| held_out_cases | 5 |
| root_cause_top1 | 1 |
| root_cause_top3 | 1 |
| completed_cases | 5 |
| tool_calls | 10 |
| tool_call_correctness | 1.0 |
| unnecessary_tool_calls | 0 |
| mean_steps | 4 |
| mean_latency_seconds | 36.64652009999918 |
| p95_latency_seconds | 60.12232919999951 |
| mean_estimated_cost_usd | 0.0006135899999999999 |
| injection_cases | 0 |
| injection_pass_rate | None |
| unauthorized_persisted_tickets | 0 |
| approved_ticket_positive_control | False |
| approval_replay_rejected | False |

Judge validation: `pending_live_judge`.
