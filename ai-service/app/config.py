"""Settings, read from environment variables (see docker-compose.yml and .env)."""
import os


def _bool(name, default):
    v = os.getenv(name)
    return default if v is None or v.strip() == "" else v.strip().lower() in ("1", "true", "yes", "on")


CATALOG_DIR = os.getenv("CATALOG_DIR", "/catalog")
CACHE_DIR = os.getenv("CACHE_DIR", "/tmp/dukaanbot_cache")

# LLM provider:
#   groq    - GroqCloud free plan (no card), OpenAI-compatible API. No embeddings: retrieval is BM25 keyword search.
#   gemini  - Google AI Studio. Free tier is not available for every Google project (HTTP 403 "free tier is
#             not available for this project" means you would need billing).
#   openai  - any other OpenAI-compatible API (set LLM_BASE_URL), e.g. OpenRouter.
# Model names change often: if you get "model not found" or "decommissioned", pick a current model from the
# provider's model list and set LLM_MODEL.
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq").strip().lower() or "groq"
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
_DEFAULT_MODEL = {"gemini": "gemini-3.5-flash-lite", "groq": "openai/gpt-oss-120b"}
_DEFAULT_BASE = {"groq": "https://api.groq.com/openai/v1"}
_DEFAULT_EMBED = {"gemini": "gemini-embedding-001"}
LLM_MODEL = os.getenv("LLM_MODEL", "").strip() or _DEFAULT_MODEL.get(LLM_PROVIDER, "")
LLM_BASE_URL = (os.getenv("LLM_BASE_URL", "").strip() or _DEFAULT_BASE.get(LLM_PROVIDER, "")).rstrip("/")
# Empty EMBED_MODEL = no embeddings; retrieval then uses BM25 keyword search only.
EMBED_MODEL = os.getenv("EMBED_MODEL", "").strip() or _DEFAULT_EMBED.get(LLM_PROVIDER, "")
# gpt-oss models think before answering; "low" keeps that short (fewer tokens, fits free-plan limits).
LLM_REASONING_EFFORT = os.getenv("LLM_REASONING_EFFORT", "low")
LLM_TEMPERATURE = os.getenv("LLM_TEMPERATURE", "")  # empty = use the model default

TOP_K = int(os.getenv("TOP_K", "5"))
RAG_DEFAULT = _bool("RAG_ENABLED", True)
GROUNDING_DEFAULT = _bool("GROUNDING_ENABLED", True)
