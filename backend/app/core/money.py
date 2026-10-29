from decimal import ROUND_HALF_UP, Decimal


def format_inr(amount: Decimal | int | float) -> str:
    """₹1,25,000 — Indian digit grouping."""
    n = int(Decimal(amount).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    sign, s = ("-" if n < 0 else ""), str(abs(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts + [tail])
    return f"{sign}₹{s}"
