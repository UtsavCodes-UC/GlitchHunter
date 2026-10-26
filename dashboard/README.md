# GlitchHunter Dashboard

The dashboard is a Next.js client for the GlitchHunter orchestrator API. The
mock responses make it possible to develop the dashboard before the
orchestrator endpoints are available.

## Install

From this directory, install the project dependencies:

```bash
npm install
```

## Run the development server

```bash
npm run dev
```

Then open `http://localhost:3000`.

## Choose mock data or the live API

Create a `.env.local` file in the `dashboard/` directory.

To use the bundled mock JSON files:

```env
NEXT_PUBLIC_USE_MOCK=true
```

To call the live orchestrator API, set the flag to `false` and provide its
base URL:

```env
NEXT_PUBLIC_USE_MOCK=false
NEXT_PUBLIC_API_URL=http://127.0.0.1:9000
```

When `NEXT_PUBLIC_API_URL` is omitted, the API layer falls back to
`http://127.0.0.1:9000`. Restart the development server after changing
`.env.local`.
