# DukaanBot

AI sales assistant for a Pakistani clothing seller. Customers chat in Roman Urdu, Urdu or English; the bot answers from the seller's catalog, takes orders, and hands over to the seller when needed.

This starter has three pieces:

1. `backend/`: Node.js + Express + MongoDB. Chat endpoint, saves conversations and orders, serves two simple pages.
2. `ai-service/`: Python + FastAPI. The GenAI pipeline (see below).
3. `catalog/`: JSON catalog files. `store_002.json` is the **real catalog**: 35 products, prices and delivery/return policies copied by hand from BATIK's public website (batik.com.pk, retrieved 23 Nov 2026; course demo, not affiliated). `store_001.json` is a fictional store (Noor Collection, 16 products) used for development. The chat page opens BATIK by default and has a store picker.

Contract between 1 and 2: `docs/contract.md`. Example requests: `docs/sample_requests.md`.

## Run it

Requires Docker. On Windows, follow `docs/windows-quickstart.md` (Command Prompt commands, GitHub setup, WhatsApp setup, troubleshooting).

Short version:

```
copy .env.example .env
docker compose up --build
```

Then open:

1. Chat page: http://localhost:3000
2. Seller view (orders and escalated chats): http://localhost:3000/admin.html
3. AI service docs: http://localhost:8000/docs

Try the chat page with: `red lawn suit M size mein hai?`, `kitne ka hai karandi shawl`, `mujhe refund chahiye` and `Assalam o alaikum`.

Run the test set against the AI service: `python tests\run_tests.py`

## Project layout

```
docker-compose.yml        runs mongo, ai-service, backend
catalog/                  store catalogs (shared, read-only, mounted into both services)
backend/src/              index.js, routes.js, chat.js, whatsapp.js, models.js, catalog.js
backend/public/           index.html (chat demo), admin.html (seller view)
ai-service/app/           GenAI pipeline (normalize, retrieval, llm, grounding, escalation, fallback)
ai-service/tests/         offline unit tests with a fake LLM
docs/contract.md          request/response format
tests/test_messages_batik.json  29 test messages for BATIK (the default)
tests/test_messages.json  40 test messages for the fictional store (use --store store_001)
tests/run_tests.py        runs the test messages against /respond and prints a report
```

## The AI service (GenAI pipeline)

`ai-service/app/` is a working first version of the GenAI pipeline. For each customer message:

1. `normalize.py`: Roman Urdu / Urdu / English normalization. Maps spelling variants (kia/kiya/kya, laal/red, joda/suit) to one form, detects the language, extracts size, color, quantity and SKU, and flags refund, discount, bulk and similar words. Includes fuzzy matching for typos.
2. `escalation.py` + `templates.py`: complaints, refunds, defects, delivery problems, discounts, bulk and custom orders are handed to the seller with a fixed polite reply in the customer's language. Greetings and thanks are answered without the LLM.
3. `retrieval.py`: RAG. Every product and store policy is a text chunk. Search uses BM25 word matching, with extra weight on product-name matches. With an embedding model (Gemini, or any OpenAI-compatible embeddings API) it becomes hybrid search (BM25 + embeddings). With Groq, which has no embeddings, it is BM25 only.
4. `pipeline.py` + `llm.py`: the retrieved records go to the LLM (default: openai/gpt-oss-120b on Groq's free plan; Gemini also supported) with strict rules (answer only from the records, reply in the customer's language style, return JSON with the reply, intent, the facts it claims, and the order if complete).
5. `grounding.py`: the grounding check. Every price, size, stock and color claim is compared with the catalog by plain code, and every large number in the reply must be a real price, charge or total. On failure the model gets the reasons and one retry; if it still fails, a rule-based answer built directly from the catalog is sent instead. Orders are validated (items exist, size in stock, name, address, phone) before they reach the backend.
6. `fallback.py`: rule-based answers from catalog data, used when there is no API key, the LLM fails, or the check fails twice.

### Get a free LLM API key (Groq)

