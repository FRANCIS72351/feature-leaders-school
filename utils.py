from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def parse_currency_amount(raw_value):
    """Parse currency text into a quantized Decimal.

    Accepts 9000, 9000.00, 9,000.00, 9.000,00, and 9.000.00 (thousands
    separators plus a decimal). The last comma or dot is the decimal
    separator when both appear, or when several dots/commas are present.
    """
    if raw_value is None:
        raise ValueError("Amount is required.")
    if isinstance(raw_value, Decimal):
        return raw_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if isinstance(raw_value, bool):
        raise ValueError(f"Invalid amount: {raw_value}")
    if isinstance(raw_value, (int, float)):
        return Decimal(str(raw_value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    text = str(raw_value).strip()
    if not text:
        raise ValueError("Amount is required.")

    for symbol in ("$", "₱", "₦", "€", "£"):
        text = text.replace(symbol, "")
    text = text.replace(" ", "").replace("\u00a0", "")
    if not text:
        raise ValueError("Amount is required.")

    last_comma = text.rfind(",")
    last_dot = text.rfind(".")
    if last_comma != -1 and last_dot != -1:
        if last_comma > last_dot:
            clean = text.replace(".", "").replace(",", ".")
        else:
            clean = text.replace(",", "")
    elif last_comma != -1:
        fraction = len(text) - last_comma - 1
        if text.count(",") == 1 and fraction in (1, 2):
            clean = text.replace(",", ".")
        else:
            clean = text.replace(",", "")
    elif text.count(".") > 1:
        clean = text[:last_dot].replace(".", "") + "." + text[last_dot + 1:]
    else:
        clean = text

    try:
        return Decimal(clean).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid amount: {raw_value}") from exc


def parse_currency_amount_optional(raw_value, default=Decimal("0.00")):
    """Parse currency text; return default when the field is blank."""
    if raw_value is None:
        return default
    if isinstance(raw_value, str) and not raw_value.strip():
        return default
    return parse_currency_amount(raw_value)


def currency_to_float(raw_value, default=0.0):
    """Return currency as a two-decimal float."""
    if raw_value is None or (isinstance(raw_value, str) and not str(raw_value).strip()):
        return float(default)
    return float(parse_currency_amount(raw_value))


def build_student_financials(student, academic_year=None):
    """Stub — real implementation lives in app.py (payment-ledger only, no dummy fees)."""
    return {
        "yearly_fee": 0.0,
        "tuition_paid": 0.0,
        "tuition_balance": 0.0,
        "utility_paid": 0.0,
        "registration_paid": 0.0,
        "total_paid": 0.0,
    }
