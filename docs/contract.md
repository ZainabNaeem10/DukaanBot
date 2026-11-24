# Interface contract: backend <-> AI service

Owner: Zainab (defined). Ayesha builds the AI service to match it.
**Do not change field names or types without both of you agreeing.**

The backend (Node, port 3000) calls the AI service (Python/FastAPI, port 8000).
The catalog files in `catalog/*.json` are mounted read-only into both services at `/catalog`.

## POST /respond

Called once per customer message.

### Request

```json
{
  "store_id": "store_001",
  "conversation_id": "b6f1c2e0-...",
  "message": "ye red lawn suit M size mein hai?",
  "history": [
    { "role": "customer", "text": "assalam o alaikum" },
    { "role": "bot", "text": "Walaikum assalam! Kaise madad kar sakte hain?" }
  ]
}
```

- `history` holds up to the last 10 messages before the current one, oldest first.
- `role` is `"customer"` or `"bot"`.

### Response

```json
{
  "reply": "Ji, red Embroidered Lawn 3-Piece M size mein available hai. Price Rs. 5,800. Order karna chahenge?",
  "language": "roman_urdu",
  "intent": "product_question",
  "escalate": false,
  "escalate_reason": null,
  "order": null,
  "grounded": true
}
```

| Field | Type | Notes |
|---|---|---|
| `reply` | string | Text shown to the customer. Required. |
| `language` | string | `en`, `ur`, `roman_urdu` or `mixed` |
| `intent` | string | `product_question`, `policy`, `order`, `complaint`, `discount`, `bulk`, `other` |
| `escalate` | boolean | `true` means the seller must take over |
| `escalate_reason` | string or null | e.g. `complaint`, `refund`, `discount`, `bulk_order`, `low_confidence` |
| `order` | object or null | Only when the customer has confirmed items AND given name, address, phone |
| `grounded` | boolean | `true` if the grounding check passed for every price/size/stock claim |

### Order object

```json
{
  "items": [{ "sku": "CTN-001", "size": "M", "color": "White", "qty": 2 }],
  "name": "Ali Raza",
  "address": "House 12, Street 4, F-8, Islamabad",
  "phone": "03001234567"
}
```

`sku` must exist in the store catalog. The backend looks up name and price from the database.

### Optional query parameters (for experiments)

- `POST /respond?rag=false`: plain-LLM baseline, no catalog records are given to the model
- `POST /respond?grounding=false`: skip the grounding check
- `grounded` is `true` only when the check ran and passed (or the reply was built directly from catalog data); it is `false` when the check was skipped

## POST /reindex

Reload the catalog files and rebuild the retrieval index (and embeddings). No body. Returns `{"status": "ok", ...}`.

## GET /health

Returns `{"status": "ok", ...}` plus whether an LLM key is set and the last LLM error.

## GET /llm/test

Makes one tiny live call to the LLM and the embedding API and reports any error (wrong key, wrong model name, quota).

## Rules

1. The AI service never talks to MongoDB. All data it needs is in the request and in `/catalog`.
2. If the AI service is down or returns an error, the backend replies with a fallback message and flags the chat for the seller.
3. The backend timeout is 30 seconds per `/respond` call.
