# Backend: the API plus the demo apps (wallet, inventory) in one container. Build context: the repo root.
# The dashboard has its own image: dashboard/Dockerfile.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt ./
# the extra libraries are what uploaded projects may import (see docs/try_your_own_app.md)
RUN pip install -r requirements.txt pydantic sqlalchemy asyncpg "psycopg[binary]"

COPY apps ./apps
COPY controller ./controller
COPY orchestrator ./orchestrator
COPY cli ./cli
COPY deploy ./deploy
COPY gh.example.yml ./
RUN mkdir -p runs

# This container runs as ROOT on purpose: uploaded code is started through controller/sandbox.py, which then switches to the
# unprivileged user "nobody" (uid 65534) with resource limits, so it cannot read this process's environment (API keys, database URL).
# Set GH_DISABLE_UPLOADS=1 to turn the "Your own code" feature off.
ENV PORT=10000 LLM_OLLAMA_FALLBACK=0
EXPOSE 10000
CMD ["python", "deploy/start.py"]
