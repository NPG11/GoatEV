"""
charts.py — baseline preflop ranges for a solid, "normal" 9-max player.

A range depends on two things:

  POSITION  early seats play tight (many players still to act behind),
            late seats play wide (fewer players behind, position after the flop).
  ACTION    what villain did tells you which part of their hands they have:

    open       raised first into the pot                  -> their playable hands
    call       flat-called someone's open raise           -> medium hands
                                                             (best hands 3-bet, worst fold)
    3bet       re-raised an open                          -> strong hands + a few bluffs
    call_3bet  opened, then called a 3-bet                -> strong-but-not-best hands
    4bet       opened, then re-raised a 3-bet             -> premiums (+ rare bluff)

These are the "Unknown" villain. Step 3C bends them for Nit, Calling station,
LAG and Maniac.

v1 simplifications (on purpose, to keep it learnable):
  - 100 BB deep, raise-or-fold (no limping ranges yet).
  - call / 3bet ranges depend on villain's seat, not on WHO opened.
"""

from .ranges import Range, parse_range
from .scenario import POSITIONS

ACTIONS = ("open", "call", "3bet", "call_3bet", "4bet")

# ---------------------------------------------------------------------------
# Opening ranges (raise first in). Each seat contains the previous seat's range.
# ---------------------------------------------------------------------------

OPEN = {
    "UTG":  "77+, A9s+, A5s-A4s, KTs+, QTs+, JTs, T9s, AQo+, KQo",
    "UTG1": "66+, A8s+, A5s-A4s, KTs+, QTs+, JTs, T9s, AJo+, KQo",
    "MP":   "55+, A7s+, A5s-A3s, K9s+, Q9s+, J9s+, T9s, 98s, AJo+, KQo",
    "LJ":   "44+, A2s+, K9s+, Q9s+, J9s+, T8s+, 98s, 87s, ATo+, KJo+",
    "HJ":   "33+, A2s+, K8s+, Q9s+, J9s+, T8s+, 97s+, 87s, 76s, ATo+, KJo+, QJo",
    "CO":   "22+, A2s+, K6s+, Q8s+, J8s+, T8s+, 97s+, 86s+, 75s+, 65s, 54s, "
            "A8o+, KTo+, QTo+, JTo",
    "BTN":  "22+, A2s+, K2s+, Q5s+, J7s+, T7s+, 96s+, 85s+, 74s+, 64s+, 53s+, 43s, "
            "A2o+, K8o+, Q9o+, J9o+, T9o, 98o",
    "SB":   "22+, A2s+, K3s+, Q6s+, J7s+, T7s+, 96s+, 86s+, 75s+, 65s, 54s, "
            "A4o+, K9o+, Q9o+, J9o+, T9o",
    # BB never "opens": if everyone folds to the BB, the BB just wins the blinds.
}

# ---------------------------------------------------------------------------
# Flat-calling an open raise
# ---------------------------------------------------------------------------

_CALL_EARLY = "TT-66, AQs-AJs, KQs, QJs, JTs, AQo"
_CALL_LATE = ("TT-22, AQs-ATs, KQs-KTs, QJs-QTs, JTs, T9s, 98s, 87s, 76s, "
              "AQo-AJo, KQo")

CALL = {
    "UTG1": _CALL_EARLY,
    "MP":   _CALL_EARLY,
    "LJ":   _CALL_EARLY,
    "HJ":   _CALL_LATE,
    "CO":   _CALL_LATE,
    "BTN":  "JJ-22, AQs-A9s, KQs-K9s, QJs-Q9s, JTs-J9s, T9s-T8s, 98s-97s, "
            "87s-86s, 76s, 65s, 54s, AQo-ATo, KQo-KJo, QJo",
    "SB":   "TT-22, AQs-ATs, KQs, QJs, JTs, AQo",
    # BB already has 1 BB in the pot and closes the action -> defends widest.
    "BB":   "JJ-22, AQs-A2s, KQs-K5s, QJs-Q7s, JTs-J7s, T9s-T7s, 98s-96s, "
            "87s-85s, 76s-75s, 65s-64s, 54s, 43s, AQo-A8o, KQo-K9o, QJo-Q9o, "
            "JTo-J9o, T9o, 98o",
}

# ---------------------------------------------------------------------------
# 3-betting an open raise (value hands + some bluffs with blockers)
# ---------------------------------------------------------------------------

_3BET_IN_POSITION = "QQ+, AQs+, AKo, A5s-A4s, KQs:0.5, JTs:0.3"
_3BET_BLINDS = "JJ+, ATs+, KQs, AQo+, A5s-A2s, K9s:0.5, 76s:0.5, 65s:0.5"

THREE_BET = {pos: _3BET_IN_POSITION for pos in ("UTG1", "MP", "LJ", "HJ", "CO", "BTN")}
THREE_BET.update({"SB": _3BET_BLINDS, "BB": _3BET_BLINDS})

# ---------------------------------------------------------------------------
# Opener's response to a 3-bet (same for every opening seat in v1)
# ---------------------------------------------------------------------------

_CALL_3BET = "QQ-88, AQs-AJs, KQs, QJs, JTs, AKo:0.5, AQo:0.5"
_4BET = "KK+, AKs, QQ:0.5, AKo:0.5, A5s:0.5"

CALL_3BET = {pos: _CALL_3BET for pos in OPEN}
FOUR_BET = {pos: _4BET for pos in OPEN}

_CHARTS = {
    "open": OPEN,
    "call": CALL,
    "3bet": THREE_BET,
    "call_3bet": CALL_3BET,
    "4bet": FOUR_BET,
}


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------

def chart_text(position: str, action: str) -> str:
    """The range text for a seat + action. Raises if that combo can't happen."""
    if position not in POSITIONS:
        raise ValueError(f"unknown position '{position}'")
    if action not in _CHARTS:
        raise ValueError(f"unknown action '{action}' (use one of {ACTIONS})")
    chart = _CHARTS[action]
    if position not in chart:
        raise ValueError(f"{position} can't '{action}' preflop in this model")
    return chart[position]


def chart_range(position: str, action: str) -> Range:
    """Same as chart_text, but parsed into {hand class: weight}."""
    return parse_range(chart_text(position, action))
