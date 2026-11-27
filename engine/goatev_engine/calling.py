"""
calling.py — when hero bets, WHICH of villain's hands keep playing?

Villain doesn't fold at random. They fold their weakest hands and keep
the strongest. So if a Nit folds 55% to a bet, the hands that call are
the TOP 45% of their range — and hero's equity against those is lower
than against the whole range.

To find "the top 45%" we rank villain's combos by how strong they are:

  preflop   by the Chen score of the hand (strength.py)
  flop      by the actual made hand on this board (treys score),
            with strong DRAWS (flush draw, open-ended straight draw)
            treated like a weak pair, because people keep playing draws.

One more rule: villain can't fold MORE than the hands that missed.
Hands that are top pair or better on the flop (or QQ+/AK preflop) never
fold to one bet. So the real fold rate is capped at the share of the
range that is weaker than that.
"""

from treys import Card, Evaluator

from .equity import Combo
from .ranges import parse_range
from .scenario import RANKS
from .strength import chen_score

_EVALUATOR = Evaluator()

# treys scores: 1 = royal flush ... 7462 = worst high card. Lower = stronger.
# One pair is 3326-6185. A strong draw is ranked like a weak pair.
DRAW_SCORE = 5500

NEVER_FOLD_PREFLOP = set(parse_range("QQ+, AK"))


# ---------------------------------------------------------------------------
# Describing one villain combo
# ---------------------------------------------------------------------------

def combo_class(combo: Combo) -> str:
    """('Kd', 'As') -> 'AKo'   ('Qh', 'Qc') -> 'QQ'"""
    a, b = sorted(combo, key=lambda c: RANKS.index(c[0]), reverse=True)
    if a[0] == b[0]:
        return a[0] + b[0]
    return a[0] + b[0] + ("s" if a[1] == b[1] else "o")


def made_score(combo: Combo, board: list[str]) -> int:
    """treys score of villain's best hand right now (needs 3+ board cards)."""
    return _EVALUATOR.evaluate([Card.new(c) for c in board],
                               [Card.new(c) for c in combo])


def has_flush_draw(combo: Combo, board: list[str]) -> bool:
    """4 cards of one suit, at least one of them in villain's hand."""
    cards = list(combo) + list(board)
    for suit in {c[1] for c in combo}:
        if sum(c[1] == suit for c in cards) == 4:
            return True
    return False


def _values(cards) -> set[int]:
    vals = {RANKS.index(c[0]) for c in cards}
    if 12 in vals:          # an ace also plays low (A-2-3-4-5)
        vals.add(-1)
    return vals


def has_open_ended_draw(combo: Combo, board: list[str]) -> bool:
    """4 ranks in a row, open at both ends, using at least one hole card.
    e.g. villain 9-8 on a 7-6-2 board (a 5 or a T makes a straight)."""
    all_vals = _values(list(combo) + list(board))
    hole_vals = _values(combo)
    for low in range(0, 9):               # windows 2-5 ... T-K, both ends open
        window = set(range(low, low + 4))
        if window <= all_vals and window & hole_vals:
            return True
    return False


def strength_key(combo: Combo, board: list[str]) -> float:
    """A number where LOWER = STRONGER, used to sort villain's range."""
    if not board:
        return -chen_score(combo_class(combo))
    score = made_score(combo, board)
    if len(board) < 5 and (has_flush_draw(combo, board)
                           or has_open_ended_draw(combo, board)):
        score = min(score, DRAW_SCORE)
    return score


def _made_category(combo: Combo, board: list[str]) -> str | None:
    """'strong', 'top_pair', 'weak_pair', or None (no pair of villain's own)."""
    rank_class = _EVALUATOR.get_rank_class(made_score(combo, board))
    # treys classes: 1 straight flush, 2 quads, 3 full house, 4 flush,
    #                5 straight, 6 trips, 7 two pair, 8 one pair, 9 high card
    board_ranks = [c[0] for c in board]
    board_paired = len(set(board_ranks)) < len(board_ranks)

    if rank_class <= 6:
        return "strong"
    if rank_class == 7 and not board_paired:
        return "strong"                      # real two pair, using both hole cards
    if rank_class == 9:
        return None
    # One pair (or "two pair" where one pair is on the board):
    # what matters is villain's OWN pair and how it compares to the board.
    all_ranks = [c[0] for c in combo] + board_ranks
    own = [r for r in {c[0] for c in combo} if all_ranks.count(r) >= 2]
    if not own:
        return None                          # the only pair is the board's
    pair = max(own, key=RANKS.index)
    top_board = max(RANKS.index(r) for r in board_ranks)
    return "top_pair" if RANKS.index(pair) >= top_board else "weak_pair"


def hand_category(combo: Combo, board: list[str]) -> str:
    """Sort a villain hand on the flop into one of five buckets:
    strong (two pair+), top_pair (incl. overpairs), draw, weak_pair, air."""
    made = _made_category(combo, board)
    if made in ("strong", "top_pair"):
        return made
    if len(board) < 5 and (has_flush_draw(combo, board) or has_open_ended_draw(combo, board)):
        return "draw"
    return made or "air"


def never_folds(combo: Combo, board: list[str]) -> bool:
    """Hands no one folds to a single bet: QQ+/AK preflop,
    top pair or better on the flop."""
    if not board:
        return combo_class(combo) in NEVER_FOLD_PREFLOP
    return _made_category(combo, board) in ("strong", "top_pair")


# ---------------------------------------------------------------------------
# Working with the whole range
# ---------------------------------------------------------------------------

def max_fold_share(combos: list[Combo], weights: list[float], board: list[str]) -> float:
    """The most villain can fold: the share of the range that is NOT a never-fold hand."""
    total = sum(weights)
    strong = sum(w for c, w in zip(combos, weights) if never_folds(c, board))
    return 1 - strong / total


def strength_order(combos: list[Combo], board: list[str]) -> list[int]:
    """Indexes of `combos`, strongest first. Compute once, reuse many times."""
    return sorted(range(len(combos)), key=lambda i: strength_key(combos[i], board))


def continuing_weights(
    combos: list[Combo], weights: list[float], board: list[str], continue_share: float,
    order: list[int] | None = None,
) -> list[float]:
    """Weights for the hands that CALL, same order as `combos`.

    Keeps the strongest hands until they make up `continue_share` of the
    range (by weight). The hand at the edge keeps a partial weight.
    Folded hands get weight 0. Pass `order` (from strength_order) to skip re-sorting.
    """
    if not 0 <= continue_share <= 1:
        raise ValueError("continue_share must be between 0 and 1")
    if order is None:
        order = strength_order(combos, board)
    budget = continue_share * sum(weights)
    out = [0.0] * len(combos)
    for i in order:
        if budget <= 1e-12:
            break
        take = min(weights[i], budget)
        out[i] = take
        budget -= take
    return out
