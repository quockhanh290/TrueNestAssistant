"""Type checks for values the db layer stores.

The db layer is the one place that knows each column's type, so every
create_*/update_* that takes a number, a time, a list, a status or a switch
runs the value through here. A value that cannot be read is refused with
FieldError (the webapp turns it into HTTP 400 with the field name); it is
never stored as text in a REAL column or silently turned into 0.

SQLite triggers (core._migrate_type_triggers) are the second wall: they
catch writes that bypass this module (scripts, DB Browser).
"""
import math

# epoch seconds between 2000-01-01 and 2100-01-01: a millisecond timestamp
# or a bare small number is a bug, not a time
_EPOCH_MIN = 946684800.0
_EPOCH_MAX = 4102444800.0

_TRUE = {"true", "1", "yes", "on"}
_FALSE = {"false", "0", "no", "off"}


class FieldError(ValueError):
    """A value for `field` cannot be stored. reason: short machine word."""

    def __init__(self, field, reason="bad_type"):
        super().__init__(f"{field}: {reason}")
        self.field = field
        self.reason = reason


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def to_number(value, field, money=False):
    """None / "" -> None. int/float -> float. Text: a plain number
    ("2", "2.5", "2,5"); with money=True also broker shorthand ("15tr",
    "500k") through db.money.parse_money. Anything else -> FieldError."""
    if value is None or value == "":
        return None
    if _is_num(value):
        v = float(value)
    elif isinstance(value, str):
        s = value.strip()
        v = None
        try:
            v = float(s.replace(",", ".") if s.count(",") == 1
                      and "." not in s else s)
        except ValueError:
            if money:
                from .money import parse_money
                v = parse_money(s)
        if v is None:
            raise FieldError(field, "not_a_number")
    else:
        raise FieldError(field, "not_a_number")
    if math.isnan(v) or math.isinf(v) or v < 0:
        raise FieldError(field, "out_of_range")
    return v


def to_epoch(value, field, allow_none=True):
    """Epoch seconds (int/float, or a numeric string). Text dates like
    "2026-10-18 15:00" are refused: the caller converts Vietnam wall time
    with db.vntime first."""
    if value is None or value == "":
        if allow_none:
            return None
        raise FieldError(field, "required")
    if _is_num(value):
        v = float(value)
    elif isinstance(value, str):
        try:
            v = float(value.strip())
        except ValueError:
            raise FieldError(field, "not_epoch_seconds") from None
    else:
        raise FieldError(field, "not_epoch_seconds")
    if not (_EPOCH_MIN <= v <= _EPOCH_MAX):
        raise FieldError(field, "not_epoch_seconds")
    return v


def to_bool(value, field):
    """True/False, 1/0, or the words true/false/1/0/yes/no/on/off.
    "false" is False (bool("false") would be True)."""
    if isinstance(value, bool):
        return value
    if _is_num(value) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        s = value.strip().lower()
        if s in _TRUE:
            return True
        if s in _FALSE:
            return False
    raise FieldError(field, "not_a_boolean")


def to_id_list(value, field):
    """A JSON list of id strings. A bare string is refused (list("tg:ab")
    used to store one id per character)."""
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise FieldError(field, "not_a_list")
    out = []
    for v in value:
        if not isinstance(v, str) or not v:
            raise FieldError(field, "not_a_list_of_ids")
        out.append(v)
    return out


def choice(value, field, allowed):
    if value not in allowed:
        raise FieldError(field, "not_allowed")
    return value
