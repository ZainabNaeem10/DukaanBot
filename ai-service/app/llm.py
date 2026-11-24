"""
Thin LLM client with no SDK. Two API styles:
  - "gemini": Google AI Studio REST API (generateContent / embedContent)
  - "groq" / "openai": any OpenAI-compatible API (/chat/completions, /embeddings)

Everything here fails soft: on any error the functions return None and keep the
message in LAST_ERROR, so the pipeline can fall back to rule-based replies.
"""
import json
import re
import time
import urllib.error
import urllib.request

from . import config

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
LAST_ERROR = None


def available():
    return bool(config.LLM_API_KEY)


def _gemini():
    return config.LLM_PROVIDER == "gemini"


def _retry_wait(e, default):
    try:
        return min(30.0, float(e.headers.get("retry-after") or default))
    except (TypeError, ValueError):
        return default


def _post(url, body, headers, timeout=60, retries=2):
    global LAST_ERROR
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers=dict({"Content-Type": "application/json", "Accept": "application/json",
                                               # Cloudflare (in front of Groq) blocks Python's default
                                               # "Python-urllib" agent with "error code: 1010"
                                               "User-Agent": "dukaanbot/1.0 (course project)"}, **headers), method="POST")
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                LAST_ERROR = None
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:500]
            LAST_ERROR = "HTTP %s: %s" % (e.code, detail)
            if e.code in (429, 500, 502, 503) and attempt < retries:
                time.sleep(_retry_wait(e, 5 if e.code == 429 else 3))  # 429 = free-plan rate limit
                continue
            return None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            LAST_ERROR = "%s: %s" % (type(e).__name__, e)
            if attempt < retries:
                time.sleep(2)
                continue
            return None
    return None


def _gemini_post(path, body):
    return _post(GEMINI_BASE + path, body, {"x-goog-api-key": config.LLM_API_KEY}, retries=1)


def _openai_post(path, body):
    if not config.LLM_BASE_URL:
        global LAST_ERROR
        LAST_ERROR = "LLM_BASE_URL is empty (needed for LLM_PROVIDER=%s)" % config.LLM_PROVIDER
        return None
    return _post(config.LLM_BASE_URL + path, body, {"Authorization": "Bearer " + config.LLM_API_KEY})


def _extract_json(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except ValueError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except ValueError:
                pass
    return None


def _generate_text_gemini(system, prompt):
    global LAST_ERROR
    gen_cfg = {"responseMimeType": "application/json"}
    if config.LLM_TEMPERATURE:
        gen_cfg["temperature"] = float(config.LLM_TEMPERATURE)
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": gen_cfg,
    }
    data = _gemini_post("/models/%s:generateContent" % config.LLM_MODEL, body)
    if not data:
        return None
    try:
        return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
    except (KeyError, IndexError, TypeError):
        LAST_ERROR = "unexpected response: %s" % json.dumps(data)[:300]
        return None


def _generate_text_openai(system, prompt):
    global LAST_ERROR
    body = {
        "model": config.LLM_MODEL,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
    }
    if config.LLM_TEMPERATURE:
        body["temperature"] = float(config.LLM_TEMPERATURE)
    if config.LLM_REASONING_EFFORT and "gpt-oss" in config.LLM_MODEL:
        body["reasoning_effort"] = config.LLM_REASONING_EFFORT
    data = _openai_post("/chat/completions", body)
    if not data:
        return None
    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        LAST_ERROR = "unexpected response: %s" % json.dumps(data)[:300]
        return None


def generate_json(system, prompt):
    """Ask the model for a JSON object. Returns a dict or None."""
    global LAST_ERROR
    if not available():
        return None
    text = (_generate_text_gemini if _gemini() else _generate_text_openai)(system, prompt)
    if text is None:
        return None
    obj = _extract_json(text)
    if not isinstance(obj, dict):
        LAST_ERROR = "model did not return a JSON object: %s" % text[:200]
        return None
    return obj


def embeddings_on():
    return available() and bool(config.EMBED_MODEL)


def _embed_openai(texts):
    data = _openai_post("/embeddings", {"model": config.EMBED_MODEL, "input": texts})
    try:
        return [d["embedding"] for d in sorted(data["data"], key=lambda d: d["index"])]
    except (KeyError, TypeError):
        return None


def embed_documents(texts):
    """Embeddings for catalog chunks. Returns list of vectors or None."""
    if not embeddings_on() or not texts:
        return None
    vectors = []
    for i in range(0, len(texts), 50):
        batch = texts[i:i + 50]
        if _gemini():
            body = {"requests": [{
                "model": "models/%s" % config.EMBED_MODEL,
                "content": {"parts": [{"text": t}]},
                "taskType": "RETRIEVAL_DOCUMENT",
            } for t in batch]}
            data = _gemini_post("/models/%s:batchEmbedContents" % config.EMBED_MODEL, body)
            try:
                vectors += [e["values"] for e in data["embeddings"]]
            except (KeyError, TypeError):
                return None
        else:
            got = _embed_openai(batch)
            if not got:
                return None
            vectors += got
    return vectors if len(vectors) == len(texts) else None


def embed_query(text):
    if not embeddings_on():
        return None
    if not _gemini():
        got = _embed_openai([text])
        return got[0] if got else None
    body = {
        "model": "models/%s" % config.EMBED_MODEL,
        "content": {"parts": [{"text": text}]},
        "taskType": "RETRIEVAL_QUERY",
    }
    data = _gemini_post("/models/%s:embedContent" % config.EMBED_MODEL, body)
    try:
        return data["embedding"]["values"]
    except (KeyError, TypeError):
        return None


def check():
    """Small live test used by GET /llm/test."""
    out = {"provider": config.LLM_PROVIDER, "key_set": available(), "model": config.LLM_MODEL,
           "embed_model": config.EMBED_MODEL or None}
    if not available():
        out["error"] = "LLM_API_KEY is empty"
        return out
    r = generate_json("Reply with JSON only.", 'Return the JSON object {"ok": true}')
    out["generate_ok"] = bool(r)
    out["generate_error"] = None if r else LAST_ERROR
    if not config.EMBED_MODEL:
        out["embed_ok"] = None
        out["embed_note"] = "embeddings off: retrieval uses BM25 keyword search (normal for Groq)"
        return out
    v = embed_query("test")
    out["embed_ok"] = bool(v)
    out["embed_error"] = None if v else LAST_ERROR
    return out
