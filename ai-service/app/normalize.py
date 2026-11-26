"""
Roman Urdu / Urdu / English normalization.

Turns a raw customer message into:
  - a normalized token list (spelling variants mapped to one canonical word),
  - the language of the message (en, ur, roman_urdu, mixed),
  - slots (sizes, colors, quantity, SKU codes),
  - flags (refund, discount, bulk, ... ) used for escalation rules.
"""
import difflib
import re

# canonical word -> spelling variants seen in Roman Urdu / chat English
_GROUPS = {
    "kya": ["kya", "kia", "kiya", "kyaa", "kyah"],
    "hai": ["hai", "hy", "hae", "he", "hain", "hen", "hyn", "haen"],
    "mein": ["mein", "mei", "mai", "maen"],
    "kitna": ["kitna", "kitne", "kitnay", "kitni", "kitnaa", "ketna", "kitnai"],
    "price": ["price", "prices", "qeemat", "qimat", "keemat", "kimat", "rate", "rates", "daam", "dam", "qeemt", "cost"],
    "chahiye": ["chahiye", "chahiyay", "chahie", "chaiye", "chahye", "chahea", "chahiyeh", "chahiyae"],
    "bhejna": ["bhej", "bhejna", "bhejo", "bhejein", "bhejen", "bhijwa", "bhijwana", "bhejdein", "bhejdo", "send"],
    "nahi": ["nahi", "nahin", "nai", "nhi", "nahe"],
    "delivery": ["delivery", "deliver", "delivri", "dilivery", "dilevery", "shipping", "courier"],
    "payment": ["payment", "paisay", "adaigi"],
    "easypaisa": ["easypaisa", "easypaysa", "easypesa"],
    "jazzcash": ["jazzcash", "jazcash"],
    "size": ["size", "saiz", "sz", "sizes", "saize"],
    "available": ["available", "avaialable", "availble", "avaliable", "milega", "milegi", "milta", "milti"],
    "stock": ["stock", "stok"],
    "order": ["order", "oder", "orderr", "ordar", "booking"],
    "color": ["color", "colour", "colr", "rang", "rung"],
    "lawn": ["lawn", "lown", "laan"],
    "cotton": ["cotton", "cottn", "coton"],
    "khaddar": ["khaddar", "khadar", "khaddr"],
    "chiffon": ["chiffon", "shiffon", "chifon"],
    "cambric": ["cambric", "cambrick"],
    "wool": ["wool", "woolen", "woollen"],
    "silk": ["silk"],
    "suit": ["suit", "suits", "joda", "jora", "jode", "sut", "3pc", "3-piece", "3piece", "2pc", "2-piece", "2piece"],
    "kurta": ["kurta", "kurti", "kurtay", "kurtas", "kurtey", "kameez", "qameez"],
    "trouser": ["trouser", "trousers", "shalwar", "salwar", "pajama", "pyjama", "pant", "pants"],
    "dupatta": ["dupatta", "dopatta", "dupata", "dupatte"],
    "shawl": ["shawl", "shawls", "shaal", "chadar"],
    "abaya": ["abaya", "abayas", "abya", "burqa"],
    "unstitched": ["unstitched", "unstiched", "un-stitched", "kapra", "fabric"],
    "embroidered": ["embroidered", "embroidary", "embroidery", "embroidred", "kadhai", "kadhaai", "kadai"],
    "printed": ["printed", "print", "prints"],
    "plain": ["plain", "sada", "saada"],
    "exchange": ["exchange", "exchanged", "badalna", "badal"],
    # words that trigger escalation
    "refund": ["refund", "refunds", "rifund", "wapsi"],
    "complaint": ["complaint", "complain", "complaints", "shikayat", "shikayet", "shikaayat"],
    "defect": ["kharab", "kharaab", "damaged", "damage", "defective", "defect", "faulty", "phata", "phati", "torn", "broken", "galat"],
    "fraud": ["fraud", "scam", "dhoka", "dhokha", "dhoke", "jhoota", "jhoot", "fake", "cheat", "chor", "looted"],
    "discount": ["discount", "discounts", "mehnga", "mehenga", "mehngi", "mahenga", "mahnga", "mehngay", "expensive", "costly", "sasta", "sasti", "bargain", "concession", "rayat"],
    "bulk": ["bulk", "wholesale", "thok", "wholesaler"],
    "custom": ["custom", "customize", "customised", "customized", "measurement", "measurements", "tailor", "tailoring"],
    "tracking": ["tracking", "track"],
    "policy": ["policy", "policies"],
}
LEX = {v: canon for canon, variants in _GROUPS.items() for v in variants}

