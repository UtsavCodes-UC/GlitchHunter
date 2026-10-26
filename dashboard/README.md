# GlitchHunter dashboard

Next.js (App Router) + TypeScript. Shows the loop for each scenario: propose rules, filter, attack, explain the failing run, repair.
All data shapes follow `docs/contracts.md`.

## Run

```powershell
cd dashboard
npm install
copy .env.local.example .env.local
npm run dev
```

Open http://localhost:3000.

## Mock data or live data

`.env.local` controls the data source (no secrets in it):

- `NEXT_PUBLIC_USE_MOCK=true` uses `mock/*.json`. A yellow banner says so on every page. The numbers in the mock files are placeholders, not results.
- `NEXT_PUBLIC_USE_MOCK=false` calls the orchestrator at `NEXT_PUBLIC_API_URL` (default `http://127.0.0.1:9000`). Restart `npm run dev` after changing it.

Live mode needs, from the repo root:
1. `GH_DATABASE_URL` set, and the target app running in vulnerable mode (see `apps/README.md`).
2. The API: `python -m uvicorn orchestrator.api:app --port 9000`

## Pages

- `/` scenarios and the five stage statuses
- `/scenarios/<id>` overview with a button per stage
- `/scenarios/<id>/invariants` rules, filter results, Approve / Reject
- `/scenarios/<id>/attack` summary, timeline of the overlapping requests, plain-words explanation
- `/scenarios/<id>/repair` fix attempts with validation results, accepted / rejected, and the negative control

The last attack and repair result are kept in sessionStorage because the API does not store them.

## Wording rules
A fix is "validated by rerunning the failing run and N fresh trials", never "proven". AI-proposed rules are marked as needing human approval. Every number on screen comes from the API data.
