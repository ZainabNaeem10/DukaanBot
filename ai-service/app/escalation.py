"""Rule-based escalation: messages the bot must never answer on its own."""


def rule_escalation(n):
    """Return (intent, reason) if the seller must handle this message, else None."""
    f = n["flags"]
    if f["fraud"]:
        return "complaint", "complaint"
    if f["refund"] and not f["policy_word"]:
        return "complaint", "refund"
    if f["defect"] and not f["policy_word"]:
        return "complaint", "defect"
    if f["complaint"]:
        return "complaint", "complaint"
    if f["delivery_issue"]:
        return "complaint", "delivery_issue"
    if f["custom"]:
        return "other", "custom_order"
    if f["bulk"]:
        return "bulk", "bulk_order"
    if f["discount"]:
        return "discount", "discount"
    if f.get("abroad"):
        # our records only cover delivery within Pakistan (real comment: "Why not available in UK website?")
        return "policy", "international"
    if f.get("seller_only"):
        # a link to a page/collection is not a question about a product
        return ("other" if "link" in n["tokens"] else "product_question"), "seller_only"
    return None
