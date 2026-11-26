"""
The DukaanBot pipeline for one customer message:

  normalize -> (greeting / escalation rules) -> retrieve (RAG) -> LLM -> grounding check -> reply

Switches for experiments:  rag=False  gives the "plain LLM" baseline (no catalog records),
grounding=False skips the verification step.
"""
import json
import re

from . import catalog, config, escalation, fallback, grounding, llm, normalize, retrieval, templates

INTENTS = {"product_question", "policy", "order", "complaint", "discount", "bulk", "other"}
LANGS = {"en", "ur", "roman_urdu", "mixed"}

SYSTEM = """You are DukaanBot, the WhatsApp sales assistant of a small Pakistani clothing store.
Reply to the customer's latest message.

RULES
1. Use ONLY the facts in RECORDS (products, prices, sizes, stock, policies). Never invent a product, price, size, color, stock level or policy. If the customer asks for a kind of item the store clearly does not sell (nothing like it in RECORDS), say it is not in the catalog and set needs_seller to false. If the answer is not in RECORDS and only the seller could know it (for example the shop address, a restock date, a size guide, or how a colour looks in real life), say so and set needs_seller to true. If the customer does not say which product they mean ("this", "yeh suit", "price please" — they are looking at a photo you cannot see), ask them which product (its name) and set needs_seller to false.
Never state an order's status (processed, shipped, delayed): you cannot see orders. For "where is my order" hand over to the seller.
2. A size with 0 stock (or marked "out of stock") is out of stock: say so. A size or color that is not listed does not exist: say so. A product marked SOLD OUT cannot be ordered: say it is sold out and, if useful, suggest a similar available product from RECORDS.
2b. If a product says its sizes/colors are NOT LISTED, do not confirm or deny any size or color for it: give the price, say the seller will confirm the size/color, and set needs_seller to true with reason "details_not_listed". Never put such a product in "order". This applies ONLY when the customer is asking about or ordering that product; other products in RECORDS being NOT LISTED is not a reason to set needs_seller.
2d. When the customer sends their name, address and phone, the item they want is the one from the CONVERSATION SO FAR: complete that order.
2e. When you confirm a product is available, also give its price.
2f. A number used with chahiye / chahiyen / dein / bhej dein / "I want" / "I need" is a QUANTITY ("Edinaa 2 chahiye" = 2 Edinaa dresses). Only "2Pc", "2 piece" or "3 piece" means the number of pieces in the outfit.
2g. If you ask the customer a question to clarify (which product, size, quantity), set needs_seller to false: the customer answers you, not the seller.
2h. The CATALOG INDEX, when present, lists every product's name, price and availability. Customers may write a product name in Urdu script or with a different spelling; match it to the index before saying a product is not in the catalog.
2c. If a record shows a sale price and a regular price, the customer pays the sale price; you may mention the regular price.
3. Write the reply in the customer's language style: Roman Urdu (Latin letters) if they wrote Roman Urdu, Urdu script if they wrote Urdu script, English if they wrote English, a natural mix if they mixed. Keep it short (1 to 3 sentences), polite and friendly. Write prices as Rs. 5,800.
4. If the customer wants to order, ask for what is missing: which item, size and color (if the item has them), quantity, and their name, delivery address and phone number. Fill "order" ONLY when the customer has clearly chosen the items AND has given name, address and phone. Otherwise "order" must be null.
5. "claims" must list EVERY price, size, color or stock fact you state in the reply, one entry per fact: {"sku", "size", "color", "in_stock", "price"} (use null for fields you did not state). Use the SKU codes from RECORDS. "price" is a plain number (11193, not "Rs. 11,193"). For something the product does NOT have or is out of ("doesn't come in red", "no XXL", "sold out"), set "in_stock": false. Store policy facts (delivery, payment, exchange) are not claims: leave them out of "claims".
6. Never promise discounts, refunds, delivery dates not in the policies, or anything else not in RECORDS.

Return ONLY a JSON object with exactly these keys:
{"reply": string, "language": "en"|"ur"|"roman_urdu"|"mixed",
 "intent": "product_question"|"policy"|"order"|"other",
 "claims": [ ... ],
 "order": null | {"items": [{"sku": string, "size": string|null, "color": string|null, "qty": integer}], "name": string, "address": string, "phone": string},
 "needs_seller": boolean, "needs_seller_reason": string|null}"""


def _resp(reply, language, intent, escalate=False, reason=None, order=None, grounded=True):
    return {"reply": reply, "language": language if language in LANGS else "en",
            "intent": intent if intent in INTENTS else "other", "escalate": escalate,
            "escalate_reason": reason, "order": order, "grounded": grounded}


_PHONE_IN_TEXT = re.compile(r"(?:\+?92|0)3\d{2}[\s-]?\d{7}")


