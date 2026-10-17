"""Read a money amount typed by a broker (commission, deal value).

The ONE reader for amounts a broker types as an answer ("15tr", "15tr5",
"1,5 tỷ", "500k", "7.500.000đ"). Rent prices inside a listing post keep
using parser.parse_price, which has to find a price inside free text; this
reader takes a short reply that should be ONLY an amount and refuses
anything it cannot read in full. It never drops part of what was typed:
an unreadable or ambiguous reply returns None so the bot asks again.

Pure module (no Telegram, no DB) so the bot and the webapp can share it.
"""
import re

# unit word -> multiplier. Every word the commission step's "is this an
# amount?" filter accepts comes from here (feat_deals imports AMOUNT_WORDS),
# so the filter can never accept a word this reader cannot turn into money.
UNIT_WORDS = {
    "tỷ": 1_000_000_000, "tỉ": 1_000_000_000,
    "ty": 1_000_000_000, "ti": 1_000_000_000,
    "triệu": 1_000_000, "trieu": 1_000_000, "tr": 1_000_000,
    "củ": 1_000_000, "cu": 1_000_000, "m": 1_000_000,
    "nghìn": 1_000, "ngàn": 1_000, "nghin": 1_000, "ngan": 1_000,
    "k": 1_000,
}
# currency markers: allowed once, as the last word ("7.500.000đ",
# "15 triệu đồng"); they never multiply.
CURRENCY_WORDS = {"đ", "đồng", "dong", "vnd", "vnđ"}
AMOUNT_WORDS = frozenset(UNIT_WORDS) | frozenset(CURRENCY_WORDS)

# A bare number below this ("15") is read as "probably 15 triệu" by a
# human but is 15 đồng literally -> ambiguous -> ask again.
MIN_BARE_AMOUNT = 1000

_TOKEN = re.compile(r"\s*(?:(\d+(?:[.,]\d+)*)|([^\W\d_]+))", re.UNICODE)


def _tokenize(t):
    """[('num', '15'), ('word', 'tr'), ...] or None if a stray char is
    left (e.g. '$', '+', '-')."""
    out, pos = [], 0
    t = t.rstrip()
    while pos < len(t):
        m = _TOKEN.match(t, pos)
        if not m or m.end() == pos:
            return None
        if m.group(1):
            out.append(("num", m.group(1)))
        else:
            out.append(("word", m.group(2)))
        pos = m.end()
    return out


def _number(s, with_unit):
    """Value of a number token, or None if ambiguous.

    '7.500.000' / '7,500,000' -> 7500000 (thousand groups)
    '1,5' / '1.25'            -> decimal, only meaningful before a unit
    '1.500'                   -> thousand group when bare; ambiguous
                                 (1,5 or 1500?) before a unit -> None
    A grouped number before a unit ('7.500.000k') is ambiguous too: it is
    either a typo or 7,5 tỷ, and a wrong guess is a wrong deal -> None.
    """
    seps = re.findall(r"[.,]", s)
    if not seps:
        return int(s)
    parts = re.split(r"[.,]", s)
    if len(seps) == 1:
        frac = parts[1]
        if len(frac) == 3:
            if with_unit:
                return None
            return int(parts[0] + frac)
        if not with_unit:
            return None
        return float(parts[0] + "." + frac)
    # several separators: must be one kind, 1-3 leading digits, 3-digit groups
    if len(set(seps)) != 1 or not (1 <= len(parts[0]) <= 3) \
            or any(len(p) != 3 for p in parts[1:]):
        return None
    if with_unit:
        return None
    return int("".join(parts))


def parse_money(text):
    """Amount in VND (int) for a short typed amount, or None.

    Reads: 15tr, 15 triệu, 15tr5 (= 15,5 triệu), 15 triệu 500 nghìn,
    1 tỷ / 1 tỉ / 1,5 tỷ / 1 tỷ 2, 500k, 500 nghìn/ngàn, 15 củ, 15m,
    15000000, 7.500.000, 7500000đ, 7.500.000 vnd, 15 triệu đồng.
    None for anything ambiguous or not fully readable.
    """
    if text is None:
        return None
    t = str(text).strip().lower()
    if not t or "\n" in t:
        return None
    toks = _tokenize(t)
    if not toks:
        return None
    if toks[-1][0] == "word" and toks[-1][1] in CURRENCY_WORDS:
        toks = toks[:-1]
    if not toks or toks[0][0] != "num":
        return None
    # group into (number, unit-or-None)
    comps = []
    i = 0
    while i < len(toks):
        kind, val = toks[i]
        if kind != "num":
            return None          # two words in a row, or a currency mid-way
        unit = None
        if i + 1 < len(toks) and toks[i + 1][0] == "word":
            unit = toks[i + 1][1]
            if unit not in UNIT_WORDS:
                return None
            i += 2
        else:
            i += 1
        comps.append((val, unit))

    # one bare number: a fully written amount
    if len(comps) == 1 and comps[0][1] is None:
        n = _number(comps[0][0], with_unit=False)
        if n is None or n < MIN_BARE_AMOUNT:
            return None
        return int(n)

    total = 0
    prev_mult = None
    prev_was_decimal = False
    for idx, (num, unit) in enumerate(comps):
        if unit is None:
            # trailing digits after a unit: "15tr5" = 15,5tr, "1 tỷ 2" =
            # 1,2 tỷ, "2tr500" = 2,5tr. Only plain digits, last position.
            if idx != len(comps) - 1 or prev_mult is None \
                    or prev_was_decimal or not num.isdigit() or len(num) > 3:
                return None
            total += int(num) * prev_mult / (10 ** len(num))
            break
        if prev_was_decimal:
            return None          # "1,5 tỷ 200 triệu": which one is meant?
        mult = UNIT_WORDS[unit]
        n = _number(num, with_unit=True)
        if n is None:
            return None
        if prev_mult is not None:
            # units must go down, and each part must fit under the one
            # before it ("15 triệu 1500 nghìn" is not an amount)
            if mult >= prev_mult or n * mult >= prev_mult:
                return None
        total += n * mult
        prev_mult = mult
        prev_was_decimal = isinstance(n, float)
    total = int(round(total))
    return total if total > 0 else None


def looks_like_amount(text, max_len=30):
    """True for a short single-line reply made only of digits and the
    amount words above (used to tell an amount from a pasted listing)."""
    t = (text or "").strip().lower()
    if not t or len(t) > max_len or "\n" in t:
        return False
    if not re.search(r"\d", t):
        return False
    words = re.findall(r"[^\W\d_]+", t)
    return all(w in AMOUNT_WORDS for w in words)
