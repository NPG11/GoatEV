"""
strength.py — put all 169 starting hands in order, strongest first.

Why we need this: to make a range TIGHTER (Nit) we drop its weakest hands;
to make it WIDER (Maniac) we add the next-best hands it doesn't have yet.
Both need a ranking.

We use the CHEN FORMULA, a classic quick way to score a starting hand
(by Bill Chen, a poker pro and mathematician):

  1. Score the HIGHER card:  A = 10, K = 8, Q = 7, J = 6, T..2 = half its value
                             (T = 5, 9 = 4.5, ... 2 = 1)
  2. Pair?                   double it (minimum 5).            AA = 20, 22 = 5
  3. Suited?                 +2
  4. Gap between the cards:  0 -> 0, 1 -> -1, 2 -> -2, 3 -> -4, 4+ -> -5
                             (gap = ranks missing between them; KQ = 0, K9 = 2)
  5. Connected or 1-gap, and both cards below a Q?   +1  (straight potential)

Examples:  AKs = 10 + 2 = 12     T9s = 5 + 2 + 1 = 8     72o = 3.5 - 5 = -1.5

The usual formula rounds up; we keep the half points so the order is finer.
It's an approximation — good enough to decide which hands to add or drop.
Known weakness: it scores small pairs (22-66) low, so a tightened range
drops them first, even though many real players keep them to hit a set.
"""

from .ranges import all_hand_classes
from .scenario import RANKS

_HIGH_CARD_POINTS = {"A": 10, "K": 8, "Q": 7, "J": 6}
_GAP_PENALTY = {0: 0, 1: -1, 2: -2, 3: -4}   # 4 or more -> -5


def _card_points(rank: str) -> float:
    return _HIGH_CARD_POINTS.get(rank, (RANKS.index(rank) + 2) / 2)


def chen_score(hand: str) -> float:
    """'AKs' -> 12.0, '72o' -> -1.5"""
    high, low, suffix = hand[0], hand[1], hand[2:]
    score = _card_points(high)

    if high == low:
        return max(score * 2, 5)

    if suffix == "s":
        score += 2

    gap = RANKS.index(high) - RANKS.index(low) - 1
    score += _GAP_PENALTY.get(gap, -5)

    if gap <= 1 and RANKS.index(high) < RANKS.index("Q"):
        score += 1

    return score


def hands_by_strength() -> list[str]:
    """All 169 hand classes, strongest first.
    Ties are broken by higher cards, then suited before offsuit."""
    def sort_key(hand: str):
        return (
            chen_score(hand),
            RANKS.index(hand[0]),
            RANKS.index(hand[1]),
            hand.endswith("s"),
        )
    return sorted(all_hand_classes(), key=sort_key, reverse=True)
