# Deploy on Render (Docker + Blueprint)

Files: `render.yaml` (database + two web services), `Dockerfile` (backend: API + demo apps, built from the repo root), `dashboard/Dockerfile` (Next.js), `deploy/start.py` (container entry point), `.dockerignore` files.
**None of this has been built or run on Render or with Docker yet** (no Docker on the machine where it was written). Expect to fix small things on the first deploy.

## Steps
1. Push the repo to GitHub (a private repo is fine; Render asks for access).
2. Render Dashboard > **New > Blueprint** > choose the repo. Render reads `render.yaml` and proposes: `glitchhunter-db` (PostgreSQL), `glitchhunter-api`, `glitchhunter-web`.
3. When asked for `GEMINI_API_KEY`, paste your key (it is marked `sync: false`, so it never lives in the repo). Apply.
4. Wait for the three resources to deploy. The API logs should show `started api on 0.0.0.0:...` and the three demo apps.
5. Check the public URLs:
   - API: `https://glitchhunter-api.onrender.com/health` should return `{"ok": true, ...}`.
   - Dashboard: `https://glitchhunter-web.onrender.com`.
6. **If the two URLs are not exactly those** (the name was taken, so Render added a suffix), edit `render.yaml`: `GH_CORS_ORIGINS` (the dashboard's URL) and `NEXT_PUBLIC_API_URL` (the API's URL), push, and redeploy the dashboard. `NEXT_PUBLIC_API_URL` is compiled into the page at build time, so changing it later needs a rebuild.

## What is configured
- The backend container runs the wallet (8000), inventory (8001) and fixed wallet (8010) demo apps on localhost and the API on `$PORT`. If any of them stops, the container exits and Render restarts it.
- `GH_DATABASE_URL` comes from the database's internal connection string (the database accepts only internal connections: `ipAllowList: []`).
- **Uploading your own code is ON for everyone** (`GH_DISABLE_UPLOADS=0`), exactly like localhost. The API has no login, so **anyone with the URL can run code on this server**. The container runs as root so that uploaded code can be started as the unprivileged user `nobody` with resource limits and no access to the API's environment; outbound network access is not restricted. This Linux sandbox has NOT been tested. To switch the feature off, set `GH_DISABLE_UPLOADS` to `1` in `render.yaml` (or in the service's environment) and redeploy.
- **It needs `CREATEROLE`:** each uploaded project gets its own database role. If Render's database user cannot create roles, "Save and test the setup" fails with a message saying so; the demos still work. Roles cannot be granted on Render's managed database by you, so this may simply not work there.
- Free plans have 512 MB of memory shared by the API, the three demo apps and any uploaded app: an upload may be killed or may restart the container.
- No local Ollama on Render (`LLM_OLLAMA_FALLBACK=0`): when Gemini's quota runs out, AI steps fail instead of falling back.
- `runs/` (saved attacks, checks) lives on the container's temporary disk and is lost on every deploy or restart; add a persistent disk mounted at `/app/runs` if that matters.

## Costs and plans
`render.yaml` uses the **free** plans for all three resources (no card needed). Free web services sleep after about 15 minutes idle (the first request then takes about a minute), have 512 MB of memory (shared by the API, the three demo apps and any uploaded app), and the free PostgreSQL is deleted after 30 days. For more memory or no sleeping, add a payment method under Billing and change `plan:` (web: `starter` 512 MB, `standard` 2 GB; database: `basic-256mb`). Render refuses a paid plan with "Plan requires payment information on file" until a card is saved. Credits are shown under the workspace's Billing page.

## Quick local check of the images (needs Docker)
```
docker build -t gh-api .
docker build -t gh-web --build-arg NEXT_PUBLIC_API_URL=http://localhost:10000 dashboard
```