# Urdu script -> canonical word
URDU_MAP = {
    "قیمت": "price", "لان": "lawn", "سوٹ": "suit", "کرتا": "kurta", "کرتے": "kurta", "کرتی": "kurta",
    "لارج": "large", "سمال": "small", "میڈیم": "medium", "سائز": "size", "ہے": "hai", "ہیں": "hai",
    "میں": "mein", "کیا": "kya", "ایمبرائیڈرڈ": "embroidered", "کڑھائی": "embroidered",
    "ڈیلیوری": "delivery", "ڈسکاؤنٹ": "discount", "ریفنڈ": "refund", "شکایت": "complaint",
    "آرڈر": "order", "رنگ": "color", "سرخ": "red", "لال": "red", "نیلا": "blue", "سیاہ": "black",
    "کالا": "black", "سفید": "white", "ہرا": "green", "پیلا": "yellow", "شال": "shawl",
    "دوپٹہ": "dupatta", "دوپٹے": "dupatta", "عبایا": "abaya", "ٹراؤزر": "trouser", "شلوار": "trouser",
    "کتنا": "kitna", "کتنے": "kitna", "کتنی": "kitna", "کاٹن": "cotton", "شفون": "chiffon",
    "کھدر": "khaddar", "پرنٹڈ": "printed", "یہ": "ye", "کا": "ka", "کی": "ki", "کے": "ke",
}

COLORS = {
    "red": ["red", "laal", "lal", "surkh"],
    "blue": ["blue", "neela", "neeli", "nila", "neelay"],
    "yellow": ["yellow", "peela", "peeli", "pila"],
    "green": ["green", "hara", "hari", "haray"],
    "black": ["black", "kala", "kali", "kaala"],
    "white": ["white", "safed", "safaid"],
    "pink": ["pink", "gulabi"],
    "orange": ["orange", "narangi"],
    "brown": ["brown", "bhura", "bhoora"],
    "grey": ["grey", "gray", "slate"],
    "maroon": ["maroon"], "mustard": ["mustard"], "olive": ["olive"], "sand": ["sand"],
    "peach": ["peach"], "navy": ["navy"], "teal": ["teal"], "emerald": ["emerald"],
    "camel": ["camel"], "gold": ["gold", "golden"], "beige": ["beige"],
}
COLOR_LOOKUP = {v: canon for canon, vs in COLORS.items() for v in vs}

SIZE_WORDS = {"small": "S", "medium": "M", "large": "L", "xlarge": "XL", "xxl": "XXL"}
SIZE_LETTERS = {"s", "m", "l", "xl", "xxl"}
NOUNS = {"suit", "kurta", "trouser", "dupatta", "shawl", "abaya", "piece", "pieces", "pcs", "pc", "item", "items"}
NUMWORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "ek": 1, "aik": 1, "teen": 3, "char": 4}

GREET_WORDS = {"assalam", "alaikum", "salam", "walaikum", "o", "hello", "hi", "hey", "aoa", "good", "morning",
               "evening", "afternoon", "ji", "sir", "madam", "baji", "bhai", "apa"}
