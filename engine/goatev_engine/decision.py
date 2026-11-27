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

from .calling import (
    combo_class, continuing_weights, hand_category, has_flush_draw,
    has_open_ended_draw, max_fold_share, strength_order,
)
from .ranges import combo_count
from .strength import chen_score
from .equity import equity_by_combo, weighted_equity
from .ev import breakeven_fold_pct, ev_call, ev_raise, ev_vs_shove
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
    "Later streets are estimated, not simulated: flop calls get an implied-odds "
    "bonus for strong draws and a reverse-implied-odds penalty for weak pairs, "
    "and preflop uses an equity-realization factor. There is no full turn/river "
    "game tree.",
    "When villain re-raises hero's bet or raise (a flop raise or a preflop "
    "4-bet), it is treated as all-in, and hero takes the better of calling "
    "or folding.",
    "Villain's flop bet or check narrows their range using estimated betting "
    "frequencies for each kind of hand (strong, top pair, draw, weak pair, air).",
    "Villain fold rates are estimates for this player type, not measured stats. "
    "Each bet shows the folds it needs, the advice shows how far the estimate "
    "can be off before it changes, and you can override the fold rate.",
)


@dataclass(frozen=True)
class Option:
    action: str                 # fold, check, call, bet, raise, allin
    amount: float               # chips hero puts in now
    ev: float                   # average profit vs folding, in chips
    fold_pct: float | None = None
    equity_when_called: float | None = None
    breakeven_fold: float | None = None    # folds needed if this were a pure bluff
    reraise_pct: float | None = None       # chance villain re-raises (all-in)
    vs_reraise: str | None = None          # hero's best answer to it: "call" or "fold"

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


def villain_flop_action(s: Scenario) -> str | None:
    """What villain did on THIS flop, worked out from the spot:
    facing a bet -> 'bet'; hero in position with nothing to call -> 'check';
    otherwise villain hasn't acted yet -> None."""
    if s.street != "flop":
        return None
    if s.to_call > 0:
        return "bet"
    return "check" if in_position(s) else None


def narrow_by_flop_action(combos, weights, board, profile, action):
    """Multiply each hand's weight by how likely villain is to have taken
    this action with it. A Nit who bets is mostly strong; a Maniac who bets
    could have anything."""
    if action is None:
        return combos, weights
    kept_c, kept_w = [], []
    for c, w in zip(combos, weights):
        p_bet = profile.flop_bet[hand_category(c, board)]
        w2 = w * (p_bet if action == "bet" else 1 - p_bet)
        if w2 > 1e-9:
            kept_c.append(c)
            kept_w.append(w2)
    return kept_c, kept_w


FLUSH_DRAW_OUTS, STRAIGHT_DRAW_OUTS, COMBO_DRAW_OUTS = 9, 8, 15
UNSEEN_ON_TURN = 47    # 52 - your 2 cards - 3 on the flop


def hero_outs(s: Scenario) -> int:
    """Outs for a strong draw: flush draw 9, open-ended straight draw 8, both 15."""
    hand = tuple(s.hero_cards)
    flush = has_flush_draw(hand, s.board)
    straight = has_open_ended_draw(hand, s.board)
    if flush and straight:
        return COMBO_DRAW_OUTS
    return FLUSH_DRAW_OUTS if flush else STRAIGHT_DRAW_OUTS if straight else 0


def future_streets(s: Scenario, profile, equity: float, call: float) -> dict:
    """Money expected to change hands AFTER a flop call (turn and river).

    implied_bonus    with a draw: hit on the turn (outs / 47) x how much this
                     villain type pays off x one pot-size bet later.
    reverse_penalty  with a weak pair: later bets cost you when you're behind
                     and pay you when you're ahead, so the NET is
                     (chance behind - chance ahead) x how often this villain
                     keeps betting x one pot-size bet later - and only when
                     you're behind more often than ahead.
    "One pot-size bet later" is capped by the chips left behind.
    """
    out = {"hero_hand_type": None, "outs": 0, "implied_bonus": 0.0, "reverse_penalty": 0.0}
    if s.street != "flop" or call <= 0:
        return out
    hero_type = hand_category(tuple(s.hero_cards), s.board)
    out["hero_hand_type"] = hero_type
    pot_after = s.pot + call
    behind = min(s.hero_stack - call, s.villain_stack)
    later_bet = max(0.0, min(behind, pot_after))

    if hero_type == "draw":
        out["outs"] = hero_outs(s)
        out["implied_bonus"] = out["outs"] / UNSEEN_ON_TURN * profile.payoff_rate * later_bet
    elif hero_type == "weak_pair":
        behind_minus_ahead = (1 - equity) - equity
        out["reverse_penalty"] = max(0.0, behind_minus_ahead) * profile.barrel_rate * later_bet
    return out


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


AGGRESSIVE = {"bet", "raise", "allin"}


def pick_best(options: list[Option], big_blind: float) -> tuple[Option, Option, bool]:
    """(recommended, highest_ev, close). Within CLOSE_BB of the top EV the
    options are basically equal - recommend the one that risks the least
    (same average profit, smaller swings)."""
    ranked = sorted(options, key=lambda o: o.ev, reverse=True)
    highest = ranked[0]
    near_top = [o for o in ranked if highest.ev - o.ev < CLOSE_BB * big_blind]
    return min(near_top, key=lambda o: o.amount), highest, len(near_top) > 1


# --- the decider --------------------------------------------------------------------

