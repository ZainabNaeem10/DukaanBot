"""Loads the store catalogs from CATALOG_DIR (the same JSON files the backend uses).

Catalogs come in two kinds:
  - full catalogs (store_001): every product has sizes, colors and stock counts per size.
  - real-store catalogs (store_002, BATIK): the brand publishes only "available" or "sold out",
    sale and regular prices, and some products were captured without sizes or colors.

_prepare() turns both into the same shape so the rest of the pipeline can rely on:
  p["available"]      False = whole product sold out
  p["details_known"]  False = sizes/colors were not captured; only the seller can answer those
  p["stock"]          units per size (counts unknown -> a large number, so any quantity is accepted)
  p["regular_price"]  the price before the sale, or None
"""
import json
from pathlib import Path

from . import config

UNKNOWN_COUNT = 99  # used when the store says a size is in stock but does not publish counts

_cache = None


def _prepare(store, products):
    counts_known = store.get("stock_counts_known", True)
    store["stock_counts_known"] = counts_known
    store.setdefault("delivery_charge", 0)
    store.setdefault("payment_options", [])
    store.setdefault("city", "")
    for p in products:
        p.setdefault("colors", [])
        p.setdefault("sizes", [])
        p.setdefault("stock", {})
        p.setdefault("fabric", "not listed")
        p.setdefault("category", "")
        p.setdefault("regular_price", None)
        p["available"] = bool(p.get("available", True))
        p["details_known"] = bool(p.get("details_verified", True)) and bool(p["sizes"])
        if not p["available"]:
            p["stock"] = {s: 0 for s in p["sizes"]}
        elif not counts_known:
            p["stock"] = {s: (UNKNOWN_COUNT if int(p["stock"].get(s, 1)) > 0 else 0) for s in p["sizes"]}
    return {p["sku"]: p for p in products}


def stores():
    global _cache
    if _cache is None:
        _cache = {}
        d = Path(config.CATALOG_DIR)
        for f in sorted(d.glob("*.json")) if d.exists() else []:
            data = json.loads(f.read_text(encoding="utf-8"))
            s = dict(data["store"])
            s["products"] = _prepare(s, [dict(p) for p in data["products"]])
            _cache[s["store_id"]] = s
    return _cache


def get_store(store_id):
    return stores().get(store_id)


def reset():
    global _cache
    _cache = None
