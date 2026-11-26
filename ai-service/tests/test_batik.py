"""
Offline tests for the real BATIK catalog (store_002): sale prices, sold-out products,
products whose sizes/colors were not captured, and unknown stock counts.

Run from the ai-service folder:
    python -m unittest discover -s tests -v
"""
import unittest

from test_pipeline import FakeLLM  # also sets CATALOG_DIR and sys.path
from app import catalog, grounding, llm, pipeline, retrieval

STORE = "store_002"


def run(message, history=None, **kw):
    return pipeline.respond(STORE, "t", message, history or [], **kw)


def answer(**over):
    base = {"reply": "Ji, Edinaa M size mein available hai. Price Rs. 11,193.",
            "language": "roman_urdu", "intent": "product_question",
            "claims": [{"sku": "BTK-001", "size": "M", "color": None, "in_stock": True, "price": 11193}],
            "order": None, "needs_seller": False, "needs_seller_reason": None}
    base.update(over)
    return base


def order(sku="BTK-001", size="M", qty=1):
    return {"items": [{"sku": sku, "size": size, "color": None, "qty": qty}],
            "name": "Sara", "address": "House 5, F-7, Islamabad", "phone": "03001234567"}


class TestBatikCatalog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        catalog.reset()
        retrieval.reset()
        cls.store = catalog.get_store(STORE)

    def test_loaded_and_prepared(self):
        self.assertEqual(len(self.store["products"]), 35)
        self.assertFalse(self.store["products"]["BTK-029"]["available"])
        self.assertFalse(self.store["products"]["BTK-003"]["details_known"])
        self.assertTrue(self.store["products"]["BTK-001"]["details_known"])

    def test_records_say_sold_out_and_not_listed(self):
        text = {c["id"]: c["text"] for c in retrieval.build_chunks(self.store)}
        self.assertIn("SOLD OUT", text["BTK-029"])
        self.assertIn("NOT LISTED", text["BTK-003"])
        self.assertIn("regular price Rs. 15990", text["BTK-001"])
        self.assertIn("M: in stock", text["BTK-001"])  # counts are not published

    def test_product_name_wins_retrieval(self):
        res = retrieval.get_index(STORE).search("mavi m size mein available hai")
        self.assertEqual(res["chunks"][0]["sku"], "BTK-003")


