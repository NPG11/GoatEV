"""
facts.py — turn the engine's Decision into a FACT SHEET for the explanation.

The fact sheet is the ONLY source of numbers the explanation may use.
Every number is pre-rounded exactly as it should be shown to the user,
so Claude never has to (and is told never to) do its own math.

It also produces the set of "allowed numbers" that the checker in
explain.py compares Claude's text against.
"""

from .decision import Decision
from .ev import breakeven_fold_pct
from .scenario import Scenario


def pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def dollars(x: float) -> str:
    sign = "-" if x < 0 else ""
    return f"{sign}${abs(x):.2f}".replace(".00", "")


def bb(x: float, big_blind: float) -> str:
    return f"{x / big_blind:.1f} BB".replace(".0 BB", " BB")


def _option_name(action: str, amount: float, big_blind: float) -> str:
    if action in ("fold", "check"):
        return action
    verb = {"call": "call", "bet": "bet", "raise": "raise to", "allin": "go all-in for"}[action]
    return f"{verb} {dollars(amount)}"


def build_facts(s: Scenario, d: Decision) -> dict:
    """Everything the explanation may say, as display-ready strings."""
    n = d.numbers
    bbv = s.big_blind
    ranked = sorted(d.options, key=lambda o: o.ev, reverse=True)

    options = []
    for o in ranked:
        row = {
            "option": _option_name(o.action, o.amount, bbv),
            "puts_in": f"{dollars(o.amount)} ({bb(o.amount, bbv)})",
            "ev": f"{dollars(o.ev)} ({bb(o.ev, bbv)})",
        }
        if o.fold_pct is not None:
            row["villain_folds"] = pct(o.fold_pct)
            row["your_equity_when_called"] = pct(o.equity_when_called)
            # How often this bet would have to work if it had 0% equity when called
            row["folds_needed_for_pure_bluff"] = pct(breakeven_fold_pct(s.pot, o.amount))
        options.append(row)

    best = d.best
    runner_up = next((o for o in ranked if o is not best), None)

    facts = {
        "hand": {
            "street": s.street,
            "your_cards": " ".join(s.hero_cards),
            "board": " ".join(s.board) if s.board else "none yet (preflop)",
            "your_position": s.hero_position,
            "villain_position": s.villain_position,
            "villain_type": n["villain_type"],
            "villain_preflop_action": s.villain_action,
            "stakes": f"${s.small_blind:g}/${s.big_blind:g}",
        },
        "money": {
            "pot": f"{dollars(s.pot)} ({bb(s.pot, bbv)})",
            "to_call": f"{dollars(s.to_call)} ({bb(s.to_call, bbv)})",
            "effective_stack": f"{dollars(n['effective_stack'])} ({bb(n['effective_stack'], bbv)})",
            "spr": f"{n['spr']:.1f}",
        },
        "math": {
            "your_equity": pct(n["equity"]),
            "equity_needed_to_call": pct(n["pot_odds"]) if s.to_call > 0 else "n/a (no bet to call)",
            "villain_range_size": pct(n["villain_range_pct"]),
            "villain_combos_after_blockers": f"{n['villain_combos']:.0f}",
            "villain_usual_fold_rate": pct(n["villain_base_fold"]),
            "villain_most_they_can_fold": pct(n["villain_max_fold"]),
        },
        "options_best_first": options,
        "recommendation": {
            "play": _option_name(best.action, best.amount, bbv),
            "ev": f"{dollars(best.ev)} ({bb(best.ev, bbv)})",
            "close_spot": d.close,
        },
    }
    if s.street == "preflop":
        facts["math"]["equity_you_realize"] = pct(n["realization"])
        facts["math"]["in_position"] = n["in_position"]
    if runner_up is not None:
        facts["recommendation"]["edge_over_next_best"] = (
            f"{dollars(best.ev - runner_up.ev)} ({bb(best.ev - runner_up.ev, bbv)})")
        facts["recommendation"]["next_best"] = _option_name(runner_up.action, runner_up.amount, bbv)
    if d.close and d.highest_ev is not best:
        facts["recommendation"]["note"] = (
            f"{_option_name(d.highest_ev.action, d.highest_ev.amount, bbv)} has a slightly "
            f"higher EV ({dollars(d.highest_ev.ev)}), but the gap is under 0.5 BB, "
            f"so the lower-risk play is recommended.")
    return facts


def allowed_numbers(facts: dict) -> set[float]:
    """Every number that appears anywhere in the fact sheet."""
    import re
    found: set[float] = set()

    def walk(x):
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, str):
            for m in re.finditer(r"\d+(?:\.\d+)?", x):
                found.add(float(m.group()))
        elif isinstance(x, (int, float)) and not isinstance(x, bool):
            found.add(float(x))

    walk(facts)
    return found
