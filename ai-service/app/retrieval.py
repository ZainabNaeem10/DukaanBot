"""
Retrieval for RAG.

Each product and each store policy becomes a text chunk. A query is scored with
BM25 (word match on normalized text) and, when the embedding API works, with
embedding cosine similarity; the two scores are mixed (hybrid search).
"""
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path

from . import catalog, config, llm

_WORD = re.compile(r"[a-z0-9\u0600-\u06ff]+")
_indexes = {}


def _tok(text):
    return _WORD.findall(text.lower())


def product_text(store, p):
    """The record the LLM sees for one product. States plainly what is known and what is not."""
    price = "Price: Rs. %s" % p["price"]
    if p.get("regular_price") and p["regular_price"] > p["price"]:
        price = "Sale price: Rs. %s (regular price Rs. %s)" % (p["price"], p["regular_price"])
    head = "%s (%s). Category: %s. %s." % (p["name"], p["sku"], p["category"], price)
    if not p["available"]:
        return head + " SOLD OUT in all sizes; cannot be ordered."
    if not p["details_known"]:
        return head + (" Available to order. Sizes, colors and fabric: NOT LISTED in our records "
                       "(only the seller can confirm them).")
    if store.get("stock_counts_known", True):
        stock = ", ".join("%s: %s" % (s, q) for s, q in p["stock"].items())
    else:
        stock = ", ".join("%s: %s" % (s, "in stock" if q > 0 else "out of stock") for s, q in p["stock"].items())
    return head + " Fabric: %s. Colors: %s. Sizes: %s. Stock by size: %s. %s" % (
        p["fabric"], ", ".join(p["colors"]), ", ".join(p["sizes"]), stock, p.get("description", ""))


def build_chunks(store):
    chunks = []
    for p in store["products"].values():
        chunks.append({"kind": "product", "id": p["sku"], "sku": p["sku"], "text": product_text(store, p)})
    chunks.append({"kind": "policy", "id": "delivery", "text": "Delivery policy: " + store["delivery_policy"]})
    chunks.append({"kind": "policy", "id": "returns", "text": "Return and exchange policy: " + store["return_policy"]})
    chunks.append({"kind": "policy", "id": "payment",
                   "text": "Payment options: " + ", ".join(store["payment_options"])})
    return chunks


def _cos(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class Index:
    def __init__(self, store):
        self.store = store
        self.chunks = build_chunks(store)
        self.tokens = [_tok(c["text"]) for c in self.chunks]
        # Product names get extra weight: in a real catalog the name ("Mavi", "Edinaa") is often the only
        # word that tells products apart, while "size", "M" and "available" appear in many records.
        self.name_tokens = [set(t for t in _tok(store["products"][c["sku"]]["name"]) if len(t) >= 3)
                            if c["kind"] == "product" else set() for c in self.chunks]
        self.avgdl = sum(len(t) for t in self.tokens) / max(1, len(self.tokens))
        df = Counter()
        for t in self.tokens:
            df.update(set(t))
        n = len(self.tokens)
        self.idf = {w: math.log(1 + (n - d + 0.5) / (d + 0.5)) for w, d in df.items()}
        self.vecs = self._load_vectors()

    def _load_vectors(self):
        texts = [c["text"] for c in self.chunks]
        key = hashlib.sha256((config.EMBED_MODEL + "\n" + "\n".join(texts)).encode("utf-8")).hexdigest()[:24]
        path = Path(config.CACHE_DIR) / ("emb_%s.json" % key)
        if path.exists():
            try:
                return json.loads(path.read_text())
            except ValueError:
                pass
        vecs = llm.embed_documents(texts)
        if vecs:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(vecs))
            except OSError:
                pass
        return vecs

    def _bm25(self, q_tokens):
        scores = []
        for toks in self.tokens:
            tf = Counter(toks)
            s = 0.0
            for w in set(q_tokens):
                if w in tf:
                    f = tf[w]
                    s += self.idf.get(w, 0) * f * 2.5 / (f + 1.5 * (0.25 + 0.75 * len(toks) / self.avgdl))
            scores.append(s)
        return scores

    def search(self, query, k=None, want_policy=False, skus=()):
        k = k or config.TOP_K
        q_tokens = _tok(query)
        bm = self._bm25(q_tokens)
        top = max(bm) or 1.0
        bm = [s / top for s in bm]
        name = [sum(self.idf.get(w, 0) for w in set(q_tokens) if w in nt) for nt in self.name_tokens]
        if max(name, default=0) > 0:
            ntop = max(name)
            bm = [0.5 * b + 0.5 * (s / ntop) for b, s in zip(bm, name)]
        scores = bm
        used_embeddings = False
        if self.vecs:
            qv = llm.embed_query(query)
            if qv:
                cos = [_cos(qv, v) for v in self.vecs]
                lo, hi = min(cos), max(cos)
                cosn = [(c - lo) / (hi - lo + 1e-9) for c in cos]
                scores = [0.5 * b + 0.5 * c for b, c in zip(bm, cosn)]
                used_embeddings = True
        order = sorted(range(len(self.chunks)), key=lambda i: scores[i], reverse=True)
        picked = [i for i in order if scores[i] > 0][:k]
        for i, c in enumerate(self.chunks):  # explicitly named SKUs are always included
            if c.get("sku") in skus and i not in picked:
                picked.append(i)
        if want_policy:
            for i in [j for j in order if self.chunks[j]["kind"] == "policy"][:2]:
                if i not in picked:
                    picked.append(i)
        return {
            "chunks": [dict(self.chunks[i], score=round(scores[i], 3)) for i in picked],
            "top_score": max([scores[i] for i in picked], default=0.0),
            "embeddings": used_embeddings,
        }


def get_index(store_id):
    store = catalog.get_store(store_id)
    if not store:
        return None
    if store_id not in _indexes:
        _indexes[store_id] = Index(store)
    return _indexes[store_id]


def reset():
    _indexes.clear()
