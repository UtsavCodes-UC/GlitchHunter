"""One swappable LLM interface: complete(prompt) -> text. Provider chosen by LLM_PROVIDER (anthropic | gemini | ollama).
Keys come only from the environment (ANTHROPIC_API_KEY, GEMINI_API_KEY); nothing is printed or stored."""
import os, time, httpx

PROVIDER = os.environ.get("LLM_PROVIDER", "gemini")
MODEL = os.environ.get("LLM_MODEL", {"anthropic": "claude-sonnet-5-5", "gemini": "gemini-3.5-flash",
                                     "ollama": "llama3.1:latest"}.get(PROVIDER, ""))

FALLBACK_MODELS = [m for m in os.environ.get("LLM_FALLBACK_MODELS", "gemini-3-flash-preview,gemini-3.5-flash-lite").split(",") if m]
LAST_MODEL = MODEL  # the model that answered the most recent call (differs from MODEL after a fallback)

def complete(prompt, max_tokens=900):
    if PROVIDER == "anthropic":
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key: raise RuntimeError("ANTHROPIC_API_KEY is not set in this terminal")
        r = httpx.post("https://api.anthropic.com/v1/messages", timeout=120,
                       headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                       json={"model": MODEL, "max_tokens": max_tokens, "messages": [{"role": "user", "content": prompt}]})
        r.raise_for_status()
        return "".join(b.get("text", "") for b in r.json()["content"])
    if PROVIDER == "gemini":
        key = os.environ.get("GEMINI_API_KEY")
        if not key: raise RuntimeError("GEMINI_API_KEY is not set in this terminal")
        # 429 (free-tier quota, per model) / 503 (overload) are transient: retry briefly, then fall back to the next model.
        # Thinking tokens share the output budget, so allow more. LAST_MODEL records which model actually answered.
        global LAST_MODEL
        for m in [MODEL] + [x for x in FALLBACK_MODELS if x != MODEL]:
            for attempt in range(2):
                r = httpx.post(f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent", timeout=120,
                               headers={"x-goog-api-key": key},
                               json={"contents": [{"parts": [{"text": prompt}]}],
                                     "generationConfig": {"maxOutputTokens": max(max_tokens, 16384), "responseMimeType": "application/json"}})
                if r.status_code not in (429, 503): break
                time.sleep(3 * (attempt + 1))
            if r.status_code not in (429, 503): break
        r.raise_for_status(); LAST_MODEL = m
        return "".join(p.get("text", "") for p in r.json()["candidates"][0]["content"]["parts"])
    if PROVIDER == "ollama":
        r = httpx.post("http://localhost:11434/api/generate", timeout=240,
                       json={"model": MODEL, "prompt": prompt, "stream": False, "format": "json",
                             "options": {"temperature": 0.7, "num_predict": max_tokens}})
        r.raise_for_status()
        return r.json()["response"]
    raise ValueError(f"unknown LLM_PROVIDER {PROVIDER}")
