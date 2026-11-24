"""
Offline tests for the AI service. They use a fake LLM, so no API key or internet is needed.

Run from the ai-service folder:
    python -m unittest discover -s tests -v
"""
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("CATALOG_DIR", str(ROOT / "catalog"))
os.environ.setdefault("CACHE_DIR", "/tmp/dukaanbot_test_cache")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import catalog, fallback, grounding, llm, normalize, pipeline, retrieval  # noqa: E402

STORE = "store_001"


def run(message, history=None, **kw):
    return pipeline.respond(STORE, "t", message, history or [], **kw)


class FakeLLM:
    """Replaces llm.available / llm.generate_json for a test."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts = []

    def __enter__(self):
        self._a, self._g = llm.available, llm.generate_json
        llm.available = lambda: True
        llm.generate_json = self._gen
        return self

    def _gen(self, system, prompt):
        self.prompts.append(prompt)
        return self.answers.pop(0) if self.answers else None

    def __exit__(self, *exc):
        llm.available, llm.generate_json = self._a, self._g


def good_answer(**over):
    base = {"reply": "Ji, red Embroidered Lawn 3-Piece M size mein available hai. Price Rs. 5,800.",
            "language": "roman_urdu", "intent": "product_question",
            "claims": [{"sku": "LWN-001", "size": "M", "color": "red", "in_stock": True, "price": 5800}],
            "order": None, "needs_seller": False, "needs_seller_reason": None}
    base.update(over)
    return base


class TestNormalize(unittest.TestCase):
    def test_slots_and_language(self):
        n = normalize.normalize("ye red lawn suit M size mein hai?")
        self.assertEqual(n["slots"]["sizes"], ["M"])
        self.assertEqual(n["slots"]["colors"], ["red"])
        self.assertEqual(n["language"], "roman_urdu")

    def test_spelling_variants(self):
        self.assertIn("price", normalize.normalize("kimat kya hai")["tokens"])
        self.assertIn("red", normalize.normalize("laal joda chahiye")["tokens"])
        self.assertIn("available", normalize.normalize("avaialable hai?")["tokens"])
        self.assertEqual(normalize.normalize("red wala lawn suit large mein milega?")["slots"]["sizes"], ["L"])

    def test_urdu_script(self):
        n = normalize.normalize("ایمبرائیڈرڈ لان سوٹ کی قیمت کیا ہے؟")
        self.assertEqual(n["language"], "ur")
        for w in ("price", "lawn", "suit", "embroidered"):
            self.assertIn(w, n["tokens"])

    def test_english_and_mixed(self):
        self.assertEqual(normalize.normalize("I need a size M white cotton kurta")["language"], "en")
        self.assertEqual(normalize.normalize("Sea Green lawn suit S size mein hai?")["slots"]["colors"], ["sea green"])

    def test_flags(self):
        f = lambda m: normalize.normalize(m)["flags"]
        self.assertTrue(f("mujhe refund chahiye, suit kharab nikla")["refund"])
        self.assertTrue(f("bohat mehnga hai, 4500 mein de do")["discount"])
        self.assertTrue(f("mujhe 50 suits ka bulk order karna hai")["bulk"])
        self.assertTrue(f("mera order abhi tak nahi aaya, 10 din ho gaye")["delivery_issue"])
        self.assertTrue(f("tum log fraud ho, paise le kar suit nahi bheja")["fraud"])
        self.assertFalse(f("mujhe 2 cotton kurta M white chahiye")["bulk"])
        self.assertEqual(normalize.normalize("mujhe 2 cotton kurta M white chahiye")["slots"]["qty"], 2)

    def test_greeting_thanks(self):
        self.assertTrue(normalize.is_greeting(normalize.normalize("Assalam o alaikum")["tokens"]))
        self.assertTrue(normalize.is_thanks(normalize.normalize("shukriya")["tokens"]))
        self.assertFalse(normalize.is_greeting(normalize.normalize("hello price kya hai")["tokens"]))


class TestRetrieval(unittest.TestCase):
    def top(self, msg):
        n = normalize.normalize(msg)
        res = retrieval.get_index(STORE).search(n["normalized"])
        return res["chunks"][0]["id"]

    def test_right_product_first(self):
        cases = {
            "ye red lawn suit M size mein hai?": "LWN-001",
            "salam, lawn ka koi unstitched suit hai?": "LWN-003",
            "karandi shawl kitne ki hai": "KRN-001",
            "linen kurta olive L mein hai? price btao": "LIN-001",
            "wool shawl ka price?": "SHL-001",
            "plain abaya 52 size navy mein hai?": "ABY-001",
            "khaddar suit XL available hai?": "KHD-001",
        }
        for msg, sku in cases.items():
            self.assertEqual(self.top(msg), sku, msg)

    def test_policy_included_on_request(self):
        res = retrieval.get_index(STORE).search("delivery kitne din", want_policy=True)
        self.assertTrue(any(c["kind"] == "policy" for c in res["chunks"]))


class TestGrounding(unittest.TestCase):
    store = None

    @classmethod
    def setUpClass(cls):
        cls.store = catalog.get_store(STORE)

    def test_correct_claims_pass(self):
        self.assertEqual(grounding.verify(self.store, good_answer()), [])

    def test_wrong_price_fails(self):
        bad = good_answer(reply="Price Rs. 4,999.", claims=[{"sku": "LWN-001", "price": 4999}])
        self.assertTrue(grounding.verify(self.store, bad))

    def test_unsupported_number_in_text_fails(self):
        bad = good_answer(reply="Yeh sirf Rs. 4,999 ka hai.", claims=[])
        self.assertTrue(any("4999" in p for p in grounding.verify(self.store, bad)))

    def test_wrong_stock_fails(self):
        bad = good_answer(claims=[{"sku": "LWN-001", "size": "L", "in_stock": True}])  # L has 0 units
        self.assertTrue(grounding.verify(self.store, bad))

    def test_bad_color_and_size_fail(self):
        self.assertTrue(grounding.verify(self.store, good_answer(claims=[{"sku": "ABY-002", "color": "Navy"}])))
        self.assertTrue(grounding.verify(self.store, good_answer(claims=[{"sku": "SLK-001", "size": "S"}])))

    def test_phone_number_not_treated_as_price(self):
        ok = good_answer(reply="Order for 03001234567 noted. Total Rs. 2,650.", claims=[])
        self.assertEqual(grounding.verify(self.store, ok), [])

    def test_order_validation(self):
        good = {"items": [{"sku": "CTN-001", "size": "M", "color": "White", "qty": 1}],
                "name": "Ali", "address": "House 5, F-8, Islamabad", "phone": "03001234567"}
        self.assertEqual(grounding.validate_order(self.store, good), [])
        oos = dict(good, items=[{"sku": "LWN-001", "size": "L", "qty": 1}])
        self.assertTrue(grounding.validate_order(self.store, oos))
        self.assertTrue(grounding.validate_order(self.store, dict(good, phone="12345")))
        self.assertTrue(grounding.validate_order(self.store, dict(good, address="")))


class TestPipelineWithFakeLLM(unittest.TestCase):
    def test_grounded_answer_is_returned(self):
        with FakeLLM(good_answer()) as f:
            r = run("ye red lawn suit M size mein hai?")
        self.assertFalse(r["escalate"])
        self.assertTrue(r["grounded"])
        self.assertIn("5,800", r["reply"])
        self.assertIn("LWN-001", f.prompts[0])  # RAG put the right record in the prompt

    def test_wrong_answer_is_retried_with_feedback(self):
        wrong = good_answer(reply="Price Rs. 4,999.", claims=[{"sku": "LWN-001", "price": 4999}])
        with FakeLLM(wrong, good_answer()) as f:
            r = run("lawn suit ka price?")
        self.assertIn("5,800", r["reply"])
        self.assertEqual(len(f.prompts), 2)
        self.assertIn("rejected by the fact checker", f.prompts[1])

    def test_still_wrong_falls_back_to_catalog_answer(self):
        wrong = good_answer(reply="Price Rs. 4,999.", claims=[{"sku": "LWN-001", "price": 4999}])
        with FakeLLM(wrong, wrong):
            r = run("red lawn suit M size mein hai?")
        self.assertNotIn("4,999", r["reply"])
        self.assertIn("5,800", r["reply"])

    def test_order_is_returned_when_complete(self):
        order = {"items": [{"sku": "CTN-001", "size": "M", "color": "White", "qty": 1}],
                 "name": "Ali Raza", "address": "House 5 Street 3 F-8 Islamabad", "phone": "03001234567"}
        ans = good_answer(reply="Shukriya Ali! Order note kar liya. Total Rs. 2,650 (delivery ke saath).",
                          intent="order", claims=[{"sku": "CTN-001", "size": "M", "price": 2400}], order=order)
        hist = [{"role": "customer", "text": "cotton kurta M white chahiye 1"},
                {"role": "bot", "text": "Ji available hai. Naam, address, phone bata dein."}]
        with FakeLLM(ans):
            r = run("Ali Raza, House 5 Street 3 F-8 Islamabad, 03001234567", hist)
        self.assertEqual(r["intent"], "order")
        self.assertEqual(r["order"]["items"][0]["sku"], "CTN-001")

    def test_incomplete_order_is_rejected(self):
        order = {"items": [{"sku": "CTN-001", "size": "M", "qty": 1}], "name": "Ali", "address": "", "phone": ""}
        with FakeLLM(good_answer(intent="order", order=order), good_answer(intent="order", order=order)):
            r = run("cotton kurta M order karo, naam Ali")
        self.assertIsNone(r["order"])

    def test_baseline_without_rag_has_no_records(self):
        with FakeLLM(good_answer()) as f:
            run("price kya hai?", rag=False, grounding_on=False)
        self.assertIn("no catalog records", f.prompts[0])

    def test_grounding_off_accepts_wrong_answer(self):
        wrong = good_answer(reply="Price Rs. 4,999.", claims=[{"sku": "LWN-001", "price": 4999}])
        with FakeLLM(wrong):
            r = run("lawn suit price?", grounding_on=False)
        self.assertIn("4,999", r["reply"])
        self.assertFalse(r["grounded"])

    def test_needs_seller_escalates(self):
        with FakeLLM(good_answer(reply="Seller se pooch kar bataungi.", claims=[], needs_seller=True,
                                 needs_seller_reason="low_confidence")):
            r = run("kia aap ki Lahore mein shop bhi hai? address do")
        self.assertTrue(r["escalate"])

    def test_rules_and_greetings_do_not_call_llm(self):
        with FakeLLM() as f:
            self.assertTrue(run("mujhe refund chahiye, suit kharab nikla")["escalate"])
            self.assertTrue(run("thora discount mil sakta hai?")["escalate"])
            self.assertTrue(run("mujhe 50 suits ka bulk order karna hai")["escalate"])
            self.assertFalse(run("Assalam o alaikum")["escalate"])
            self.assertFalse(run("shukriya")["escalate"])
        self.assertEqual(f.prompts, [])


class TestFallbackWithoutLLM(unittest.TestCase):
    def setUp(self):
        self._a = llm.available
        llm.available = lambda: False

    def tearDown(self):
        llm.available = self._a

    def reply(self, msg):
        return run(msg)["reply"]

    def test_stock_answers(self):
        self.assertIn("available", self.reply("ye red lawn suit M size mein hai?"))
        self.assertIn("stock mein nahi", self.reply("red wala lawn suit large mein milega?"))
        self.assertIn("stock mein nahi", self.reply("khaddar suit XL available hai?"))
        self.assertIn("stock mein nahi", self.reply("cambric kurta XL mein hai?"))
        self.assertIn("nahi banta", self.reply("Raw silk kurta S size mein hai?"))

    def test_color_not_offered(self):
        self.assertIn("Black", self.reply("embroidered abaya navy mein milegi?"))

    def test_price_and_policy(self):
        self.assertIn("3,200", self.reply("Printed lawn ka price kya hai?"))
        self.assertIn("Delivery policy", self.reply("delivery Karachi kitne din mein hogi?"))
        self.assertIn("Payment options", self.reply("kya aap Easypaisa se payment le lete hain?"))

    def test_unknown_item(self):
        self.assertIn("catalog", self.reply("do you have a green leather jacket?"))
        self.assertIn("catalog", self.reply("tracksuit hai?"))

    def test_order_asks_for_details(self):
        r = run("mujhe 2 cotton kurta M white chahiye, Islamabad bhej dein")
        self.assertEqual(r["intent"], "order")
        self.assertIsNone(r["order"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
