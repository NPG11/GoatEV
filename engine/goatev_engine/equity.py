"""
equity.py — how often does hero's hand win?

EQUITY = hero's share of the pot if all remaining board cards were dealt
         and we averaged over every possible way they could come.

    equity = (wins + ties / 2) / total_runouts

A tie splits the pot, so it counts as half a win.

Two ways to compute it:

  EXACT        Try every possible runout. Used when few cards are left
               to come. On the flop, 2 cards must come from 45 unseen
               cards -> C(45, 2) = 990 runouts. Fast and perfectly exact.

  MONTE CARLO  Deal random runouts many times and count. Used preflop,
               where 5 cards must come -> C(48, 5) = 1,712,304 runouts
               per villain hand: too slow to try them all in Python.
               With 20,000 samples the answer is within about +-0.5%.

Villain can be one exact hand ("QhQc") or a RANGE: a list of hands they
might hold. Hands that use a card we can already see are removed first
(that's "card removal" / blockers).
"""

import random
from dataclasses import dataclass
from itertools import combinations
from math import comb

from treys import Card, Evaluator

from .scenario import RANKS, SUITS, is_valid_card

_EVALUATOR = Evaluator()

FULL_DECK: tuple[str, ...] = tuple(r + s for r in RANKS for s in SUITS)

DEFAULT_ITERATIONS = 20_000

Combo = tuple[str, str]   # one specific 2-card hand, e.g. ("Qh", "Qc")


@dataclass(frozen=True)
class EquityResult:
    wins: float
    ties: float
    losses: float
    exact: bool          # True = every runout tried; False = Monte Carlo estimate
    combos_used: int     # villain hands left after removing blocked ones

    @property
    def total(self) -> float:
        return self.wins + self.ties + self.losses

    @property
    def equity(self) -> float:
        return (self.wins + self.ties / 2) / self.total

    @property
    def win_pct(self) -> float:
        return self.wins / self.total

    @property
    def tie_pct(self) -> float:
        return self.ties / self.total


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _check_known_cards(cards: list[str]) -> None:
    bad = [c for c in cards if not is_valid_card(c)]
    if bad:
        raise ValueError(f"invalid card(s): {bad}")
    dupes = sorted({c for c in cards if cards.count(c) > 1})
    if dupes:
        raise ValueError(f"duplicate card(s): {dupes}")


def _showdown(hero: list[int], villain: list[int], board: list[int]) -> int:
    """+1 hero wins, 0 tie, -1 hero loses.
    treys scores hands from 1 (royal flush) to 7462 (worst high card):
    LOWER IS BETTER."""
    h = _EVALUATOR.evaluate(board, hero)
    v = _EVALUATOR.evaluate(board, villain)
    return (h < v) - (h > v)


def remove_blocked(combos: list[Combo], dead: list[str]) -> list[Combo]:
    """Drop villain hands that need a card we can already see."""
    dead_set = set(dead)
    return [c for c in combos if c[0] not in dead_set and c[1] not in dead_set]


# ---------------------------------------------------------------------------
# Main API
# ---------------------------------------------------------------------------

def equity_vs_hand(
    hero: list[str],
    villain: list[str],
    board: list[str] = (),
    *,
    iterations: int = DEFAULT_ITERATIONS,
    seed: int | None = None,
) -> EquityResult:
    """Hero's equity against ONE known villain hand."""
    _check_known_cards(list(hero) + list(villain) + list(board))
    return equity_vs_range(hero, [tuple(villain)], board,
                           iterations=iterations, seed=seed)


def equity_vs_range(
    hero: list[str],
    villain_range: list[Combo],
    board: list[str] = (),
    *,
    weights: list[float] | None = None,
    iterations: int = DEFAULT_ITERATIONS,
    seed: int | None = None,
) -> EquityResult:
    """Hero's equity against a list of possible villain hands.

    weights: optional, one number per combo. A weight of 0.5 means
             "villain plays this hand half the time". Default: all 1.0.
    seed:    makes Monte Carlo repeatable (same seed -> same answer).
    """
    hero, board = list(hero), list(board)
    if len(hero) != 2:
        raise ValueError("hero needs exactly 2 cards")
    if len(board) > 5:
        raise ValueError("board can't have more than 5 cards")
    _check_known_cards(hero + board)

    if weights is None:
        weights = [1.0] * len(villain_range)
    if len(weights) != len(villain_range):
        raise ValueError("weights must have one number per combo")

    # 1. Card removal: throw out villain hands that collide with known cards.
    dead = hero + board
    kept = [(tuple(c), w) for c, w in zip(villain_range, weights)
            if w > 0 and remove_blocked([tuple(c)], dead)]
    for combo, _ in kept:
        _check_known_cards(list(combo))
    if not kept:
        raise ValueError("every villain hand is blocked by the known cards")

    cards_to_come = 5 - len(board)
    if cards_to_come <= 2:
        return _exact(hero, board, kept, cards_to_come)
    return _monte_carlo(hero, board, kept, cards_to_come, iterations, seed)


