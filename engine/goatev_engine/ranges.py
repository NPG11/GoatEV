"""
ranges.py — turn range text like "QQ+, AKs, A5s-A2s" into real card combos.

Three levels of detail, from coarse to exact:

  HAND CLASS   "AKs"           a type of hand, ignoring exact suits (169 exist)
  COMBO        ("As", "Ks")    one exact 2-card hand (1,326 exist)
  RANGE        {"AKs": 1.0, "QQ": 0.5, ...}
               hand classes -> weight (how often villain has it, 0..1)

Combos per hand class:
  pair     "QQ"   C(4,2) = 6    (QsQh QsQd QsQc QhQd QhQc QdQc)
  suited   "AKs"  4             (one per suit)
  offsuit  "AKo"  4 x 3 = 12    (any two different suits)
  both     "AK"   16            (4 suited + 12 offsuit)

Notation supported:
  QQ        one pair           AKs / AKo / AK    one non-pair class
  QQ+       QQ, KK, AA         ATs+              ATs, AJs, AQs, AKs
  99-66     99, 88, 77, 66     A5s-A2s           A5s, A4s, A3s, A2s
  AKs:0.5   any token with a weight (default 1.0)
"""

import re
from itertools import combinations

from .equity import Combo, remove_blocked
from .scenario import RANKS, SUITS

TOTAL_COMBOS = 1326   # C(52, 2): every possible starting hand

Range = dict[str, float]   # hand class -> weight


# ---------------------------------------------------------------------------
# Hand classes
# ---------------------------------------------------------------------------

def _rank_value(r: str) -> int:
    """'2' -> 0 ... 'A' -> 12. Higher number = stronger rank."""
    return RANKS.index(r)


def _make_class(high: str, low: str, suffix: str) -> str:
    """Build a hand-class name, always strongest rank first."""
    if _rank_value(low) > _rank_value(high):
        high, low = low, high
    return high + low if high == low else high + low + suffix


def all_hand_classes() -> list[str]:
    """All 169 starting-hand classes: 13 pairs + 78 suited + 78 offsuit."""
    hands = []
    for i, high in enumerate(reversed(RANKS)):
        for low in reversed(RANKS[: len(RANKS) - i]):
            if high == low:
                hands.append(high + low)
            else:
                hands += [high + low + "s", high + low + "o"]
    return hands


def hand_combos(hand: str) -> list[Combo]:
    """'AKs' -> [('As','Ks'), ('Ah','Kh'), ('Ad','Kd'), ('Ac','Kc')]"""
    high, low, suffix = hand[0], hand[1], hand[2:]
    if high == low:
        return [(high + a, low + b) for a, b in combinations(SUITS, 2)]
    if suffix == "s":
        return [(high + s, low + s) for s in SUITS]
    if suffix == "o":
        return [(high + a, low + b) for a in SUITS for b in SUITS if a != b]
    raise ValueError(f"'{hand}' needs 's' or 'o'")


# ---------------------------------------------------------------------------
# Parsing range text
# ---------------------------------------------------------------------------

_HAND = r"([2-9TJQKA])([2-9TJQKA])([so]?)"
_SINGLE = re.compile(rf"^{_HAND}(\+?)$")
_DASH = re.compile(rf"^{_HAND}-{_HAND}$")


def expand_token(token: str) -> list[str]:
    """One piece of range text -> the hand classes it means.
    'ATs+' -> ['ATs', 'AJs', 'AQs', 'AKs']"""
    # Normalise case: ranks upper, s/o lower. "aks" -> "AKs", "a5s-a2s" -> "A5s-A2s"
    t = "".join(ch.lower() if ch.lower() in "so" else ch.upper()
                for ch in token.strip())

    m = _SINGLE.match(t)
    if m:
        high, low, suffix, plus = m.groups()
        if _rank_value(low) > _rank_value(high):
            high, low = low, high          # "KA" -> "AK"
        if high == low:
            if suffix:
                raise ValueError(f"'{token}': pairs can't be suited/offsuit")
            if not plus:
                return [high + low]
            # QQ+ -> every pair from QQ up to AA
            return [r + r for r in RANKS[_rank_value(high):]]
        suffixes = [suffix] if suffix else ["s", "o"]
        if not plus:
            return [high + low + s for s in suffixes]
        # ATs+ -> keep the A, raise the kicker up to one below the A
        kickers = RANKS[_rank_value(low): _rank_value(high)]
        return [high + k + s for k in kickers for s in suffixes]

    m = _DASH.match(t)
    if m:
        h1, l1, s1, h2, l2, s2 = m.groups()
        if h1 == l1 and h2 == l2 and not s1 and not s2:
            # 99-66 -> 99, 88, 77, 66
            lo, hi = sorted([_rank_value(h1), _rank_value(h2)])
            return [r + r for r in RANKS[lo: hi + 1]]
        if h1 == h2 and h1 != l1 and h2 != l2 and s1 == s2:
            # A5s-A2s -> A5s, A4s, A3s, A2s  (same top card, kicker varies)
            lo, hi = sorted([_rank_value(l1), _rank_value(l2)])
            if hi >= _rank_value(h1):
                raise ValueError(f"'{token}': kicker must be below the top card")
            suffixes = [s1] if s1 else ["s", "o"]
            return [h1 + k + s for k in RANKS[lo: hi + 1] for s in suffixes]
        raise ValueError(
            f"'{token}': a dash range must be pairs (99-66) "
            f"or share the top card (A5s-A2s)"
        )

    raise ValueError(f"can't read '{token}' (examples: QQ+, AKs, ATo+, 99-66)")


def parse_range(text: str) -> Range:
    """'QQ+, AKs, AJs:0.5' -> {'QQ':1.0, 'KK':1.0, 'AA':1.0, 'AKs':1.0, 'AJs':0.5}
    If a hand appears twice, the later weight wins."""
    result: Range = {}
    for piece in text.split(","):
        piece = piece.strip()
        if not piece:
            continue
        token, _, weight_text = piece.partition(":")
        weight = float(weight_text) if weight_text else 1.0
        if not 0 <= weight <= 1:
            raise ValueError(f"'{piece}': weight must be between 0 and 1")
        for hand in expand_token(token):
            result[hand] = weight
    return result


# ---------------------------------------------------------------------------
# Range -> combos (ready for equity.equity_vs_range)
# ---------------------------------------------------------------------------

def range_to_combos(rng: Range, dead: list[str] = ()) -> tuple[list[Combo], list[float]]:
    """Expand a range into exact combos + matching weights,
    dropping any combo that uses a card in `dead` (hero's cards, board)."""
    combos, weights = [], []
    for hand, w in rng.items():
        if w <= 0:
            continue
        for c in remove_blocked(hand_combos(hand), list(dead)):
            combos.append(c)
            weights.append(w)
    return combos, weights


def combo_count(rng: Range, dead: list[str] = ()) -> float:
    """Weighted number of combos. {'AKs': 1.0, 'QQ': 0.5} -> 4 + 3 = 7.0"""
    _, weights = range_to_combos(rng, dead)
    return sum(weights)


def range_percent(rng: Range) -> float:
    """Share of all 1,326 starting hands. 'QQ+, AKs' -> 22/1326 = 1.66%"""
    return combo_count(rng) / TOTAL_COMBOS
