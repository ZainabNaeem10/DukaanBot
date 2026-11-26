# Adding real customer questions

Our teacher's feedback asked where real data comes from. The catalog is already real (BATIK's public website). This step makes part of the **test set** real too: questions that actual customers asked in public, so the evaluation is not only on messages we wrote ourselves.

Aim for **15-20 questions**. That takes about 1-2 hours.

## 1. Where to find them

Read public comments and questions by hand. Do not use scraping tools.

- Comments on BATIK's official Instagram and Facebook product posts ("price?", "M size available?", "COD hai?").
- Product questions or reviews on BATIK's website, if a product page has them.
- If BATIK has too few, use comments on other Pakistani clothing brands' posts. Pick questions that make sense for any store (delivery, COD, exchange, sizes), or that ask for something BATIK doesn't sell, so the right answer is "not in catalog".

## 2. What to copy, and what not to copy

- Copy **only the question text**, exactly as written: spelling mistakes, Roman Urdu, mixed English and Urdu. That is the point.
- **Do not copy** names, usernames, profile pictures or phone numbers. If a question contains a phone number or a name, remove it.
- Write where you found it (for example "Instagram comment on BATIK lawn post") and the date, but not who wrote it.
- Skip questions that only make sense with the photo ("ye wala?"), unless you can rewrite the product name in brackets, for example "ye wala [Edinaa] M mein hai?", and say so in `facts`.

## 3. Fill in the spreadsheet

Open `tests\real_questions_batik.csv` in Excel. One row per question:

| Column | What to write |
|---|---|
| `message` | the customer's question, copied exactly |
| `found_on` | where you found it |
| `date_found` | e.g. 2026-11-25 |
| `expected_intent` | one of: `product_question`, `policy`, `order`, `complaint`, `discount`, `bulk`, `other` |
| `expected_escalate` | `yes` if only the seller can answer (complaint, refund, discount, bulk, a product whose sizes we don't have, anything not in our records), otherwise `no` |
| `facts` | the correct answer according to `catalog\store_002.json`, in your own words |
| `must_include_any` | optional: words or numbers the reply must contain, separated by `\|`, e.g. `11,193\|11193` |

How to decide the expected behaviour:

- Product is in our catalog with sizes (Edinaa, Amiraa, Aquamarine, Kara): `no`, and the bot should answer.
- Product is in our catalog without sizes, and the customer asks about size or color: `yes` (seller confirms).
- Product is sold out: `no`, and the bot should say it is sold out.
- Product is not in our 35 products: `no`, and the bot should say it is not in the catalog.
- Delivery, COD, card payment, exchange rules: `policy`, `no`.
- Refund, damaged item, late order: `complaint`, `yes`. Discount: `discount`, `yes`. Many pieces: `bulk`, `yes`.

Save with **File > Save As > "CSV UTF-8 (Comma delimited)"**, so Urdu text is kept. You can leave the example row; rows starting with `#` are skipped.

## 4. Run it

```
python tests\run_tests.py --delay 3 --out tests\results_full.json
```

The script loads the real questions automatically (they get ids R1, R2, ...) and prints a separate score for real and written questions at the end. To run only the written ones, add `--no-real`.

## 5. In the report and slides

Say how many real questions you collected, where from, and that they were anonymized. Report the real and written scores separately, and show one or two interesting real questions with the bot's replies. If the bot fails some real questions, say which and why: that is honest and useful evidence.
