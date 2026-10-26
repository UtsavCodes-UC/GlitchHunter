# GlitchHunter command line

Runs in the VS Code integrated terminal (PowerShell) from the repo root. No extra packages: it uses the same code as the API and dashboard, and shares the same stored checks (`runs/state/`), so what you approve in the CLI also shows in the dashboard.

```powershell
.\glitchhunter <command> ...        # or: python -m cli <command> ...
```

Needs `GH_DATABASE_URL` (for example `postgresql://rh:rh@localhost:5432/rh`). The AI steps need `GEMINI_API_KEY` (or a running Ollama; see below). Colour only appears in a real terminal; set `NO_COLOR=1` to turn it off.

If the ✔ / ✖ symbols look garbled (for example when you redirect output to a file in Windows PowerShell 5.1), set `GH_ASCII=1` for plain `[ok]` / `[x]`.

## Running the demo in two terminals
| Terminal | Command | What it starts |
|---|---|---|
| 1 | `.\glitchhunter serve` | buggy wallet (8000), inventory (8001), fixed wallet (8010, for the red/green test), and the API (9000), all in one window. Waits until each answers, prints the addresses, `Ctrl+C` stops all of them. Logs: `runs\logs\` |
| 2 | `.\glitchhunter ui` | the dashboard at http://localhost:3000. Production build (steadier for a demo), rebuilt only when the source or `dashboard\.env.local` changed. `--dev` gives hot reload instead |

- `serve` refuses to start if one of its ports is already used (it lists what holds it); add `--restart` to stop those leftovers first. It only stops processes that look like our servers (`uvicorn`, `next`, `node`) and leaves anything else alone.
- `.\glitchhunter stop` stops leftovers (and the test copies of uploaded apps); `stop --all` also stops the dashboard. Use it if a window was closed abruptly.
- `serve` does not start PostgreSQL or Ollama. Set `GEMINI_API_KEY` in terminal 1 (after `setx`, open a fresh terminal). `GH_DATABASE_URL` defaults to the local `rh` database.
- Options: `serve --no-fixed`, `serve --no-inventory`, `ui --restart`, `ui --rebuild`.

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
| `upload PATH [--name N]` | adds your own code (a .zip, a folder or one .py): it is only scanned, not run; prints the endpoints with hints |
| `setup ID [--config FILE]` | saves the setup (default: the suggested one) and tests it once in isolation, with a live log |
| `delete-project ID` | removes an uploaded project: files, database role and schema, results |
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

## Install it as a command (works from any folder)
From the repo root, once:
```powershell
python -m pip install -e .
```
This puts a `glitchhunter` command on your PATH (in the Python `Scripts` folder; if PowerShell says it is not recognised, add that folder to PATH, or use `python -m cli ...`). The install is *editable*: it points at this repo, so keep the repo where it is (the command reads its prompts and writes runs under `runs/`). To keep it out of your global Python, install it into a virtual environment: `python -m venv .venv; .venv\Scripts\activate; python -m pip install -e .`.
Set the database once per terminal (and `GEMINI_API_KEY` for the AI): `$env:GH_DATABASE_URL="postgresql://rh:rh@localhost:5432/rh"`. Then `glitchhunter doctor`.

## One command for the whole loop: `fix`
```powershell
glitchhunter fix C:\path\to\your\app            # read, set up, find the race, ask the AI for a fix, test it
glitchhunter fix C:\path\to\your\app --apply    # ... and write the accepted fix into your file (a .glitchhunter.bak copy is kept)
```
What it does: (1) reads the folder without running it, (2) saves a setup and tests it once in isolation, (3) asks the AI for checks and keeps the ones that survive the filter, (4) attacks with simultaneous requests, (5) if something goes wrong, asks the AI for a fix and tests it on a copy, (6) shows the change as a diff. It removes its temporary project afterwards (`--keep` leaves it, so you can open it in the dashboard).
- **It works on the source folder, not on a running server.** GlitchHunter starts its own isolated copy of your app against a private database account; the app you have open is not touched. So give it the folder, not a URL.
- **Setup:** it uses `glitchhunter.json` in the folder if there is one, else the scan's suggestion (`--endpoint "POST /withdraw"` picks another route). If the scan cannot guess your tables it stops and prints the JSON to fill in. Every folder in `samples/` already has a `glitchhunter.json`: `glitchhunter fix samples\01-bank-psycopg2`.
- **Exit codes:** 0 = no problem found, or a fix was accepted; 1 = a bug was found and no safe fix was accepted; 2 = setup problem.
- The fix replaces one function and is only as good as the checks; "accepted" is evidence, not proof. Read the diff before using `--apply`.

## Your own code
```powershell
.\glitchhunter upload samples\05-safe-shop          # scan only; prints the id, for example u1a2b3c4d5e6
.\glitchhunter setup u1a2b3c4d5e6
.\glitchhunter checks u1a2b3c4d5e6 --propose --filter --auto-approve
.\glitchhunter scan u1a2b3c4d5e6
.\glitchhunter repair u1a2b3c4d5e6
```
`setup` without `--config` uses the suggested setup from the scan. The app is started for you in isolation; you do not run it yourself. The database user needs `CREATEROLE` (see `docs/try_your_own_app.md`).

## In CI (idea, not set up here)
`scan` exits 1 when it finds a violation, so a pipeline step such as `.\glitchhunter scan wallet --trials 100` fails the build when a change introduces a race. This needs a throwaway PostgreSQL and the app started in the pipeline, and it needs at least one approved check stored for the scenario.

## AI model and fallback
Gemini models are tried in order; if all fail or the call takes longer than `LLM_BUDGET_S` (default 120 s in total) it falls back to local Ollama (`llama3.1`; disable with `LLM_OLLAMA_FALLBACK=0`). `checks --propose` prints which model answered, and warns when it was Ollama (weaker).