def decide(s: Scenario, *, samples: int = 200, seed: int = 0,
           fold_override: float | None = None) -> Decision:
    """fold_override: your own read on how often villain folds to a bet/raise
    (0..1). Replaces the villain type's estimate."""
    s.validate()
    if fold_override is not None and not 0 <= fold_override <= 1:
        raise ValueError("fold_override must be between 0 and 1")
    profile = get_profile(s.villain_type)

    # 2. villain's range, minus cards we can see
    rng = villain_range(s.villain_type, s.villain_position, s.villain_action)
    combos, weights = range_to_combos(rng, s.hero_cards + s.board)
    if not combos:
        raise ValueError("every hand in villain's range is blocked")
    combos_before = sum(weights)

    # 2b. what villain did on the flop narrows the range further
    flop_action = villain_flop_action(s)
    combos, weights = narrow_by_flop_action(combos, weights, s.board, profile, flop_action)

    # 3. equity
    per_combo = equity_by_combo(s.hero_cards, combos, s.board, samples=samples, seed=seed)
    equity = weighted_equity(per_combo, weights)
    fold_cap = max_fold_share(combos, weights, s.board)
    base_fold = fold_override if fold_override is not None else _base_fold(s, profile)
    order = strength_order(combos, s.board)   # villain's hands, strongest first

    eff = effective_stack(s.hero_stack, s.villain_stack)
    stack_to_pot = spr(eff, s.pot)
    posted = _hero_posted(s)
    real = realization(s)
    preflop = s.street == "preflop"

    # Preflop, an opener who faces hero's 3-bet sometimes 4-bets (from the
    # Step 3 charts). Those are their very strongest hands.
    reraise = 0.0
    if preflop and s.villain_action == "open":
        fourbet = villain_range(s.villain_type, s.villain_position, "4bet")
        reraise = combo_count(fourbet, s.hero_cards) / sum(weights)

    def aggressive(action: str, risk: float, base: float | None = None) -> Option:
        b = base_fold if base is None else base
        fold = fold_chance(b, s.pot, s.to_call, risk, fold_cap, preflop)

        # Re-raises: preflop from the 4-bet chart; on the flop, the top
        # `flop_reraise` share of the hands that continue.
        if preflop:
            rr = min(reraise, 1 - fold)
        else:
            rr = profile.flop_reraise * (1 - fold)
        if action == "allin" or s.villain_stack <= risk - s.to_call:
            rr = 0.0       # nothing left to re-raise with; those hands just call

        # Hands that call = the strongest (1 - fold) share, minus the top `rr` share
        cont = continuing_weights(combos, weights, s.board, 1 - fold, order)
        top = continuing_weights(combos, weights, s.board, rr, order)
        called = [c - t for c, t in zip(cont, top)]
        eq_called = weighted_equity(per_combo, called) if sum(called) > 1e-9 else equity

        # When villain re-raises (treated as all-in), hero calls or folds - whichever is better.
        rr_value, answer = None, None
        if rr > 0:
            eq_rr = weighted_equity(per_combo, top)
            rr_value, answer = ev_vs_shove(s.pot, s.to_call, risk, s.hero_stack,
                                           s.villain_stack, eq_rr)

        ev = ev_raise(s.pot, s.to_call, risk, fold, eq_called * real,
                      s.villain_stack, reraise_pct=rr, reraise_value=rr_value)
        return Option(action, round(risk, 2), ev, fold, eq_called,
                      breakeven_fold_pct(s.pot, risk), rr, answer)

    # 4. options
    options: list[Option] = []
    allin_ok = stack_to_pot <= ALLIN_SPR

    future = future_streets(s, profile, equity, call_amount(s.to_call, s.hero_stack))

    if s.to_call > 0:
        options.append(Option("fold", 0.0, 0.0))
        call = call_amount(s.to_call, s.hero_stack)
        pot_if_called = s.pot - (s.to_call - call)   # short call: excess goes back
        call_ev = (ev_call(pot_if_called, call, equity * real)
                   + future["implied_bonus"] - future["reverse_penalty"])
        options.append(Option("call", call, call_ev))

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

    # 5. pick the best
    best, highest, close = pick_best(options, s.big_blind)

    # 5b. how much does the answer depend on our fold-rate guess?
    #     Re-score at every fold rate from 0% to 95% and find where the
    #     recommendation switches between aggressive (bet/raise) and passive.
    def aggressive_wins_at(b: float) -> bool:
        rescored = [aggressive(o.action, o.amount, b) if o.action in AGGRESSIVE else o
                    for o in options]
        return pick_best(rescored, s.big_blind)[0].action in AGGRESSIVE

    sensitivity = None
    if any(o.action in AGGRESSIVE for o in options):
        grid = [i / 100 for i in range(0, 96)]
        if best.action in AGGRESSIVE:
            flips = [b for b in grid if b < base_fold and not aggressive_wins_at(b)]
            sensitivity = {"best_is_aggressive": True,
                           "holds_if_folds_at_least": (max(flips) + 0.01) if flips else 0.0}
        else:
            flips = [b for b in grid if b > base_fold and aggressive_wins_at(b)]
            sensitivity = {"best_is_aggressive": False,
                           "aggression_wins_if_folds_more_than": min(flips) if flips else None}

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
        "villain_combos_before_flop_action": combos_before,
        "villain_flop_action": flop_action,
        "villain_base_fold": base_fold,
        "fold_rate_source": "your override" if fold_override is not None else "estimate",
        "villain_max_fold": fold_cap,
        "fold_sensitivity": sensitivity,
        "hero_hand_type": future["hero_hand_type"],
        "hero_outs": future["outs"],
        "implied_odds_bonus": future["implied_bonus"],
        "reverse_implied_penalty": future["reverse_penalty"],
    }
    return Decision(best, options, close, numbers, highest)
