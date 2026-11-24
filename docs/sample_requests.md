# Sample requests

Replace `localhost` if you run on another machine.

## Backend (what the chat page calls)

```bash
# Health
curl http://localhost:3000/health

# Chat: ordinary message (new conversation)
curl -X POST http://localhost:3000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"store_id":"store_001","message":"ye red lawn suit M size mein hai?"}'

# Chat: continue a conversation (use the conversation_id from the previous reply)
curl -X POST http://localhost:3000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"store_id":"store_001","conversation_id":"PASTE_ID_HERE","message":"haan 2 bhej dein"}'

# Orders and escalated chats
curl http://localhost:3000/api/orders
curl "http://localhost:3000/api/conversations?escalated=true"

# Catalog
curl http://localhost:3000/api/catalog/store_001
curl -X POST http://localhost:3000/api/catalog/reload
```

## AI service directly (what the backend calls)

```bash
curl http://localhost:8000/health

curl -X POST http://localhost:8000/respond \
  -H "Content-Type: application/json" \
  -d '{"store_id":"store_001","conversation_id":"test-1","message":"price kya hai?","history":[]}'

curl -X POST http://localhost:8000/reindex
```

## Stub-only triggers

While the AI service is still the stub:

- A message containing `order` returns a sample order (tests order saving).
- A message containing `refund`, `complaint`, `shikayat` or `wapis` returns `escalate: true` (tests escalation).
- Anything else echoes the message.
