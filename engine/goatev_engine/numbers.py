"""
numbers.py — the basic arithmetic of a poker decision.

These are pure functions: numbers in, numbers out, no randomness.
Everything here is cheap and exact, so the coach can quote these
numbers and the LLM check can verify them later.
"""

from .scenario import Scenario


def call_amount(to_call: float, hero_stack: float) -> float:
    """What hero ACTUALLY puts in when calling.
    If the bet is bigger than hero's stack, hero calls all-in for less."""
    return min(to_call, hero_stack)


def pot_odds(pot: float, to_call: float) -> float:
    """Equity hero needs to break even on a call, as a fraction 0..1.

        required = call / (pot + call)

    `pot` already includes villain's bet. Example: pot $30 (incl. a $10 bet),
    call $10 -> 10 / (30 + 10) = 0.25 -> hero needs 25% equity.
    Returns 0.0 when there's nothing to call (a free check).
    """
    if to_call <= 0:
        return 0.0
    return to_call / (pot + to_call)


def pot_odds_ratio(pot: float, to_call: float) -> float:
    """The same idea as 'X to 1': pot / call.
    $30 pot, $10 call -> 3.0 ("3 to 1")."""
    if to_call <= 0:
        return float("inf")
    return pot / to_call


def effective_stack(hero_stack: float, villain_stack: float) -> float:
    """The most that can be won or lost between these two players:
    the SMALLER of the two stacks."""
    return min(hero_stack, villain_stack)


def spr(eff_stack: float, pot: float) -> float:
    """Stack-to-pot ratio: effective stack / pot.
    Low SPR (< ~4) = easy to commit with top pair; high SPR = be careful."""
    if pot <= 0:
        raise ValueError("pot must be > 0 to compute SPR")
    return eff_stack / pot


def spr_after_call(s: Scenario) -> float:
    """SPR hero will face on the NEXT street if hero just calls now."""
    call = call_amount(s.to_call, s.hero_stack)
    new_pot = s.pot + call
    eff = effective_stack(s.hero_stack - call, s.villain_stack)
    return spr(eff, new_pot)
