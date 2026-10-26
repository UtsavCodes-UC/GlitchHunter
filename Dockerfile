# Backend: the API plus the demo apps (wallet, inventory) in one container. Build context: the repo root.
# The dashboard has its own image: dashboard/Dockerfile.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY apps ./apps
COPY controller ./controller
COPY orchestrator ./orchestrator
COPY cli ./cli
COPY deploy ./deploy
COPY gh.example.yml ./

# run as an unprivileged user; runs/ is where results are saved (temporary disk on Render unless you add a persistent disk)
RUN useradd --create-home app && mkdir -p runs && chown -R app:app /app
USER app

# Defaults for a public deployment: uploading your own code is OFF (it runs uploaded code on the server), no local Ollama
ENV PORT=10000 GH_DISABLE_UPLOADS=1 LLM_OLLAMA_FALLBACK=0
EXPOSE 10000
CMD ["python", "deploy/start.py"]