def _build_query(n, history):
    """Follow-ups borrow words from the conversation so the right product is retrieved:
    short messages ("Embroidered wala") use the previous customer message, and a message with
    contact details (completing an order) also uses the bot's last reply, which names the item."""
    query = n["normalized"]
    contact = bool(_PHONE_IN_TEXT.search(n["original"]))
    if len(n["tokens"]) < 5 or contact:
        prev = [h for h in history if h.get("role") == "customer"]
        if prev:
            query = normalize.normalize(prev[-1]["text"])["normalized"] + " " + query
        if contact:
            bot = [h for h in history if h.get("role") == "bot"]
            if bot:
                query = normalize.normalize(bot[-1]["text"])["normalized"] + " " + query
    return query


_DETAIL_WORDS = {"size", "sizes", "color", "colour", "colors", "rang", "clr", "fabric", "kapra", "stuff", "shade"}


def _needs_seller(store, result, n=None):
    """Keep the model's handover, except a "details_not_listed" handover when no product the reply is
    about (claims or order) actually lacks details: the model sometimes applies that rule just because
    other records in the list are NOT LISTED."""
    if not result["needs_seller"]:
        return False, None
    reason = result["needs_seller_reason"] or "low_confidence"
    low = reason.lower()
    # The bot handles these itself: it asked the customer a question, or the item is simply not sold.
    if any(w in low for w in ("clarif", "not_in_catalog", "not in catalog", "not_in_the_catalog")):
        return False, None
    skus = [str(c.get("sku") or "").upper() for c in result["claims"] if isinstance(c, dict)]
    skus += [it["sku"] for it in (result["order"] or {}).get("items", [])]
    products = [store["products"].get(s) for s in skus if store["products"].get(s)]
    products += _named_products(store, n)
    if "not_listed" in reason or "not listed" in low or "detail" in low:
        # Only a real handover if the customer asked about size/colour/fabric of a product whose details
        # we do not have. A plain price question ("Joy kitne ka hai") or no product at all is not one.
        asked_details = n is None or bool(n["slots"]["sizes"] or n["slots"]["colors"]
                                          or set(n["tokens"]) & _DETAIL_WORDS)
        if not products or not asked_details or all(p["details_known"] and p["available"] for p in products):
            return False, None
        reason = "details_not_listed"
    elif not products and "?" in result["reply"]:
        # No product identified and the reply asks the customer something ("which product?"): the customer
        # answers the bot, not the seller. Seller-only topics never reach here (rules hand them over first).
        return False, None
    return True, reason


_GENERIC_NAME_WORDS = {"3pc", "2pc", "1pc", "embroidered", "printed", "lawn", "dress", "pret", "luxe", "casual",
                       "festive", "eid", "prints", "solid", "farshi", "shalwar", "the"}


def _named_products(store, n):
    """Products whose distinctive name word ("mavi", "edinaa") appears in the customer's message."""
    if n is None:
        return []
    toks = set(n["tokens"])
    out = []
    for p in store["products"].values():
        words = {w.lower() for w in re.findall(r"[A-Za-z]+", p["name"])} - _GENERIC_NAME_WORDS
        if any(len(w) >= 3 and w in toks for w in words):
            out.append(p)
    return out


def _add_price(store, result, reason, n=None):
    """When a product with unlisted details is handed over, the reply should still give its price."""
    if reason != "details_not_listed":
        return result["reply"]
    reply = result["reply"]
    candidates = [store["products"].get(str(c.get("sku") or "").upper()) for c in result["claims"] if isinstance(c, dict)]
    for p in [c for c in candidates if c] + _named_products(store, n):
        if p["available"] and "{:,}".format(p["price"]) not in reply and str(p["price"]) not in reply:
            return reply.rstrip() + " Price: Rs. {:,}.".format(p["price"])
    return reply


def _catalog_index(store):
    """One short line per product. Sent for Urdu-script messages, where keyword search cannot match
    English product names ("ایڈینا" vs "Edinaa"), so the LLM can match the name itself."""
    lines = ["CATALOG INDEX (all products; full details only in the records above)"]
    for p in store["products"].values():
        lines.append("- [%s] %s, Rs. %s, %s" % (p["sku"], p["name"], p["price"],
                                                "available" if p["available"] else "SOLD OUT"))
    return "\n".join(lines)


def _records_text(store, retrieved, n=None):
    lines = ["STORE: %s (%s)" % (store["name"], store["city"])]
    for c in retrieved["chunks"]:
        lines.append("- [%s] %s" % (c.get("sku") or c["id"], c["text"]))
    if n is not None and n["language"] == "ur":
        lines.append(_catalog_index(store))
    return "\n".join(lines)


def _prompt(store, n, history, retrieved, rag, feedback=None):
    hist = "\n".join("%s: %s" % (h["role"], h["text"]) for h in history[-6:]) or "(none)"
    records = _records_text(store, retrieved, n) if rag else "(no catalog records are available)"
    text = "RECORDS\n%s\n\nCONVERSATION SO FAR\n%s\n\nCUSTOMER MESSAGE (language detected: %s)\n%s\n" % (
        records, hist, n["language"], n["original"])
    if feedback:
        text += ("\nYour previous answer was rejected by the fact checker for these reasons:\n- " +
                 "\n- ".join(feedback) + "\nWrite a corrected answer using ONLY the RECORDS. Fix only what was "
                 "rejected and keep every correct fact from your previous answer, especially the product's "
                 "price.\n")
    return text


