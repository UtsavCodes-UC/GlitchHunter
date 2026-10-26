# GlitchHunter

Finds, reproduces and validates concurrency bugs (race conditions) in database-backed APIs, and checks AI-proposed fixes by rerunning the failing run.

Built during Hackman X (26–27 Oct 2026). See `docs/prototype_note.md` for what existed before the event.

Loop: propose checks → filter → attack → explain → repair.

## Three ways to use it
- **Dashboard** (`dashboard/`): a guided page per example in plain language, plus "Try your own app".
- **Command line** (`cli/`): `.\glitchhunter doctor`, `scan`, `checks`, `repair`, `test`, `upload`, `demo`. See `docs/cli.md`.
- **API** (`orchestrator/`): what the dashboard calls. Contract in `docs/contracts.md`.

## Quick start (Windows, PowerShell, PostgreSQL 16 running)
Two terminals, from the repo root:
```powershell
pip install -r requirements.txt
.\glitchhunter serve        # terminal 1: the whole backend (demo apps + API); Ctrl+C stops it
.\glitchhunter ui           # terminal 2: the dashboard at http://localhost:3000 (builds it the first time)
```
`GH_DATABASE_URL` defaults to `postgresql://rh:rh@localhost:5432/rh` (database `rh`, user `rh`). Set `GEMINI_API_KEY` in terminal 1 for the AI steps (otherwise the local Ollama model is used). If ports are stuck after a closed window: `.\glitchhunter stop --all`, or add `--restart` to either command.
Command line only (no dashboard): `.\glitchhunter doctor`, then `.\glitchhunter demo wallet` with `serve` running.
The AI steps use `GEMINI_API_KEY` (environment variable, never a file). If Gemini is unavailable they fall back to a local Ollama model.

## Layout
- `apps/` demo target apps (wallet, inventory)
- `controller/` attacker, validator, test generator, request log
- `orchestrator/` API, AI client, propose / filter / repair, uploaded-project handling
- `cli/` the command line
- `dashboard/` Next.js UI
- `examples/` a sample app to upload
- `docs/` contracts, CLI, upload feature, head-to-head results, notes
- `runs/` generated output (git-ignored)

## What it does and does not claim
It reproduces a race and validates a fix by rerunning the failing run and fresh simultaneous trials. It does not prove a race is gone, and the AI does not discover business rules on its own: it proposes checks from a template and a person decides which to use. It has only been run on demo apps we wrote plus one sample uploaded app. Prior art: ACIDRain and Raccoon.

## Secrets
API keys are read from environment variables only (`GEMINI_API_KEY`). Never commit them.
