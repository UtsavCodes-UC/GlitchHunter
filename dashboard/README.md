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

- `/` what the tool does in three sentences, and a pick-an-example screen
- `/scenarios/<id>` one guided page in plain language:
  1. **See the bug**: simultaneous requests, "it went wrong in N of 50 tries", and one failed try told as a story (Person A, Person B, what each was told, why the result is wrong) plus a timeline
  2. **How does the app know it went wrong?**: AI-suggested "checks" in plain English; you choose which to use (technical details and SQL are behind "Why we trust it"); thrown-out checks are listed with the reason
  3. **Fix it, then prove the fix**: what the AI changed, a tick-list of how it was tested, earlier rejected attempts, and the note that the original buggy code was rejected by the same tests

- `/try` upload your own FastAPI + PostgreSQL app (live mode only): see `docs/try_your_own_app.md` for what it needs and its limits

Wording for each scenario lives in `lib/copy.ts`; add an entry there for a new scenario (a generic fallback is used otherwise).
The last attack and repair result are kept in sessionStorage because the API does not store them.

## Wording rules
A fix is "validated by rerunning the failing run and N fresh trials", never "proven". AI-proposed rules are marked as needing human approval. Every number on screen comes from the API data.