def _clean(result):
    """Make the model output safe to use: right types, known keys."""
    if not isinstance(result.get("reply"), str) or not result["reply"].strip():
        return None
    order = result.get("order")
    if isinstance(order, dict):
        items = []
        for it in order.get("items") or []:
            if isinstance(it, dict) and it.get("sku"):
                try:
                    qty = max(1, int(it.get("qty") or 1))
                except (TypeError, ValueError):
                    qty = 1
                items.append({"sku": str(it["sku"]).upper(), "size": it.get("size"),
                              "color": it.get("color"), "qty": qty})
        order = {"items": items, "name": order.get("name"), "address": order.get("address"),
                 "phone": order.get("phone")}
    else:
        order = None
    claims = result.get("claims") if isinstance(result.get("claims"), list) else []
    return {"reply": result["reply"].strip(), "language": result.get("language"),
            "intent": result.get("intent"), "claims": claims, "order": order,
            "needs_seller": bool(result.get("needs_seller")),
            "needs_seller_reason": result.get("needs_seller_reason")}


def _generate(store, n, history, retrieved, rag, feedback=None):
    raw = llm.generate_json(SYSTEM, _prompt(store, n, history, retrieved, rag, feedback))
    return _clean(raw) if raw else None


def _problems(store, result):
    problems = grounding.verify(store, result)
    if result.get("order"):
        problems += grounding.validate_order(store, result["order"])
    return problems


def respond(store_id, conversation_id, message, history=None, rag=None, grounding_on=None):
    history = history or []
    rag = config.RAG_DEFAULT if rag is None else rag
    grounding_on = config.GROUNDING_DEFAULT if grounding_on is None else grounding_on

    store = catalog.get_store(store_id)
    n = normalize.normalize(message)
    lang = n["language"]
    if not store:
        return _resp(templates.handover("default", lang), lang, "other", True, "unknown_store", grounded=False)

    # 1. Greetings and thanks need no LLM call.
    if normalize.is_greeting(n["tokens"]):
        return _resp(templates.greeting(store, lang), lang, "other")
    if normalize.is_thanks(n["tokens"]):
        return _resp(templates.thanks(lang), lang, "other")

    # 2. Rule-based escalation: complaints, refunds, discounts, bulk and custom orders go to the seller.
    esc = escalation.rule_escalation(n)
    if esc:
        intent, reason = esc
        return _resp(templates.handover(reason, lang), lang, intent, True, reason)

    # 3. Retrieval (RAG).
    retrieved = {"chunks": [], "top_score": 0.0, "embeddings": False}
    if rag:
        index = retrieval.get_index(store_id)
        want_policy = bool(set(n["tokens"]) & {"delivery", "cod", "payment", "easypaisa", "jazzcash", "exchange",
                                               "policy", "free", "order", "chahiye", "bhejna", "kitna"})
        retrieved = index.search(_build_query(n, history), want_policy=want_policy, skus=n["slots"]["skus"])

    # 4. LLM generation, 5. grounding check (one retry with the checker's feedback).
    result = None
    # trace: how this answer was produced, for the evaluation report (not used by the backend).
    trace = {"source": "rules", "first_problems": [], "retry_problems": []}
    if llm.available():
        result = _generate(store, n, history, retrieved, rag)
        trace["source"] = "llm" if result else "llm_failed"
        if not result:
            trace["llm_error"] = (llm.LAST_ERROR or "")[:300]
        if result and grounding_on:
            problems = _problems(store, result)
            if problems:
                trace["first_problems"] = problems
                result = _generate(store, n, history, retrieved, rag, feedback=problems)
                trace["source"] = "llm_retry"
                if result:
                    trace["retry_problems"] = _problems(store, result)
                if not result or trace["retry_problems"]:
                    result = None
                    trace["source"] = "rejected_then_rules"

    # 6. If there is no usable LLM answer, build a rule-based one from the catalog.
    if result is None:
        fb = fallback.reply(store, n, retrieved, lang) if rag else None
        if fb:
            reason = fb[2] if len(fb) > 2 else None
            return dict(_resp(fb[0], lang, fb[1], bool(reason), reason, grounded=True), trace=trace)
        return dict(_resp(templates.handover("default", lang), lang, "other", True, "low_confidence",
                          grounded=False), trace=trace)

    language = result["language"] if result["language"] in LANGS else lang
    intent = result["intent"] if result["intent"] in INTENTS else "other"
    order = result["order"] if result["order"] and result["order"]["items"] else None
    escalate, reason = _needs_seller(store, result, n)
    result["reply"] = _add_price(store, result, reason, n)
    return dict(_resp(result["reply"], language, "order" if order else intent, escalate, reason, order,
                      grounded=grounding_on), trace=trace)


def reindex():
    catalog.reset()
    retrieval.reset()
    out = []
    for sid in catalog.stores():
        idx = retrieval.get_index(sid)
        out.append({"store_id": sid, "chunks": len(idx.chunks), "embeddings": bool(idx.vecs)})
    return {"status": "ok", "llm": llm.available(), "model": config.LLM_MODEL, "stores": out}
