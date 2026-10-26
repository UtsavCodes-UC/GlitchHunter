# GlitchHunter command line

Runs in the VS Code integrated terminal (PowerShell) from the repo root. No extra packages: it uses the same code as the API and dashboard, and shares the same stored checks (`runs/state/`), so what you approve in the CLI also shows in the dashboard.

```powershell
.\glitchhunter <command> ...        # or: python -m cli <command> ...
```

Needs `GH_DATABASE_URL` (for example `postgresql://rh:rh@localhost:5432/rh`). The AI steps need `GEMINI_API_KEY` (or a running Ollama; see below). Colour only appears in a real terminal; set `NO_COLOR=1` to turn it off.

If the ✔ / ✖ symbols look garbled (for example when you redirect output to a file in Windows PowerShell 5.1), set `GH_ASCII=1` for plain `[ok]` / `[x]`.

## Exit codes (so it can gate CI)
- `0` fine: no bug found / fix accepted / test passed
- `1` a bug was found, or the fix was not accepted, or the replayed problem happened again
- `2` setup or usage problem (message printed, no traceback; add `--debug` for one)

## Commands
| Command | What it does |
|---|---|
| `doctor` | checks Python, PostgreSQL, the AI keys, Ollama and whether the demo apps are running |
| `scenarios` | lists the demo scenarios (wallet, inventory) and uploaded apps |
| `checks SCENARIO [--propose] [--filter] [--auto-approve] [--approve ID...] [--reject ID...] [--decoys]` | AI suggests checks, the filter tests them, you choose which count. Without flags it just lists them |
| `scan SCENARIO [--trials 50] [-n N] [--json]` | attacks with simultaneous requests; prints which checks broke and one failed try as a story; **exit 1 if a bug is found** |
| `repair SCENARIO [--k 50] [--attempts 3] [--code]` | the AI writes a fix, tested on a copy of the app; saves the accepted function under `runs/patches/`; **exit 0 only if accepted** |
| `replay FILE.json [--trials 20]` | re-runs a saved failing schedule (written by `scan` under `runs/<run_id>/`) |
| `test SCENARIO` | writes a regression test from a failing run to `tests/generated/` (demo scenarios) |
| `upload --name N --app FILE --sql FILE [--env DATABASE_URL] [--endpoint "POST /book"] [--params JSON] [-n 6] [--state table.column]` | adds your own FastAPI + PostgreSQL app as scenario `custom_<id>` (limits: `docs/try_your_own_app.md`) |
| `delete-project ID` | removes an uploaded app, its files and its database schema |
| `demo SCENARIO [--no-decoys]` | the whole loop in one go (propose, filter, approve, attack, repair, control) |

## Typical session (demo apps)
Start the target app first (see `apps/README.md`, for example the vulnerable wallet on port 8000), then:

```powershell
.\glitchhunter doctor
.\glitchhunter checks wallet --propose --filter --auto-approve
.\glitchhunter scan wallet
.\glitchhunter repair wallet
.\glitchhunter test wallet
```

## Your own app
```powershell
.\glitchhunter upload --name "Ticket shop" --app examples\ticket_shop\ticket_shop.py --sql examples\ticket_shop\setup.sql
.\glitchhunter checks custom_ticket_shop_xxxx --propose --filter --auto-approve
.\glitchhunter scan custom_ticket_shop_xxxx
.\glitchhunter repair custom_ticket_shop_xxxx
```
The app is started for you (with a private database schema); you do not run it yourself. `upload` prints the exact scenario id.

## In CI (idea, not set up here)
`scan` exits 1 when it finds a violation, so a pipeline step such as `.\glitchhunter scan wallet --trials 100` fails the build when a change introduces a race. This needs a throwaway PostgreSQL and the app started in the pipeline, and it needs at least one approved check stored for the scenario.

## AI model and fallback
Gemini models are tried in order; if all fail or the call takes longer than `LLM_BUDGET_S` (default 120 s in total) it falls back to local Ollama (`llama3.1`; disable with `LLM_OLLAMA_FALLBACK=0`). `checks --propose` prints which model answered, and warns when it was Ollama (weaker).