GREET_KEY = {"assalam", "salam", "walaikum", "hello", "hi", "hey", "aoa", "good"}
THANKS_WORDS = {"shukriya", "shukria", "thanks", "thank", "you", "jazakallah", "meherbani", "ok", "okay",
                "acha", "theek", "thik", "hai", "bohat", "bahut"}
THANKS_KEY = {"shukriya", "shukria", "thanks", "thank", "jazakallah", "meherbani"}

# Roman Urdu function words (used only to detect the language)
URDU_MARKERS = {"ye", "yeh", "wo", "woh", "ka", "ki", "ke", "ko", "se", "mein", "hai", "kya", "kitna", "kab",
                "nahi", "haan", "ji", "aap", "ap", "mujhe", "chahiye", "bhejna", "dein", "den", "kar", "karo",
                "karna", "kia", "koi", "bohat", "thora", "zaroor", "shukriya", "salam", "assalam", "walaikum",
                "acha", "theek", "mera", "meri", "hum", "tum", "aur", "bhi", "abhi", "tak", "kis", "kaun",
                "lagenge", "milega", "milegi", "hoga", "hogi", "chahiyay", "wala", "wali", "wale", "btao", "bata"}
EN_MARKERS = {"the", "i", "you", "do", "have", "want", "need", "is", "are", "in", "for", "can", "please",
              "what", "how", "a", "an", "and", "with", "this", "that", "of", "to", "my", "me", "it", "does"}

_VOCAB = sorted({k for k in LEX if k.isalpha() and len(k) >= 5} | {"embroidered", "unstitched", "available"})
_TOKEN_RE = re.compile(r"\w+(?:-\w+)*")
_SKU_RE = re.compile(r"^[a-z]{3}-\d{3}$")
_URDU_CHARS = re.compile(r"[\u0600-\u06FF]")
_LATIN_WORD = re.compile(r"[A-Za-z]{2,}")
_SIZE_NEXT = {"size", "mein", "available", "hai", "stock", "wala", "wali", "ka"}
# Questions only the seller can answer, whichever product it is (real Instagram comments, 25 Nov):
# restock dates, size guides, measurements, how a colour looks in real life, links to collections.
_SELLER_ONLY = re.compile(
    r"\bre-?stock|\bdobara (?:kab|aa)|\bsize (?:guide|chart)|\bmeasurements?\b|\blength\b|\blambai\b"
    r"|\b(?:actual|real|asal|asli) (?:shade|colou?r|clr|rang)\b|\bin real\b|\breal (?:life|mein|me)\b"
    r"|\blink\b")
_ABROAD = re.compile(r"\b(?:uk|usa|canada|uae|dubai|abroad|international|internationally|overseas|worldwide)\b"
                     r"|\boutside pakistan\b")
_NOT_RECEIVED = re.compile(r"\bnot (?:yet )?(?:received|delivered|arrived)\b|\bstill waiting\b")
_DELIVERY_ISSUE = re.compile(r"\bnahi (?:aaya|aayi|ayi|pohancha|pahuncha|mila|mili)\b")


def _detect_language(text, tokens):
    urdu_letters = len(_URDU_CHARS.findall(text))
    latin_words = _LATIN_WORD.findall(text)
    if urdu_letters:
        return "mixed" if len(latin_words) >= 2 else "ur"
    low = [t for t in re.findall(r"[a-z]+", text.lower())]
    ur = sum(1 for t in low if t in URDU_MARKERS)
    en = sum(1 for t in low if t in EN_MARKERS)
    if ur >= 1 and en >= 2:
        return "mixed"
    if ur >= 1:
        return "roman_urdu"
    return "en"