The default provider is Groq's free plan: no credit card, OpenAI-compatible API.

1. Go to https://console.groq.com/keys, sign up, and create an API key.
2. In `.env` set `LLM_PROVIDER=groq` and `LLM_API_KEY=your-key`. Leave `LLM_MODEL` empty for the default (`openai/gpt-oss-120b`).
3. Apply the change: `docker compose up -d --force-recreate`.
4. Check it: open http://localhost:8000/llm/test. `generate_ok` should be true. `embed_ok` is `null` with Groq, because Groq has no embeddings and retrieval uses keyword search.
5. If you get "model not found" or "decommissioned", pick a current model from https://console.groq.com/docs/models and set `LLM_MODEL`.

The free plan has per-minute and per-day limits (see https://console.groq.com/settings/limits). When a limit is hit the API returns HTTP 429; the service waits and retries, and if it still fails the rule-based fallback answers. Run the test set with `--delay 3` if you see many 429s. Never commit your key.

Gemini is still supported (`LLM_PROVIDER=gemini`, `LLM_MODEL=gemini-3.5-flash-lite`, `EMBED_MODEL=gemini-embedding-001`), but Google's free tier is not available for every project: HTTP 403 "free tier is not available for this project" means that project needs billing.

### Tests and experiments

1. Offline unit tests (no key or internet needed; they use a fake LLM): `docker compose run --rm ai-service python -m unittest discover -s tests -v`
2. The test messages against the running service: `python tests\run_tests.py` (BATIK, 29 messages) or `python tests\run_tests.py --store store_001` (fictional store, 40 messages)
3. Experiments for the report:
   - Full pipeline: `python tests\run_tests.py --out tests\results_full.json`
   - Plain-LLM baseline (no RAG, no grounding): `python tests\run_tests.py --no-rag --no-grounding --out tests\results_baseline.json`
   - RAG without the grounding check: `python tests\run_tests.py --no-grounding --out tests\results_no_grounding.json`
4. Without an API key, the rule-based fallback answers the 40 messages (about 92% intent and 98% escalation accuracy in our check, but with plain wording and no real order extraction). With a key, the LLM handles the rest.

### What the next person improves

1. Add more Roman Urdu and mixed-language test messages, and grow the lexicon in `normalize.py` from the messages the bot misreads.
2. Tune the prompt in `pipeline.py` and compare models.
3. Read the replies against the `facts` column in the test file (the runner cannot judge wording).
4. Write up the three experiments above as the evaluation.

## Handoff checklist (Phase 1 done when all are true)

- [ ] `docker compose up --build` works on both machines
- [ ] Chat page and seller view load; order and escalation paths work with the stub
- [ ] Catalog and test messages are in the repo
- [ ] Contract in `docs/contract.md` agreed by both
- [ ] 30-minute walkthrough done

## How the real BATIK catalog is handled

BATIK publishes less than the fictional store, so the AI service handles three extra cases (see `ai-service/app/catalog.py`):

- **Sale prices**: the customer pays the sale price; the regular price can be mentioned ("Rs. 11,193, sale, regular Rs. 15,990").
- **Sold out**: 9 products are sold out. The bot says so and never takes an order for them.
- **Details not captured**: 31 of 35 products have only a name and price (sizes, colors and fabric were captured for Edinaa, Amiraa, Aquamarine and Kara). For these the bot gives the price and hands size/color questions to the seller (escalation reason `details_not_listed`); the grounding check rejects any reply that confirms a size or color for them.
- **No stock counts**: BATIK shows only "available" or "sold out", so any quantity of an available size is accepted.

To add details for more products, copy sizes, colors and fabric from the product page into `catalog/store_002.json`, set `"details_verified": true`, and reload the catalog (`POST http://localhost:3000/api/catalog/reload`, or restart).

The test messages in `tests/test_messages_batik.json` were written by us (field `"source": "written"`). To answer the "real data" feedback fully, add real public customer questions (from product Q&A or brand page comments, anonymized) with `"source": "real"`.
