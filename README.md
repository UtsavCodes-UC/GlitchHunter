# GlitchHunter

Finds, reproduces and validates concurrency bugs (race conditions) in database-backed APIs, and checks AI-proposed fixes by rerunning the failing run.

Built during Hackman X (26–27 Oct 2026).

Loop: propose invariants → filter → attack → explain → repair.

## Layout
- `apps/` demo target apps (wallet, inventory)
- `controller/` attacker, runners, replay
- `orchestrator/` FastAPI, LLM client, propose, filter, repair (`prompts/`)
- `dashboard/` Next.js UI
- `cli/` command line over the same modules
- `docs/` contracts, claims, decisions
- `runs/` generated output (git-ignored)

## Secrets
API keys are read from environment variables only (e.g. `GEMINI_API_KEY`). Never commit them.