# ---------------------------------------------------------------------------
# The two engines
# ---------------------------------------------------------------------------

def _exact(hero, board, kept, cards_to_come) -> EquityResult:
    hero_t = [Card.new(c) for c in hero]
    board_t = [Card.new(c) for c in board]
    wins = ties = losses = 0.0

    for combo, weight in kept:
        villain_t = [Card.new(c) for c in combo]
        unseen = [Card.new(c) for c in FULL_DECK
                  if c not in hero and c not in board and c not in combo]
        runouts = list(combinations(unseen, cards_to_come))
        # Each villain hand counts by its weight, no matter how many runouts
        # it has, so split its weight evenly across them.
        share = weight / len(runouts)
        for runout in runouts:
            result = _showdown(hero_t, villain_t, board_t + list(runout))
            if result > 0:
                wins += share
            elif result == 0:
                ties += share
            else:
                losses += share

    return EquityResult(wins, ties, losses, exact=True, combos_used=len(kept))


def _monte_carlo(hero, board, kept, cards_to_come, iterations, seed) -> EquityResult:
    rng = random.Random(seed)
    hero_t = [Card.new(c) for c in hero]
    board_t = [Card.new(c) for c in board]
    combos = [c for c, _ in kept]
    weights = [w for _, w in kept]
    wins = ties = losses = 0

    for _ in range(iterations):
        # Pick a villain hand (likelier hands get picked more often)...
        combo = rng.choices(combos, weights=weights)[0]
        unseen = [c for c in FULL_DECK
                  if c not in hero and c not in board and c not in combo]
        # ...then deal the rest of the board at random.
        runout = [Card.new(c) for c in rng.sample(unseen, cards_to_come)]
        result = _showdown(hero_t, [Card.new(c) for c in combo], board_t + runout)
        if result > 0:
            wins += 1
        elif result == 0:
            ties += 1
        else:
            losses += 1

    return EquityResult(wins, ties, losses, exact=False, combos_used=len(kept))


# ---------------------------------------------------------------------------
# Equity against EACH villain combo (used by the decision engine)
# ---------------------------------------------------------------------------

_CARD_INT = {c: Card.new(c) for c in FULL_DECK}

# treys checks all 21 five-card hands inside every 7-card hand, so each
# showdown costs ~15 microseconds in Python. These keep decide() around a second.
DEFAULT_SAMPLES_PER_COMBO = 200
MAX_EXACT_SHOWDOWNS = 50_000    # ~50 combos on the flop; bigger ranges sample


def equity_by_combo(
    hero: list[str],
    combos: list[Combo],
    board: list[str] = (),
    *,
    samples: int = DEFAULT_SAMPLES_PER_COMBO,
    seed: int | None = None,
) -> list[float]:
    """Hero's equity against each combo separately, in the same order.

    Why: the decision engine needs equity against DIFFERENT slices of
    villain's range (all of it for a call, only the calling hands for a
    raise). With one number per combo, any slice is just a weighted
    average - no need to recompute.

    Exact when <= 2 cards are to come (flop) AND the work is small enough
    (MAX_EXACT_SHOWDOWNS). Otherwise `samples` random runouts per combo:
    each combo is a bit noisy, but averaged over hundreds of combos the
    range equity stays accurate.
    """
    hero, board = list(hero), list(board)
    _check_known_cards(hero + board)
    known = set(hero + board)
    hero_t = [_CARD_INT[c] for c in hero]
    board_t = [_CARD_INT[c] for c in board]
    to_come = 5 - len(board)
    runouts_each = comb(52 - len(known) - 2, to_come)
    exact = to_come <= 2 and len(combos) * runouts_each <= MAX_EXACT_SHOWDOWNS
    rng = random.Random(seed)
    hero_score_cache: dict[tuple, int] = {}   # runout -> hero's score (exact mode)

    out = []
    for combo in combos:
        if known & set(combo):
            raise ValueError(f"combo {combo} uses a known card")
        villain_t = [_CARD_INT[c] for c in combo]
        unseen = [_CARD_INT[c] for c in FULL_DECK if c not in known and c not in combo]

        if exact:
            runouts = combinations(unseen, to_come)
        else:
            runouts = (rng.sample(unseen, to_come) for _ in range(samples))

        score = n = 0.0
        for runout in runouts:
            full = board_t + list(runout)
            if exact:
                key = tuple(sorted(runout))
                h = hero_score_cache.get(key)
                if h is None:
                    h = hero_score_cache[key] = _EVALUATOR.evaluate(full, hero_t)
            else:
                h = _EVALUATOR.evaluate(full, hero_t)
            v = _EVALUATOR.evaluate(full, villain_t)
            score += 1.0 if h < v else 0.5 if h == v else 0.0
            n += 1
        out.append(score / n)
    return out


def weighted_equity(per_combo: list[float], weights: list[float]) -> float:
    """Average equity over a set of combos, each counted by its weight."""
    total = sum(weights)
    if total <= 0:
        raise ValueError("weights must add up to more than 0")
    return sum(e * w for e, w in zip(per_combo, weights)) / total
