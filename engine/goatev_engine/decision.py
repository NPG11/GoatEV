"""
decision.py — the coach's brain: Scenario in, best play + every number out.

    1. Check the hand is possible                       (scenario.py)
    2. Build villain's range, remove blocked cards       (villains.py, ranges.py)
    3. Hero's equity vs each villain combo               (equity.py)
    4. List hero's options and score each one's EV       (ev.py, calling.py)
    5. Pick the highest EV; flag it "close" if the runner-up is near
    6. Return everything, so the explanation (Step 5) can only use real numbers

Folding is always worth $0. Every other option is measured against that.
"""

from dataclasses import dataclass, field

from .calling import combo_class, continuing_weights, max_fold_share
from .ranges import combo_count
from .strength import chen_score
from .equity import equity_by_combo, weighted_equity
from .ev import ev_call, ev_raise
from .numbers import call_amount, effective_stack, pot_odds, spr
from .ranges import range_percent, range_to_combos
from .scenario import Scenario
from .villains import get_profile, villain_range

# --- tunable settings ----------------------------------------------------------

FLOP_BET_SIZES = (0.33, 0.5, 0.75)   # fractions of the pot, when hero can bet
PREFLOP_RAISE_TO_BB = (4, 6)         # raising a limper: to 4 BB or 6 BB
RAISE_MULTIPLIER = 3                 # facing a bet: raise to 3x their bet
ALLIN_SPR = 4                        # only consider all-in when SPR is this low...
ALLIN_SHARE = 0.5                    # ...or the raise is already half our stack
CLOSE_BB = 0.5                       # options within 0.5 BB of each other = "close"

# Fold rates in villains.py are for a ~half-pot bet. Bigger bets get more
# folds, smaller bets fewer, but never more than 40% away from the base.
REFERENCE_SIZE = 0.5
SIZE_EXPONENT = 0.35
MAX_FOLD = 0.95

# EQUITY REALIZATION: preflop, the hand isn't over after a call - three more
# streets follow. Players only "cash in" part of their raw equity, less when
# out of position (acting first after the flop is a real disadvantage).
PREFLOP_REALIZATION = {"in_position": 0.9, "out_of_position": 0.75}
# ...and it depends on the hand: suited, connected, high cards play well after
# the flop; junk like 72o doesn't. Scaled by Chen score from 0.75x (worst) to 1.1x (AA).
PLAYABILITY_MIN, PLAYABILITY_MAX = 0.75, 1.10
POSTFLOP_ORDER = ("SB", "BB", "UTG", "UTG1", "MP", "LJ", "HJ", "CO", "BTN")

LIMITATIONS = (
    "One street only: after a call, the hand is treated as going straight to "
    "showdown (no extra money won or lost on later streets). Preflop this is "
    "softened with an equity-realization factor.",
    "Preflop, if villain 4-bets hero's 3-bet, hero is assumed to fold.",
    "Villain's flop bet does not narrow their range yet; their full preflop "
    "range is used.",
    "After hero bets or raises, villain only folds or calls (no re-raises).",
    "Villain fold rates are estimates for this player type, not measured stats.",
)


@dataclass(frozen=True)
class Option:
    action: str                 # fold, check, call, bet, raise, allin
    amount: float               # chips hero puts in now
    ev: float                   # average profit vs folding, in chips
    fold_pct: float | None = None
    equity_when_called: float | None = None

    def label(self, big_blind: float) -> str:
        if self.action in ("fold", "check"):
            return self.action
        return f"{self.action} ${self.amount:g} ({self.amount / big_blind:g} BB)"


@dataclass
class Decision:
    best: Option                # the recommendation
    options: list[Option]       # every option that was scored
    close: bool                 # True if another option is within CLOSE_BB of the top EV
    numbers: dict               # every number used, for the explanation step
    highest_ev: Option          # the single highest-EV option (can differ from best when close)
    limitations: tuple[str, ...] = field(default=LIMITATIONS)


# --- helpers ---------------------------------------------------------------------

def _hero_posted(s: Scenario) -> float:
    """Chips hero already put in on THIS street (only blinds, preflop)."""
    if s.street != "preflop":
        return 0.0
    return {"SB": s.small_blind, "BB": s.big_blind}.get(s.hero_position, 0.0)


def _base_fold(s: Scenario, profile) -> float:
    if s.street == "preflop":
        return profile.fold_to_3bet
    return profile.fold_to_cbet if s.to_call == 0 else profile.fold_to_raise


def in_position(s: Scenario) -> bool:
    """True if hero acts AFTER villain on the flop, turn and river."""
    return POSTFLOP_ORDER.index(s.hero_position) > POSTFLOP_ORDER.index(s.villain_position)


def playability(hero_cards: list[str]) -> float:
    """0.75 (72o) ... 1.10 (AA), from the hand's Chen score."""
    worst, best = chen_score("72o"), chen_score("AA")
    score = chen_score(combo_class(tuple(hero_cards)))
    share = (score - worst) / (best - worst)
    return PLAYABILITY_MIN + share * (PLAYABILITY_MAX - PLAYABILITY_MIN)


def realization(s: Scenario) -> float:
    """Share of raw equity hero actually cashes in (1.0 on the flop in v1)."""
    if s.street != "preflop":
        return 1.0
    base = PREFLOP_REALIZATION["in_position" if in_position(s) else "out_of_position"]
    return base * playability(s.hero_cards)


