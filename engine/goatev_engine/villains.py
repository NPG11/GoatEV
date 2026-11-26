"""
villains.py — villain types change what villain holds and how often they fold.

Each type has two kinds of numbers:

  WIDTH     how much wider or tighter than the baseline chart (charts.py)
            they play, per action. 1.0 = same as baseline, 0.5 = half as
            many hands, 2.0 = twice as many.
            Tighter -> drop the weakest hands first.
            Wider   -> add the next-strongest hands they don't have yet.

  FOLD      how often they give up when bet into or raised (0..1).
            Step 4 (the decision engine) uses these to judge bluffs.

The numbers are estimates of typical LIVE $1/$2 tendencies, not solver output.
They're all in one table below, so they're easy to tune later.

Limping (just calling the big blind instead of raising) is very common live.
A limp range = their opening range for that seat, reshaped by their limp
width, with premiums mostly removed (most players RAISE big hands; a few
trap by limping, so premiums keep a small weight).
"""

from dataclasses import dataclass

from .charts import OPEN, chart_range
from .ranges import Range, TOTAL_COMBOS, combo_count, hand_combos, parse_range
from .strength import hands_by_strength


@dataclass(frozen=True)
class VillainProfile:
    key: str
    label: str
    summary: str
    width: dict[str, float]     # action -> width factor
    fold_to_3bet: float         # preflop: folds after opening and facing a 3-bet
    fold_to_cbet: float         # flop: folds to a continuation bet
    fold_to_raise: float        # flop: folds after betting and getting raised


#                 open  call  3bet  call_3bet  4bet  limp
def _w(o, c, t, c3, f, lp):
    return {"open": o, "call": c, "3bet": t, "call_3bet": c3, "4bet": f, "limp": lp}


PROFILES: dict[str, VillainProfile] = {
    "unknown": VillainProfile(
        "unknown", "Unknown",
        "No reads yet. Assume a solid, standard player.",
        _w(1.0, 1.0, 1.0, 1.0, 1.0, 1.0),
        fold_to_3bet=0.55, fold_to_cbet=0.45, fold_to_raise=0.50,
    ),
    "nit": VillainProfile(
        "nit", "Nit",
        "Plays very few hands. When a nit raises, believe them.",
        _w(0.65, 0.6, 0.6, 0.8, 0.7, 0.7),
        fold_to_3bet=0.70, fold_to_cbet=0.55, fold_to_raise=0.70,
    ),
    "calling_station": VillainProfile(
        "calling_station", "Calling station",
        "Calls far too much, rarely raises, hates folding. Value bet, don't bluff.",
        _w(1.2, 2.5, 0.5, 2.0, 0.6, 1.5),
        fold_to_3bet=0.25, fold_to_cbet=0.20, fold_to_raise=0.25,
    ),
    "lag": VillainProfile(
        "lag", "LAG",
        "Loose-aggressive: plays many hands and raises a lot, but with a plan.",
        _w(1.4, 1.2, 2.0, 1.3, 1.5, 1.0),
        fold_to_3bet=0.45, fold_to_cbet=0.40, fold_to_raise=0.40,
    ),
    "maniac": VillainProfile(
        "maniac", "Maniac",
        "Raises and re-raises almost anything. Let them bluff; call down lighter.",
        _w(1.8, 1.6, 3.0, 1.5, 2.5, 1.0),   # maniacs raise rather than limp
        fold_to_3bet=0.30, fold_to_cbet=0.30, fold_to_raise=0.25,
    ),
}

# Big hands that most players raise rather than limp.
PREMIUMS = parse_range("TT+, AQs+, AKo")
TRAP_LIMP_WEIGHT = 0.15   # ...but ~15% of the time they limp them as a trap


def get_profile(villain_type: str) -> VillainProfile:
    if villain_type not in PROFILES:
        raise ValueError(f"unknown villain type '{villain_type}'")
    return PROFILES[villain_type]


# ---------------------------------------------------------------------------
# Reshaping a range
# ---------------------------------------------------------------------------

def reshape(rng: Range, factor: float) -> Range:
    """Make a range `factor` times as big (in combos), keeping it sensible.

    factor < 1: remove the WEAKEST hands first.
    factor > 1: add the STRONGEST missing hands first.
    The hand at the edge gets a partial weight so the size comes out exact.
    """
    if factor < 0:
        raise ValueError("factor can't be negative")
    out = dict(rng)
    current = combo_count(out)
    target = min(current * factor, TOTAL_COMBOS)
    order = hands_by_strength()

    if target < current:
        for hand in reversed(order):          # weakest first
            weight = out.get(hand, 0.0)
            if weight == 0:
                continue
            excess = current - target
            if excess <= 1e-9:
                break
            n = len(hand_combos(hand))
            if weight * n <= excess:
                del out[hand]
                current -= weight * n
            else:
                out[hand] = round(weight - excess / n, 4)
                current = target

    elif target > current:
        for hand in order:                    # strongest first
            weight = out.get(hand, 0.0)
            if weight >= 1:
                continue
            need = target - current
            if need <= 1e-9:
                break
            n = len(hand_combos(hand))
            if (1 - weight) * n <= need:
                out[hand] = 1.0
                current += (1 - weight) * n
            else:
                out[hand] = round(weight + need / n, 4)
                current = target

    return out


# ---------------------------------------------------------------------------
# Main API
# ---------------------------------------------------------------------------

def villain_range(villain_type: str, position: str, action: str) -> Range:
    """The range this type of villain has, after this action, from this seat.

    villain_range("nit", "CO", "open")  -> a tighter version of the CO open
    villain_range("calling_station", "BTN", "limp")
    """
    profile = get_profile(villain_type)

    if action == "limp":
        if position not in OPEN:
            raise ValueError(f"{position} can't 'limp' preflop in this model")
        base = reshape(chart_range(position, "open"), profile.width["limp"])
        for hand in PREMIUMS:
            if hand in base:
                base[hand] = min(base[hand], TRAP_LIMP_WEIGHT)
        return base

    base = chart_range(position, action)      # raises for impossible spots
    return reshape(base, profile.width[action])