class TestBatikGrounding(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        catalog.reset()
        cls.store = catalog.get_store(STORE)

    def test_correct_answer_passes(self):
        self.assertEqual(grounding.verify(self.store, answer()), [])

    def test_regular_price_may_be_mentioned(self):
        a = answer(reply="Edinaa sale par Rs. 11,193 hai (pehle Rs. 15,990).")
        self.assertEqual(grounding.verify(self.store, a), [])

    def test_sold_out_in_stock_claim_fails(self):
        a = answer(reply="Lilac Dream available hai.",
                   claims=[{"sku": "BTK-029", "size": None, "color": None, "in_stock": True, "price": None}])
        self.assertTrue(grounding.verify(self.store, a))

    def test_size_claim_on_unlisted_product_fails(self):
        a = answer(reply="Mavi M size mein available hai.",
                   claims=[{"sku": "BTK-003", "size": "M", "color": None, "in_stock": True, "price": None}])
        self.assertTrue(grounding.verify(self.store, a))

    def test_orders(self):
        self.assertEqual(grounding.validate_order(self.store, order(qty=2)), [])  # counts unknown: qty ok
        self.assertTrue(grounding.validate_order(self.store, order("BTK-029", None)))  # sold out
        self.assertTrue(grounding.validate_order(self.store, order("BTK-003", "M")))  # details not listed


class TestBatikPipeline(unittest.TestCase):
    def setUp(self):
        catalog.reset()
        retrieval.reset()

    def test_llm_answer_with_unknown_size_is_rejected_then_fallback_escalates(self):
        bad = answer(reply="Ji, Mavi M size mein available hai.",
                     claims=[{"sku": "BTK-003", "size": "M", "color": None, "in_stock": True, "price": None}])
        with FakeLLM(bad, bad) as fake:
            r = run("Mavi M size mein available hai?")
        self.assertEqual(len(fake.prompts), 2)
        self.assertNotIn("M size mein available", r["reply"])
        self.assertTrue(r["escalate"])

    def test_order_for_two_is_accepted(self):
        good = answer(reply="Shukriya! 2 Edinaa M size, total Rs. 22,386. Order confirm.",
                      intent="order", order=order(qty=2),
                      claims=[{"sku": "BTK-001", "size": "M", "color": None, "in_stock": True, "price": 11193}])
        with FakeLLM(good):
            r = run("Edinaa M 2 chahiye. Sara, House 5 F-7 Islamabad, 03001234567")
        self.assertIsNotNone(r["order"])
        self.assertEqual(r["order"]["items"][0]["qty"], 2)


class TestBatikFallback(unittest.TestCase):
    def setUp(self):
        catalog.reset()
        retrieval.reset()
        self._a = llm.available
        llm.available = lambda: False

    def tearDown(self):
        llm.available = self._a

    def test_sold_out(self):
        r = run("Lilac Dream milega?")
        self.assertIn("sold out", r["reply"])
        self.assertIsNone(r["order"])

    def test_unlisted_size_goes_to_seller(self):
        r = run("Mavi M size mein available hai?")
        self.assertIn("Mavi", r["reply"])
        self.assertTrue(r["escalate"])
        self.assertEqual(r["escalate_reason"], "details_not_listed")

    def test_verified_product(self):
        r = run("Edinaa M size mein hai?")
        self.assertIn("available", r["reply"])
        self.assertIn("11,193", r["reply"])
        self.assertFalse(r["escalate"])

    def test_wrong_color(self):
        self.assertIn("Blue", run("Edinaa red color mein hai?")["reply"])


if __name__ == "__main__":
    unittest.main()


class TestBatikFollowUps(unittest.TestCase):
    """Bugs seen in the first live run (23 Nov): a completed Aquamarine order was also handed to the
    seller as details_not_listed, and an order sent as name/address/phone did not find the item."""

    HISTORY = [{"role": "customer", "text": "Aquamarine M size 1 chahiye"},
               {"role": "bot", "text": "Ji, Aquamarine 2Pc - Printed Lawn Dress M size mein available hai "
                                       "(Rs. 4,193). Order ke liye apna naam, address aur phone number bata dein."}]
    CONTACT = "Sara Khan, House 5 Street 3 F-7 Islamabad, 03001234567"

    def setUp(self):
        catalog.reset()
        retrieval.reset()

    def test_contact_message_retrieves_item_from_conversation(self):
        q = pipeline._build_query(pipeline.normalize.normalize(self.CONTACT), self.HISTORY)
        res = retrieval.get_index(STORE).search(q)
        self.assertEqual(res["chunks"][0]["sku"], "BTK-008")

    def test_wrong_details_not_listed_handover_is_dropped(self):
        done = answer(reply="Shukriya Sara! Aquamarine M size, Rs. 4,193. Order confirm ho gaya.",
                      intent="order", order=order("BTK-008", "M"),
                      claims=[{"sku": "BTK-008", "size": "M", "color": None, "in_stock": True, "price": 4193}],
                      needs_seller=True, needs_seller_reason="details_not_listed")
        with FakeLLM(done):
            r = run(self.CONTACT, self.HISTORY)
        self.assertIsNotNone(r["order"])
        self.assertFalse(r["escalate"])

    def test_real_details_not_listed_handover_is_kept(self):
        mavi = answer(reply="Mavi Rs. 11,893 ka hai. Size seller confirm karein ge.",
                      claims=[{"sku": "BTK-003", "size": None, "color": None, "in_stock": None, "price": 11893}],
                      needs_seller=True, needs_seller_reason="details_not_listed")
        with FakeLLM(mavi):
            r = run("Mavi M size mein hai?")
        self.assertTrue(r["escalate"])
        self.assertEqual(r["escalate_reason"], "details_not_listed")


class TestBatikSecondLiveRun(unittest.TestCase):
    """Second live run (23 Nov): Urdu-script product names, and handovers for clarifying questions."""

    def setUp(self):
        catalog.reset()
        retrieval.reset()

    def test_urdu_script_message_gets_catalog_index(self):
        with FakeLLM(answer()) as fake:
            run("ایڈینا کی قیمت کیا ہے؟")
        self.assertIn("CATALOG INDEX", fake.prompts[0])
        self.assertIn("Edinaa", fake.prompts[0])

    def test_roman_urdu_message_has_no_index(self):
        with FakeLLM(answer()) as fake:
            run("Edinaa M size mein hai?")
        self.assertNotIn("CATALOG INDEX", fake.prompts[0])

    def test_clarifying_question_is_not_a_handover(self):
        ask = answer(reply="Aap ko kitne Edinaa chahiye, aur kaun sa size?", claims=[],
                     needs_seller=True, needs_seller_reason="clarification_needed")
        with FakeLLM(ask):
            self.assertFalse(run("Edinaa chahiye")["escalate"])

    def test_not_in_catalog_is_not_a_handover(self):
        no = answer(reply="Maazrat, men's kurta hamare catalog mein nahi hai.", claims=[],
                    needs_seller=True, needs_seller_reason="product_not_in_catalog")
        with FakeLLM(no):
            self.assertFalse(run("do you have men's kurta?")["escalate"])

    def test_shop_address_still_goes_to_seller(self):
        q = answer(reply="Shop ka address seller bata dein ge.", claims=[],
                   needs_seller=True, needs_seller_reason="shop_address_unknown")
        with FakeLLM(q):
            self.assertTrue(run("aap ki shop kahan hai?")["escalate"])


class TestFactCheckFalseAlarms(unittest.TestCase):
    """Third live run (24 Nov): 17 of 24 LLM answers were rejected, mostly by false alarms.
    Each test replays one kind of claim the model actually sent, plus a real mistake that must still fail."""

    @classmethod
    def setUpClass(cls):
        catalog.reset()
        cls.store = catalog.get_store(STORE)

    def check(self, reply, *claims):
        return grounding.verify(self.store, answer(reply=reply, claims=list(claims)))

    def claim(self, **kw):
        c = {"sku": "BTK-001", "size": None, "color": None, "in_stock": None, "price": None}
        c.update(kw)
        return c

    def test_price_written_as_text(self):
        for price in ("Rs. 11,193", "11,193", "11193", 11193.0):
            self.assertEqual(self.check("Edinaa Rs. 11,193 ki hai.", self.claim(price=price)), [], price)

    def test_wrong_price_still_caught_in_any_format(self):
        self.assertTrue(self.check("Edinaa Rs. 9,000 ki hai.", self.claim(price="Rs. 9,000")))

    def test_regular_price_claim_ok(self):
        self.assertEqual(self.check("Pehle Rs. 15,990 thi.", self.claim(price=15990)), [])

    def test_policy_fact_without_sku(self):
        for sku in (None, "", "None", "policy"):
            self.assertEqual(self.check("COD available hai, free delivery.", self.claim(sku=sku, price=None)), [])

    def test_negative_color_and_size_claims(self):
        self.assertEqual(self.check("Edinaa red mein nahi aati, sirf Blue.",
                                    self.claim(color="red", in_stock=False)), [])
        self.assertEqual(self.check("Amiraa XXL mein nahi hai.",
                                    self.claim(sku="BTK-002", size="XXL", in_stock="false")), [])

    def test_positive_wrong_color_and_size_still_caught(self):
        self.assertTrue(self.check("Edinaa red mein hai.", self.claim(color="red", in_stock=True)))
        self.assertTrue(self.check("Amiraa XXL hai.", self.claim(sku="BTK-002", size="XXL")))

    def test_sold_out_unlisted_product_negative_claim(self):
        self.assertEqual(self.check("Myra M size sold out hai.",
                                    self.claim(sku="BTK-030", size="M", in_stock=False)), [])

    def test_unlisted_product_size_confirmation_still_caught(self):
        self.assertTrue(self.check("Mavi M available hai.", self.claim(sku="BTK-003", size="M", in_stock=True)))

    def test_made_up_number_in_reply_still_caught(self):
        self.assertTrue(self.check("Delivery Rs. 350 hai.", self.claim(sku=None)))


class TestRealComments(unittest.TestCase):
    """Real Instagram comments (25 Nov) that the rules must catch before the LLM is called."""

    def test_order_status_complaints_go_to_seller(self):
        for m in ("M ny 21 date ko order placed kiya but still koi update nai hy please check the problem",
                  "where is my order", "order not received yet"):
            r = run(m)
            self.assertTrue(r["escalate"], m)
            self.assertEqual(r["escalate_reason"], "delivery_issue", m)

    def test_ordering_is_not_a_complaint(self):
        for m in ("Order kaisy krna hai", "Edinaa order karna hai"):
            self.assertNotEqual(run(m)["escalate_reason"], "delivery_issue", m)


class TestRealCommentsRound2(unittest.TestCase):
    """Run of 25 Nov 12:16: the 'unless' prompt rule made the model over-hand-over. Handover for
    seller-only topics is now decided by rules, and the model's handovers are filtered in code."""

    def setUp(self):
        catalog.reset()
        retrieval.reset()

    def test_seller_only_topics_handed_over_by_rules_without_llm(self):
        for m in ("When will you restock velvet dresses ??", "restock kab ho ga?", "Shirt length",
                  "Size guide please", "What's actual shade ?", "Is it same color in real ?",
                  "Link? Cant find the collection on the site"):
            with FakeLLM(answer()) as fake:
                r = run(m)
            self.assertTrue(r["escalate"], m)
            self.assertEqual(r["escalate_reason"], "seller_only", m)
            self.assertEqual(r["intent"], "other" if "Link" in m else "product_question", m)
            self.assertIn("?", r["reply"], m)  # asks which product
            self.assertEqual(fake.prompts, [], m)

    def test_normal_questions_are_not_seller_only(self):
        for m in ("Edinaa M size mein hai?", "Edinaa red colour mein milega?", "Order kaisy krna hai",
                  "Fabric and price", "Yeh clr konsa he?", "In stock?"):
            with FakeLLM(answer()):
                self.assertNotEqual(run(m)["escalate_reason"], "seller_only", m)

    def _llm(self, message, reply, reason, claims=None):
        a = answer(reply=reply, claims=claims or [], needs_seller=True, needs_seller_reason=reason)
        with FakeLLM(a):
            return run(message)

    def test_which_product_question_is_not_a_handover(self):
        cases = [("Is the trouser also velvet v", "Could you please tell me which dress you are referring to?",
                  "details_not_listed"),
                 ("Yeh clr konsa he?", "Aap kis product ki colour ke baare mein pooch rahe hain?", "color_detail"),
                 ("Stuff kon sa hai", "Aap kis product ka kapra jan'na chahte hain?", "no_catalog_info")]
        for m, reply, reason in cases:
            self.assertFalse(self._llm(m, reply, reason)["escalate"], m)

    def test_price_question_on_unlisted_product_is_not_a_handover(self):
        r = self._llm("Joy festive eid print kitne ka hai", "Joy 3Pc ka sale price Rs. 9443 hai.",
                      "details_not_listed", [{"sku": "BTK-018", "size": None, "color": None,
                                              "in_stock": None, "price": 9443}])
        self.assertFalse(r["escalate"])

    def test_size_question_on_unlisted_product_keeps_handover_and_adds_price(self):
        r = self._llm("Mavi M size mein available hai?",
                      "Mavi dress ke sizes aur colors seller confirm karega.", "details_not_listed")
        self.assertTrue(r["escalate"])
        self.assertIn("11,893", r["reply"])

    def test_unknown_info_without_question_still_handed_over(self):
        r = self._llm("Why not available in UK website?",
                      "Sorry, I don't have that information. Our seller will get back to you.", "seller_info")
        self.assertTrue(r["escalate"])
