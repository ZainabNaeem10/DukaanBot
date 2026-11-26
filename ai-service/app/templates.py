"""Fixed replies for cases that do not need the LLM (greetings, handover to the seller)."""


def _lang(lang):
    return lang if lang in ("en", "ur", "roman_urdu") else "roman_urdu" if lang == "mixed" else "en"


def greeting(store, lang):
    name = store["name"]
    return {
        "en": "Hello! Welcome to %s. How can I help you today?" % name,
        "roman_urdu": "Walaikum assalam! %s mein khush aamdeed. Main aap ki kaise madad kar sakta hoon?" % name,
        "ur": "وعلیکم السلام! %s میں خوش آمدید۔ میں آپ کی کیا مدد کر سکتا ہوں؟" % name,
    }[_lang(lang)]


def thanks(lang):
    return {
        "en": "You're welcome! Let me know if you need anything else.",
        "roman_urdu": "Shukriya! Aur koi madad chahiye to bata dein.",
        "ur": "شکریہ! کوئی اور مدد چاہیے تو بتا دیں۔",
    }[_lang(lang)]


_HANDOVER = {
    "default": {
        "en": "Sorry about that. I have passed your message to the seller, who will get back to you shortly.",
        "roman_urdu": "Is masle ke liye maazrat. Aap ka message seller ko bhej diya gaya hai, woh jald aap se rabta karenge.",
        "ur": "معذرت۔ آپ کا پیغام فروخت کنندہ کو بھیج دیا گیا ہے، وہ جلد آپ سے رابطہ کریں گے۔",
    },
    "discount": {
        "en": "Prices and discounts are decided by the seller. I have passed your request to them.",
        "roman_urdu": "Discount ka faisla seller karte hain. Aap ki request unhein bhej di gayi hai, woh jald jawab denge.",
        "ur": "رعایت کا فیصلہ فروخت کنندہ کرتے ہیں۔ آپ کی درخواست انہیں بھیج دی گئی ہے۔",
    },
    "seller_only": {
        "en": "The seller will answer this for you, and I have passed your message to them. "
              "Which product are you asking about? Please send its name so they can check.",
        "roman_urdu": "Yeh maloomat seller aap ko dein ge, maine aap ka sawal unhein bhej diya hai. "
                      "Aap kis product ke baare mein pooch rahe hain? Us ka naam bata dein.",
        "ur": "یہ معلومات فروخت کنندہ آپ کو دیں گے، میں نے آپ کا سوال انہیں بھیج دیا ہے۔ "
              "آپ کس پروڈکٹ کے بارے میں پوچھ رہے ہیں؟ اس کا نام بتا دیں۔",
    },
    "bulk_order": {
        "en": "Thank you for your interest in a bulk order. I have passed this to the seller, who will contact you with the details.",
        "roman_urdu": "Bulk order mein dilchaspi ka shukriya. Aap ka message seller ko bhej diya gaya hai, woh aap se rabta karenge.",
        "ur": "بلک آرڈر میں دلچسپی کا شکریہ۔ آپ کا پیغام فروخت کنندہ کو بھیج دیا گیا ہے۔",
    },
}


def handover(reason, lang):
    group = _HANDOVER.get(reason, _HANDOVER["default"])
    return group[_lang(lang)]


def not_available(lang):
    return {
        "en": "Sorry, we do not have that item in our catalog. Is there anything else I can help you with?",
        "roman_urdu": "Maazrat, yeh item humare catalog mein nahi hai. Kisi aur cheez mein madad chahiye?",
        "ur": "معذرت، یہ چیز ہمارے کیٹلاگ میں موجود نہیں۔ کیا میں کسی اور چیز میں مدد کر سکتا ہوں؟",
    }[_lang(lang)]
