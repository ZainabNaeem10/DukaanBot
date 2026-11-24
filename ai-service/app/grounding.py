"""
Grounding check: verify what the reply claims against the catalog (the ground truth).

The LLM must list every price / size / stock / color fact it states as structured
`claims`. Each claim is compared with the catalog by plain code, and every large
number in the reply text must be a known price, charge, or total. Anything unsupported
makes the reply fail the check.
"""
import re

_NUM = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+)(?!\w)")
_ADDR_WORDS = {"house", "flat", "plot", "block", "street", "sector", "phase", "gali", "ghar", "no", "number", "h", "st"}
_PHONE = re.compile(r"^(?:\+?92|0)3\d{9}$")


def _numbers(text):
    out = []
    for m in _NUM.finditer(text):
        digits = m.group(1).replace(",", "")
        before = re.findall(r"[A-Za-z#]+", text[max(0, m.start() - 12):m.start()])
        if len(digits) >= 10 or digits.startswith("03") or (before and before[-1].lower() in _ADDR_WORDS):
            continue  # phone numbers and address numbers are not catalog facts
        out.append(int(digits))
    return out


def _policy_numbers(store):
    text = store["delivery_policy"] + " " + store["return_policy"]
    return {int(x.replace(",", "")) for x in re.findall(r"\d[\d,]*", text) if x.replace(",", "").isdigit()}


def allowed_numbers(store, order=None):
    prices = [p["price"] for p in store["products"].values()]
    allowed = set(int(p) for p in prices)
    allowed |= {int(p["regular_price"]) for p in store["products"].values() if p.get("regular_price")}
    allowed.add(int(store["delivery_charge"]))
    allowed |= _policy_numbers(store)
    for price in prices:  # quantity x price, with and without delivery
        for q in range(2, 21):
            allowed.add(int(price * q))
            allowed.add(int(price * q + store["delivery_charge"]))
        allowed.add(int(price + store["delivery_charge"]))
    if order:
        total = 0
        for it in order.get("items", []):
            p = store["products"].get(it.get("sku"))
            if p:
                total += p["price"] * int(it.get("qty") or 1)
        allowed |= {int(total), int(total + store["delivery_charge"])}
    return allowed


def _match_size(product, size):
    for s in product["sizes"]:
        if str(s).lower() == str(size).lower():
            return s
    return None


def _color_ok(product, color):
    c = str(color).lower()
    return any(c in pc.lower() or pc.lower() in c for pc in product["colors"])


def verify(store, result):
    """Return a list of problems (empty list = reply is grounded)."""
    problems = []
    products = store["products"]
    for c in result.get("claims") or []:
        if not isinstance(c, dict):
            continue
        p = products.get(str(c.get("sku", "")).upper())
        if not p:
            problems.append("claim about unknown sku %r" % c.get("sku"))
            continue
        if not p.get("available", True) and c.get("in_stock"):
            problems.append("%s is sold out, but the reply says it is in stock" % p["sku"])
        if not p.get("details_known", True) and (c.get("size") or c.get("color")):
            problems.append("%s has no sizes/colors on record; the reply must not confirm a size or color, "
                            "the seller has to" % p["sku"])
            continue
        if c.get("size"):
            size = _match_size(p, c["size"])
            if size is None:
                problems.append("%s is not made in size %s (sizes: %s)" % (p["sku"], c["size"], ", ".join(p["sizes"])))
            elif c.get("in_stock") is not None and bool(c["in_stock"]) != (p["stock"].get(size, 0) > 0):
                problems.append("stock claim wrong: %s size %s has %s units" % (p["sku"], size, p["stock"].get(size, 0)))
        if c.get("color") and not _color_ok(p, c["color"]):
            problems.append("%s does not come in %s (colors: %s)" % (p["sku"], c["color"], ", ".join(p["colors"])))
        if c.get("price") is not None:
            try:
                if abs(float(c["price"]) - p["price"]) > 0.5:
                    problems.append("price claim wrong: %s costs Rs. %s" % (p["sku"], p["price"]))
            except (TypeError, ValueError):
                problems.append("price claim is not a number")
    allowed = allowed_numbers(store, result.get("order"))
    for n in _numbers(result.get("reply", "")):
        if n >= 100 and n not in allowed:
            problems.append("reply states the number %s, which is not a catalog price, charge or total" % n)
    return problems


def validate_order(store, order):
    """Check an order object before it is sent to the backend. Returns a list of problems."""
    problems = []
    items = order.get("items") or []
    if not items:
        problems.append("order has no items")
    for it in items:
        p = store["products"].get(str(it.get("sku", "")).upper())
        if not p:
            problems.append("order item has unknown sku %r" % it.get("sku"))
            continue
        if not p.get("available", True):
            problems.append("%s is sold out and cannot be ordered" % p["sku"])
            continue
        if not p.get("details_known", True):
            problems.append("%s has no sizes/colors on record; the seller must confirm before ordering" % p["sku"])
            continue
        qty = int(it.get("qty") or 1)
        size = _match_size(p, it["size"]) if it.get("size") else None
        if it.get("size") and size is None:
            problems.append("%s has no size %s" % (p["sku"], it["size"]))
        elif size is not None and p["stock"].get(size, 0) < qty:
            problems.append("only %s of %s size %s in stock" % (p["stock"].get(size, 0), p["sku"], size))
        if len(p["sizes"]) > 1 and p["sizes"] != ["Free size"] and not it.get("size"):
            problems.append("order item %s is missing a size" % p["sku"])
        if it.get("color") and not _color_ok(p, it["color"]):
            problems.append("%s does not come in %s" % (p["sku"], it["color"]))
    for field in ("name", "address", "phone"):
        if not str(order.get(field) or "").strip():
            problems.append("order is missing %s" % field)
    phone = re.sub(r"[\s-]", "", str(order.get("phone") or ""))
    if phone and not _PHONE.match(phone):
        problems.append("phone number format looks wrong")
    return problems
