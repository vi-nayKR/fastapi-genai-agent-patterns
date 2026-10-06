# Superseded provider setup attempts

These incomplete Gemini/Groq smoke attempts are retained for troubleshooting and provenance. They are superseded by `../smoke.json` and `../smoke.md`, which record the current **five-case smoke test only**. None of these files establishes full-evaluation quality.

| Attempt | What the recorded run shows |
| --- | --- |
| `smoke_pro_unavailable.json` | Gemini Pro judge exhausted rate-limit retries; agent attempts also encountered capacity errors. |
| `smoke_25_not_available.json` | Gemini 2.5 Flash returned 404: unavailable to new users of this account. |
| `smoke_37_usage_rejected.json` | Token-usage validation rejected responses; some calls also returned 503. |
| `smoke_37_capacity_incomplete.json` | Gemini 3.7 Flash returned 503 high-demand errors. |
| `smoke_flash_fallback_incomplete.json` | Gemini Flash fallback remained incomplete because of capacity/provider failures. |
| `smoke_groq_initial.json` | Initial Groq smoke had a truncated fix response rejected as invalid JSON; concise fix instructions resolved it in the current smoke. |

Some historical status fields predate the current completeness checks. Read per-case failures and judge errors; do not interpret a historical `measured` field as a successful run. No provider credentials are stored here. Raw responses and resumable campaign state remain ignored private artifacts.
