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


def fold_sensitivity_sentence(n: dict) -> str | None:
    """How far off our fold-rate guess can be before the advice changes."""
    sens = n.get("fold_sensitivity")
    if not sens:
        return None
    est = pct(n["villain_base_fold"])
    if sens["best_is_aggressive"]:
        need = sens["holds_if_folds_at_least"]
        if need <= 0:
            return f"Betting is best even if villain never folds (estimated fold rate {est})."
        return (f"This holds as long as villain folds at least {pct(need)} "
                f"(estimated fold rate {est}).")
    more = sens["aggression_wins_if_folds_more_than"]
    if more is None:
        return f"Betting or raising would not be better even if villain folded very often."
    return (f"Betting or raising would only become better if villain folded more "
            f"than {pct(more)} (estimated fold rate {est}).")


_HAND_NAMES = {1: "a straight flush", 2: "four of a kind", 3: "a full house",
               4: "a flush", 5: "a straight", 6: "three of a kind", 7: "two pair",
               8: "one pair", 9: "high card only"}


def describe_hero_hand(s: Scenario) -> str:
    """Exact, engine-checked description of hero's hand on this board, so the
    explanation never has to (or is allowed to) work it out itself."""
    from treys import Card, Evaluator
    from .calling import _made_category, has_flush_draw, has_open_ended_draw
    from .scenario import RANKS

    hand = tuple(s.hero_cards)
    ev = Evaluator()
    made = _HAND_NAMES[ev.get_rank_class(ev.evaluate(
        [Card.new(c) for c in s.board], [Card.new(c) for c in hand]))]
    parts = [made]
    cat = _made_category(hand, s.board)
    if cat == "top_pair":
        parts.append("an overpair" if hand[0][0] == hand[1][0] else "top pair")
    elif cat == "weak_pair":
        parts.append("a pair below the top board card")
    if len(s.board) < 5:
        if has_flush_draw(hand, s.board):
            parts.append("a flush draw (9 outs)")
        if has_open_ended_draw(hand, s.board):
            parts.append("an open-ended straight draw (8 outs)")
    top_board = max(RANKS.index(c[0]) for c in s.board)
    overs = [c for c in hand if RANKS.index(c[0]) > top_board]
    parts.append(f"{len(overs)} overcard{'s' if len(overs) != 1 else ''} to the board")
    return ", ".join(parts)


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
            if o.reraise_pct:
                row["villain_reraises_all_in"] = pct(o.reraise_pct)
                row["your_best_answer_to_a_reraise"] = o.vs_reraise
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
            "fold_rate_source": n["fold_rate_source"],
            "villain_most_they_can_fold": pct(n["villain_max_fold"]),
        },
        "options_best_first": options,
        "recommendation": {
            "play": _option_name(best.action, best.amount, bbv),
            "ev": f"{dollars(best.ev)} ({bb(best.ev, bbv)})",
            "close_spot": d.close,
        },
    }
    if s.board:
        facts["hand"]["your_hand_right_now"] = describe_hero_hand(s)
    if n.get("implied_odds_bonus"):
        facts["math"]["your_outs"] = f"{n['hero_outs']}"
        facts["math"]["implied_odds_bonus_on_call"] = (
            f"{dollars(n['implied_odds_bonus'])} ({bb(n['implied_odds_bonus'], bbv)})")
    if n.get("reverse_implied_penalty"):
        facts["math"]["reverse_implied_odds_penalty_on_call"] = (
            f"{dollars(n['reverse_implied_penalty'])} ({bb(n['reverse_implied_penalty'], bbv)})")
    sensitivity = fold_sensitivity_sentence(n)
    if sensitivity:
        facts["recommendation"]["how_sure"] = sensitivity
    if n.get("villain_flop_action"):
        facts["hand"]["villain_flop_action"] = n["villain_flop_action"]
    if s.street == "preflop":
        facts["math"]["equity_you_realize"] = pct(n["realization"])
        facts["math"]["in_position"] = n["in_position"]
    if runner_up is not None and best is d.highest_ev:
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
