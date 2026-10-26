"""One swappable LLM interface: complete(prompt) -> text. Provider chosen by LLM_PROVIDER (anthropic | gemini | ollama).
Keys come only from the environment (ANTHROPIC_API_KEY, GEMINI_API_KEY); nothing is printed or stored.
With the gemini provider: models are tried in order (LLM_MODEL, then LLM_FALLBACK_MODELS); if ALL of them fail with quota / overload /
timeout / network errors, the call falls back to local Ollama (disable with LLM_OLLAMA_FALLBACK=0). LAST_MODEL always says which model
actually answered, e.g. "gemini-3.5-flash-lite" or "ollama:llama3.1:latest", so results can be reported honestly."""
import os, time, httpx

PROVIDER = os.environ.get("LLM_PROVIDER", "gemini")
MODEL = os.environ.get("LLM_MODEL", {"anthropic": "claude-sonnet-5-5", "gemini": "gemini-3.5-flash",
                                     "ollama": "llama3.1:latest"}.get(PROVIDER, ""))
FALLBACK_MODELS = [m for m in os.environ.get("LLM_FALLBACK_MODELS", "gemini-3-flash-preview,gemini-3.5-flash-lite").split(",") if m]
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1:latest")
OLLAMA_FALLBACK = os.environ.get("LLM_OLLAMA_FALLBACK", "1") != "0"
BUDGET_S = float(os.environ.get("LLM_BUDGET_S", "120"))   # total seconds one complete() call may spend on Gemini before falling back
LAST_MODEL = MODEL  # the model that answered the most recent call (differs from MODEL after a fallback)

class Unavailable(Exception):
    """a provider could not answer for a transient reason (quota, overload, timeout, network); the next option may"""

def _anthropic(prompt, max_tokens):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key: raise RuntimeError("ANTHROPIC_API_KEY is not set in this terminal")
    r = httpx.post("https://api.anthropic.com/v1/messages", timeout=120,
                   headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                   json={"model": MODEL, "max_tokens": max_tokens, "messages": [{"role": "user", "content": prompt}]})
    r.raise_for_status()
    return "".join(b.get("text", "") for b in r.json()["content"]), MODEL

def _gemini(prompt, max_tokens):
    key = os.environ.get("GEMINI_API_KEY")
    if not key: raise Unavailable("GEMINI_API_KEY is not set in this terminal")
    last = "no model tried"; deadline = time.time() + BUDGET_S   # one slow model must not eat the whole request
    for m in [MODEL] + [x for x in FALLBACK_MODELS if x != MODEL]:
        for attempt in range(2):
            if time.time() > deadline: raise Unavailable(f"Gemini took longer than {BUDGET_S:.0f} s in total (last: {last})")
            try:  # a slow or hung response must not stall the whole request: cut it at 60 s and move on
                r = httpx.post(f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent", timeout=60,
                               headers={"x-goog-api-key": key},
                               json={"contents": [{"parts": [{"text": prompt}]}],
                                     # thinking tokens share the output budget, so allow plenty
                                     "generationConfig": {"maxOutputTokens": max(max_tokens, 16384), "responseMimeType": "application/json"}})
            except httpx.HTTPError as e:  # timeout / connection problem: no retry on this model
                last = f"{m}: {type(e).__name__}"; break
            if r.status_code in (429, 503):  # free-tier quota (per model) or overload: retry once, then next model
                last = f"{m}: HTTP {r.status_code}"; time.sleep(3 * (attempt + 1)); continue
            r.raise_for_status()
            return "".join(p.get("text", "") for p in r.json()["candidates"][0]["content"]["parts"]), m
    raise Unavailable(f"all Gemini models unavailable (last: {last})")

def _ollama(prompt, max_tokens):
    try:
        r = httpx.post(f"{OLLAMA_URL}/api/generate", timeout=240,
                       json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False, "format": "json",
                             "options": {"temperature": 0.7, "num_predict": max_tokens}})
    except httpx.HTTPError as e:
        raise Unavailable(f"Ollama not reachable at {OLLAMA_URL} ({type(e).__name__})")
    r.raise_for_status()
    return r.json()["response"], f"ollama:{OLLAMA_MODEL}"

def complete(prompt, max_tokens=900):
    global LAST_MODEL
    if PROVIDER == "anthropic": text, used = _anthropic(prompt, max_tokens)
    elif PROVIDER == "ollama": text, used = _ollama(prompt, max_tokens)
    elif PROVIDER == "gemini":
        try: text, used = _gemini(prompt, max_tokens)
        except Unavailable as e:
            if not OLLAMA_FALLBACK: raise RuntimeError(str(e))
            try: text, used = _ollama(prompt, max_tokens)
            except Unavailable as e2: raise RuntimeError(f"{e}; and the Ollama fallback failed: {e2}")
    else: raise ValueError(f"unknown LLM_PROVIDER {PROVIDER}")
    LAST_MODEL = used
    return text
