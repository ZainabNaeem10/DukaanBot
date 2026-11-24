# Windows quickstart (Command Prompt)

All commands are for **Command Prompt (cmd)**, not PowerShell.

## 0. Install once

1. **Docker Desktop** (turn on the WSL 2 option when asked), then restart and start Docker Desktop. Check: `docker --version` and `docker compose version`
2. **Git**: `git --version`
3. **Python 3.8+** (only for the test runner): `python --version`
4. **ngrok** (only for WhatsApp): sign up at ngrok.com and install it

## 1. Unzip and start

```
cd %USERPROFILE%\Downloads
tar -xf dukaanbot-starter.zip
cd dukaanbot
copy .env.example .env
docker compose up --build
```

The first build takes a few minutes. Leave this window open. When you see `Backend listening on port 3000`, open:

1. Chat page: http://localhost:3000
2. Seller view: http://localhost:3000/admin.html
3. AI service docs: http://localhost:8000/docs

Open a **second** Command Prompt window for the commands below, and `cd` into the `dukaanbot` folder there.

## 2. Check that everything works

In the chat page, send these messages (the AI service answers from the catalog even without an API key):

1. `red lawn suit M size mein hai?` (answers from the catalog: price and stock)
2. `red wala lawn suit large mein milega?` (says L is out of stock)
3. `mujhe refund chahiye` (the chat shows "seller has been notified", and it appears in the seller view)
4. For a full order, you need the free Groq key below: tell the bot an item, then your name, address and phone.

From the command line (note the escaped quotes, which cmd needs):

```
curl http://localhost:3000/health
curl -X POST http://localhost:3000/api/chat -H "Content-Type: application/json" -d "{\"store_id\":\"store_002\",\"message\":\"I want to order\"}"
curl http://localhost:3000/api/orders
curl "http://localhost:3000/api/conversations?escalated=true"
curl http://localhost:8000/health
```

## 2b. Turn on the LLM (free Groq key)

1. Open https://console.groq.com/keys, sign up, and create an API key (no card needed).
2. Edit `.env` (`notepad .env`): set `LLM_PROVIDER=groq` and `LLM_API_KEY=` your key. Leave `LLM_MODEL` and `EMBED_MODEL` empty.
3. Apply it: `docker compose up -d --force-recreate`
4. Check it: open http://localhost:8000/llm/test. `generate_ok` should be `true`. `embed_ok` is `null` with Groq, which is expected (keyword search is used instead).
5. "model not found" or "decommissioned": pick a current model from https://console.groq.com/docs/models and put it in `LLM_MODEL`, then repeat step 3.

## 3. Run the test set

```
python tests\run_tests.py
```

Results go to `tests\results.json`. For the report's comparison, also run:

```
python tests\run_tests.py --no-rag --no-grounding --out tests\results_baseline.json
python tests\run_tests.py --no-grounding --out tests\results_no_grounding.json
```

Offline unit tests (no key needed):

```
docker compose run --rm ai-service python -m unittest discover -s tests -v
```

## 4. Everyday commands

```
docker compose up --build         start (rebuild after code changes)
docker compose up -d              start in the background
docker compose logs backend       see backend output
docker compose logs ai-service    see AI service output
docker compose down               stop
docker compose down -v            stop and delete the database (fresh start)
docker compose up -d --force-recreate    apply changes made in .env
```

## 5. Put it on GitHub (so Ayesha can pull it)

Create an empty repo on github.com first (no README), then:

```
git init
git add .
git commit -m "Initial DukaanBot starter"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/dukaanbot.git
git push -u origin main
```

`.env` is ignored by git, so keys are not uploaded. Add Ayesha as a collaborator in the repo settings. She then runs:

```
git clone https://github.com/YOUR-USERNAME/dukaanbot.git
cd dukaanbot
copy .env.example .env
docker compose up --build
```

## 6. WhatsApp (optional; the web chat works without it)

1. Go to developers.facebook.com, create an app, and add the **WhatsApp** product. Under **API setup** you get a test phone number, its **Phone number ID**, and a temporary **access token**. Add your own phone number as a recipient there.
2. Edit `.env` and fill in `WHATSAPP_VERIFY_TOKEN` (any secret you invent), `WHATSAPP_TOKEN` and `WHATSAPP_PHONE_NUMBER_ID`. Then run `docker compose up -d --force-recreate`.
3. Expose your backend to the internet. In a new cmd window: `ngrok http 3000`. Copy the `https://....ngrok-free.app` address.
4. In Meta's **WhatsApp > Configuration**, set the callback URL to `https://YOUR-ADDRESS.ngrok-free.app/webhook` and the verify token to the same string as in `.env`, then subscribe to the **messages** field.
5. Send a WhatsApp message to the test number. Watch `docker compose logs backend` if nothing comes back.

Things to check in Meta's current docs, because they change: how long the test token lasts, how many recipients the test number allows, and the current Graph API version (set `WHATSAPP_API_VERSION`). The ngrok address changes each time you restart ngrok, so update the callback URL when it does.

## Troubleshooting

1. **`docker` is not recognized:** Docker Desktop is not installed or not running. Start it and open a new cmd window.
2. **Port already in use (3000 or 8000):** close whatever uses it, or change the left-hand port number in `docker-compose.yml` (for example `"3001:3000"`).
3. **Backend keeps restarting:** run `docker compose logs backend`. A MongoDB connection error right at startup usually fixes itself on the next restart.
4. **Chat page shows "Could not reach the server":** the backend container is not running. Run `docker compose ps`.
