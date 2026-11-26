"""
Rule-based replies used when the LLM is unavailable, fails, or fails the grounding check.
Answers come straight from catalog data, so they are always grounded (but less natural).
"""
import re

from . import normalize, templates

_STOP = {"have", "want", "need", "with", "this", "that", "what", "which", "there", "your", "from", "does",
         "please", "hello", "available", "price", "color", "size", "order", "stock", "chahiye", "kitna",
         "mein", "hai", "kya", "dikhayein", "dikhao", "dikha", "batayein", "batao", "bata", "dein", "karna",
         "piece", "pret", "dress", "chahte", "dekhna", "bhejna", "nahi", "delivery", "payment", "policy", "exchange", "milega", "ye"}


def _vocab(store):
    words = set()
    for p in store["products"].values():
        words |= set(normalize._TOKEN_RE.findall((p["name"] + " " + p["category"] + " " + p["fabric"] + " " +
                                                  " ".join(p["colors"]) + " " + p.get("description", "")).lower()))
    return words


def _unknown_terms(store, n):
    known = _vocab(store) | set(normalize.LEX.values()) | set(normalize.COLORS) | normalize.URDU_MARKERS \
        | normalize.NOUNS | _STOP | set(normalize.SIZE_WORDS)
    return [t for t in n["tokens"] if t.isascii() and t.isalpha() and len(t) >= 4 and t not in known]


def _fmt(price):
    return "Rs. {:,}".format(int(price))


def _price_text(p, ro):
    if p.get("regular_price") and p["regular_price"] > p["price"]:
        return (("%s (sale, pehle %s)" if ro else "%s (sale, regular %s)")
                % (_fmt(p["price"]), _fmt(p["regular_price"])))
    return _fmt(p["price"])


def _product_reply(store, p, n, lang):
    """Return (text, escalate_reason or None)."""
    ro = lang in ("roman_urdu", "mixed", "ur")
    sizes, colors = n["slots"]["sizes"], n["slots"]["colors"]
    name = p["name"]
    if not p["available"]:
        return (("Maazrat, %s abhi sold out hai." if ro else "Sorry, %s is sold out at the moment.") % name), None
    if not p["details_known"]:
        text = ("%s ki price %s hai." if ro else "%s: price %s.") % (name, _price_text(p, ro))
        if sizes or colors:
            text += (" Is ke sizes aur colors mere record mein nahi hain, seller aap ko confirm kar dein ge." if ro
                     else " I don't have its sizes or colors on record, so the seller will confirm them for you.")
            return text, "details_not_listed"
        return text, None
    return _product_reply_full(store, p, n, lang), None


def _product_reply_full(store, p, n, lang):
    ro = lang in ("roman_urdu", "mixed", "ur")
    sizes, colors = n["slots"]["sizes"], n["slots"]["colors"]
    name = p["name"]
    parts = []
    if colors and not any(c in pc.lower() or pc.lower() in c for c in colors for pc in p["colors"]):
        return (("%s sirf in colors mein hai: %s." if ro else "%s is only available in: %s.")
                % (name, ", ".join(p["colors"])))
    if sizes:
        size = next((s for s in p["sizes"] if s.lower() == sizes[0].lower()), None)
        if size is None:
            return (("%s %s size mein nahi banta. Available sizes: %s." if ro else
                     "%s does not come in size %s. Available sizes: %s.")
                    % ((name, sizes[0], ", ".join(p["sizes"])) if not ro else (name, sizes[0], ", ".join(p["sizes"]))))
        if p["stock"].get(size, 0) <= 0:
            return (("%s %s size mein abhi stock mein nahi hai." if ro else "%s in size %s is out of stock.")
                    % (name, size))
        parts.append(("Ji, %s %s size mein available hai." if ro else "Yes, %s is available in size %s.") % (name, size))
        parts.append(("Is ki price %s hai." if ro else "Price: %s.") % _price_text(p, ro))
    else:
        parts.append("%s: price %s, sizes %s, colors %s." % (name, _price_text(p, ro), ", ".join(p["sizes"]),
                                                     ", ".join(p["colors"])))
    return " ".join(parts)


def _mentions(p, n):
    """True if the message names this product (a word of its name, or its SKU)."""
    if p["sku"].lower() in {s.lower() for s in n["slots"]["skus"]}:
        return True
    words = {w.lower() for w in re.findall(r"[A-Za-z]+", p["name"]) if len(w) >= 3}
    return bool(words & set(n["tokens"]))


def reply(store, n, retrieved, lang):
    """Return (reply, intent) or None if no reasonable answer can be built."""
    chunks = retrieved.get("chunks", []) if retrieved else []
    tokens = set(n["tokens"])
    ro = lang in ("roman_urdu", "mixed", "ur")
    ordering = bool(tokens & {"order", "chahiye", "bhejna"})

    products = [c for c in chunks if c["kind"] == "product"]
    policies = [c for c in chunks if c["kind"] == "policy"]
    policy_words = tokens & {"delivery", "cod", "payment", "easypaisa", "jazzcash", "exchange", "policy", "free", "return"}

    if policy_words and policies and not (products and n["slots"]["sizes"]):
        return policies[0]["text"], "policy"

    if not products or _unknown_terms(store, n) and not (tokens & normalize.NOUNS):
        return templates.not_available(lang), "product_question"

    p = store["products"][products[0]["sku"]]
    if not _mentions(p, n):
        # "I want to order this" / "in stock?": the customer means a photo we cannot see. Do not guess.
        text = ("Aap kis product ke baare mein pooch rahe hain? Us ka naam bata dein." if ro
                else "Which product are you asking about? Please send its name.")
        return text, ("order" if ordering else "product_question")
    text, reason = _product_reply(store, p, n, lang)
    if reason:
        return text, "product_question", reason
    if ordering and p["available"] and not p["details_known"]:
        text += (" Is ka size aur color seller confirm karein ge, woh jald aap se rabta karein ge." if ro
                 else " The seller will confirm the size and color with you shortly.")
        return text, "order", "details_not_listed"
    if ordering and p["available"]:
        text += (" Order ke liye apna naam, address aur phone number bata dein." if ro
                 else " To place the order, please send your name, address and phone number.")
        return text, "order"
    return text, "product_question"