def normalize(text):
    original = text or ""
    t = original.lower()
    t = re.sub(r"(.)\1{2,}", r"\1\1", t)  # kyaaaa -> kyaa
    t = t.replace("cash on delivery", "cod").replace("extra large", "xlarge").replace("sea green", "sea_green")
    t = re.sub(r"\b(paise|paisay|money)\s+(wapas|wapis|back)\b", "refund", t)
    t = re.sub(r"\b(kam)\s+(karo|kar|kardo|kardein)\b", "discount", t)
    t = re.sub(r"\bthora\s+kam\b", "discount", t)

    tokens, colors, skus = [], [], []
    for raw in _TOKEN_RE.findall(t):
        if raw in URDU_MAP:
            tok = URDU_MAP[raw]
        elif raw in LEX:
            tok = LEX[raw]
        elif raw == "sea_green":
            colors.append("sea green")
            tokens += ["sea", "green"]
            continue
        elif raw in COLOR_LOOKUP:
            tok = COLOR_LOOKUP[raw]
        elif _SKU_RE.match(raw):
            skus.append(raw.upper())
            tok = raw
        elif raw.isascii() and raw.isalpha() and len(raw) >= 5:
            m = difflib.get_close_matches(raw, _VOCAB, n=1, cutoff=0.86)
            tok = LEX.get(m[0], m[0]) if m else raw
        else:
            tok = raw
        if tok in COLORS and tok not in colors and "sea green" not in colors:
            colors.append(tok)
        elif tok in COLORS and tok == "green" and "sea green" in colors:
            pass
        tokens.append(tok)

    # sizes
    sizes = []
    for i, tok in enumerate(tokens):
        prev = tokens[i - 1] if i else ""
        nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
        size = None
        if tok in SIZE_WORDS:
            size = SIZE_WORDS[tok]
        elif tok in ("xl", "xxl"):
            size = tok.upper()
        elif tok in SIZE_LETTERS and (prev == "size" or nxt in _SIZE_NEXT):
            size = tok.upper()
        elif tok.isdigit() and 50 <= int(tok) <= 60 and (prev == "size" or nxt == "size" or "abaya" in tokens):
            size = tok
        if size and size not in sizes:
            sizes.append(size)

    # quantity: "2 cotton kurta", "50 suits"
    qty = None
    for i, tok in enumerate(tokens):
        n = int(tok) if tok.isdigit() else NUMWORDS.get(tok)
        if n and 1 <= n <= 999 and not (tok.isdigit() and 50 <= n <= 60 and "size" in tokens):
            if any(x in NOUNS for x in tokens[i + 1:i + 4]):
                qty = n
                break

    joined = " ".join(tokens)
    tokset = set(tokens)
    flags = {
        "refund": "refund" in tokset,
        "complaint": "complaint" in tokset,
        "defect": "defect" in tokset,
        "fraud": "fraud" in tokset,
        "discount": "discount" in tokset,
        "bulk": "bulk" in tokset or bool(qty and qty >= 10),
        "custom": "custom" in tokset,
        "delivery_issue": (bool(_DELIVERY_ISSUE.search(joined)) or "tracking" in tokset
                           or bool(_NOT_RECEIVED.search(joined))
                           # "order placed kiya but still koi update nai" (real comment, 25 Nov)
                           or ("order" in tokset and bool(tokset & {"update", "status", "still", "where"}))),
        "exchange": "exchange" in tokset,
        "seller_only": bool(_SELLER_ONLY.search(original.lower())),
        "abroad": bool(_ABROAD.search(original.lower())),
        "policy_word": "policy" in tokset,
    }
    return {
        "original": original,
        "normalized": joined,
        "tokens": tokens,
        "language": _detect_language(original, tokens),
        "slots": {"sizes": sizes, "colors": colors, "qty": qty, "skus": skus},
        "flags": flags,
    }


def is_greeting(tokens):
    s = set(tokens)
    return bool(s) and s <= GREET_WORDS and bool(s & GREET_KEY)


def is_thanks(tokens):
    s = set(tokens)
    return bool(s) and s <= THANKS_WORDS and bool(s & THANKS_KEY)