def fold_chance(base: float, pot: float, to_call: float, risk: float, cap: float,
                preflop: bool = False) -> float:
    """Villain's fold %, adjusted for bet size and capped by what they can fold.
    Preflop the base rate already assumes a standard 3-bet size: no size adjustment."""
    if preflop:
        return min(base, cap)
    size = (risk - to_call) / (pot + to_call)       # bet as a fraction of the pot
    adjusted = base * (size / REFERENCE_SIZE) ** SIZE_EXPONENT
    adjusted = max(base * 0.6, min(adjusted, base * 1.4, MAX_FOLD))
    return min(adjusted, cap)


# --- the decider --------------------------------------------------------------------

def decide(s: Scenario, *, samples: int = 200, seed: int = 0) -> Decision:
    s.validate()
    profile = get_profile(s.villain_type)

    # 2. villain's range, minus cards we can see
    rng = villain_range(s.villain_type, s.villain_position, s.villain_action)
    combos, weights = range_to_combos(rng, s.hero_cards + s.board)
    if not combos:
        raise ValueError("every hand in villain's range is blocked")

    # 3. equity
    per_combo = equity_by_combo(s.hero_cards, combos, s.board, samples=samples, seed=seed)
    equity = weighted_equity(per_combo, weights)
    fold_cap = max_fold_share(combos, weights, s.board)
    base_fold = _base_fold(s, profile)

    eff = effective_stack(s.hero_stack, s.villain_stack)
    stack_to_pot = spr(eff, s.pot)
    posted = _hero_posted(s)
    real = realization(s)
    preflop = s.street == "preflop"

    # Preflop, an opener who faces hero's 3-bet sometimes 4-bets (from the
    # Step 3 charts). Hero then folds. Those are their very strongest hands.
    reraise = 0.0
    if preflop and s.villain_action == "open":
        fourbet = villain_range(s.villain_type, s.villain_position, "4bet")
        reraise = combo_count(fourbet, s.hero_cards) / sum(weights)

    def aggressive(action: str, risk: float) -> Option:
        fold = fold_chance(base_fold, s.pot, s.to_call, risk, fold_cap, preflop)
        rr = min(reraise, 1 - fold)
        if action == "allin":
            rr = 0.0       # nothing left to re-raise; those hands just call
        # Hands that call = the strongest (1 - fold) share, minus the top `rr` share
        cont = continuing_weights(combos, weights, s.board, 1 - fold)
        top = continuing_weights(combos, weights, s.board, rr)
        called = [c - t for c, t in zip(cont, top)]
        eq_called = weighted_equity(per_combo, called) if sum(called) > 1e-9 else equity
        ev = ev_raise(s.pot, s.to_call, risk, fold, eq_called * real,
                      s.villain_stack, reraise_pct=rr)
        return Option(action, round(risk, 2), ev, fold, eq_called)

    # 4. options
    options: list[Option] = []
    allin_ok = stack_to_pot <= ALLIN_SPR

    if s.to_call > 0:
        options.append(Option("fold", 0.0, 0.0))
        call = call_amount(s.to_call, s.hero_stack)
        pot_if_called = s.pot - (s.to_call - call)   # short call: excess goes back
        options.append(Option("call", call, ev_call(pot_if_called, call, equity * real)))

        if s.hero_stack > call and s.villain_stack > 0:
            raise_to = RAISE_MULTIPLIER * (s.to_call + posted)
            risk = raise_to - posted
            if risk < s.hero_stack:
                options.append(aggressive("raise", risk))
                allin_ok = allin_ok or risk >= ALLIN_SHARE * s.hero_stack
            else:
                allin_ok = True
            if allin_ok:
                options.append(aggressive("allin", s.hero_stack))
    else:
        options.append(Option("check", 0.0, equity * real * s.pot))
        if s.street == "preflop":
            sizes = [bb * s.big_blind - posted for bb in PREFLOP_RAISE_TO_BB]
            kind = "raise"
        else:
            sizes = [round(f * s.pot, 2) for f in FLOP_BET_SIZES]
            kind = "bet"
        for risk in sizes:
            if 0 < risk < s.hero_stack:
                options.append(aggressive(kind, risk))
        if allin_ok and s.hero_stack > 0:
            options.append(aggressive("allin", s.hero_stack))

    # 5. pick the best. If several options are within CLOSE_BB of the top EV,
    #    they're basically equal - recommend the one that risks the least money
    #    (same average profit, smaller swings).
    ranked = sorted(options, key=lambda o: o.ev, reverse=True)
    highest = ranked[0]
    near_top = [o for o in ranked if highest.ev - o.ev < CLOSE_BB * s.big_blind]
    best = min(near_top, key=lambda o: o.amount)
    close = len(near_top) > 1

    # 6. every number, for the explanation step
    numbers = {
        "street": s.street,
        "pot": s.pot,
        "to_call": s.to_call,
        "big_blind": s.big_blind,
        "equity": equity,
        "realization": real,
        "in_position": in_position(s),
        "pot_odds": pot_odds(s.pot, s.to_call),
        "effective_stack": eff,
        "spr": stack_to_pot,
        "villain_type": profile.label,
        "villain_range_pct": range_percent(rng),
        "villain_combos": sum(weights),
        "villain_base_fold": base_fold,
        "villain_max_fold": fold_cap,
    }
    return Decision(best, options, close, numbers, highest)
