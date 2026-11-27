"""Tests for Step 5. No real API calls: a fake client plays Claude's part."""

from types import SimpleNamespace

import pytest

from goatev_engine.decision import decide
from goatev_engine.explain import (
    MODEL, explain, find_bad_numbers, mentions_other_play, template_explanation,
)
from goatev_engine.facts import allowed_numbers, build_facts
from goatev_engine.scenario import Scenario

SPOT = Scenario(hero_position="BTN", villain_position="CO", villain_action="open",
                villain_type="nit", hero_stack=180, villain_stack=180, street="flop",
                hero_cards=["As", "Kd"], board=["Ah", "7c", "2d"], pot=30, to_call=10)


@pytest.fixture(scope="module")
def decision():
    return decide(SPOT, samples=60, seed=1)


@pytest.fixture(scope="module")
def facts(decision):
    return build_facts(SPOT, decision)


# --- a fake Claude ----------------------------------------------------------------

def reply(text, stop_reason="end_turn"):
    return SimpleNamespace(stop_reason=stop_reason,
                           content=[SimpleNamespace(type="text", text=text)])


class FakeClient:
    """Returns queued replies in order and records every request."""
    def __init__(self, *replies, error=None):
        self.replies = list(replies)
        self.calls = []
        self.error = error
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.replies.pop(0)


def good_text(f):
    m = f["math"]
    return (f"Your equity is {m['your_equity']} and you only need "
            f"{m['equity_needed_to_call']} to call. A nit folds a lot, "
            f"so raising wins the pot often. Rule of thumb: 1 in 4 is enough "
            f"against a half-pot bet.")


# --- fact sheet ---------------------------------------------------------------------

def test_fact_sheet_has_the_key_numbers(facts, decision):
    assert facts["math"]["your_equity"].endswith("%")
    assert facts["math"]["equity_needed_to_call"] == "25%"
    assert facts["money"]["pot"] == "$30 (15 BB)"
    assert len(facts["options_best_first"]) == len(decision.options)


def test_recommendation_matches_the_engine(facts, decision):
    first_word = {"fold": "fold", "check": "check", "call": "call", "bet": "bet",
                  "raise": "raise", "allin": "go"}[decision.best.action]
    assert facts["recommendation"]["play"].startswith(first_word)


def test_allowed_numbers_include_fact_values(facts):
    nums = allowed_numbers(facts)
    assert 30.0 in nums and 25.0 in nums


@pytest.mark.parametrize("cards,board,expected,not_expected", [
    (["Kc", "Qc"], ["As", "7c", "2c"], ["flush draw (9 outs)", "0 overcards"], ["pair"]),
    (["As", "Kd"], ["Ah", "7c", "2d"], ["one pair", "top pair"], ["draw"]),
    (["Ks", "Kd"], ["Qh", "7c", "2d"], ["an overpair"], ["top pair"]),
    (["8s", "8h"], ["Kd", "9c", "4s"], ["below the top board card"], ["overpair"]),
    (["9s", "8s"], ["7c", "6d", "2h"], ["open-ended straight draw (8 outs)", "2 overcards"], []),
])
def test_hero_hand_description_is_exact(cards, board, expected, not_expected):
    from goatev_engine.facts import describe_hero_hand
    s = Scenario(hero_position="BTN", villain_position="CO", street="flop",
                 hero_cards=cards, board=board, pot=20, to_call=0)
    text = describe_hero_hand(s)
    for e in expected:
        assert e in text
    for n in not_expected:
        assert n not in text


def test_fact_sheet_includes_hand_description_on_the_flop(facts):
    assert "top pair" in facts["hand"]["your_hand_right_now"]


# --- the checker ---------------------------------------------------------------------

def test_template_always_passes_the_checker(facts):
    assert find_bad_numbers(template_explanation(facts), facts) == []


def test_close_spot_never_shows_a_negative_edge():
    s = Scenario(hero_position="BTN", villain_position="CO", villain_action="open",
                 villain_type="nit", hero_stack=180, villain_stack=180, street="flop",
                 hero_cards=["Qs", "Jh"], board=["Ah", "7c", "2d"], pot=20, to_call=0)
    f = build_facts(s, decide(s, samples=60, seed=1))
    edge = f["recommendation"].get("edge_over_next_best", "")
    assert not edge.startswith("-")
    assert "how_sure" in f["recommendation"]


def test_invented_numbers_are_caught(facts):
    text = "Raise to $31.50 because you have 62.5% equity and a 44 BB edge."
    bad = find_bad_numbers(text, facts)
    assert "$31.50" in bad
    assert any(b.startswith("62.5") for b in bad)


def test_small_numbers_and_card_ranks_are_fine(facts):
    assert find_bad_numbers("On A-7-2 you win about 1 in 4 times.", facts) == []


def test_percent_rounding_within_half_a_point_is_ok(facts):
    eq = float(facts["math"]["your_equity"].rstrip("%"))
    assert find_bad_numbers(f"{eq + 0.4:.1f}% equity", facts) == []
    assert find_bad_numbers(f"{eq + 2:.0f}% equity", facts) != []


def test_suggesting_another_play_is_caught(facts):
    assert mentions_other_play("Honestly you should fold here.", facts)
    assert not mentions_other_play("Folding would waste your equity.", facts)


# --- explain() end to end with a fake Claude ----------------------------------------

def test_offline_mode_uses_template(decision):
    e = explain(SPOT, decision, use_claude=False)
    assert e.source == "template" and e.check_passed
    assert e.limitations


def test_good_claude_text_is_used(decision, facts):
    client = FakeClient(reply(good_text(facts)))
    e = explain(SPOT, decision, client=client)
    assert e.source == "claude"
    assert e.body == good_text(facts)
    assert len(client.calls) == 1


def test_request_uses_default_model_and_fallbacks(decision, facts):
    client = FakeClient(reply(good_text(facts)))
    explain(SPOT, decision, client=client)
    call = client.calls[0]
    assert call["model"] == MODEL
    assert call["fallbacks"] == "default"
    assert "FACT SHEET" in call["messages"][0]["content"]


def test_verdict_is_written_by_code_not_claude(decision, facts):
    e = explain(SPOT, decision, client=FakeClient(reply(good_text(facts))))
    assert e.verdict.lower().startswith(facts["recommendation"]["play"].split()[0])


def test_bad_numbers_trigger_one_retry(decision, facts):
    client = FakeClient(reply("You have 99% equity, raise to $31.50."),
                        reply(good_text(facts)))
    e = explain(SPOT, decision, client=client)
    assert e.source == "claude"
    assert e.attempts == 2
    assert "$31.50" in e.bad_numbers            # what the first draft got wrong
    assert len(client.calls) == 2
    feedback = client.calls[1]["messages"][-1]["content"]
    assert "$31.50" in feedback


def test_two_failures_fall_back_to_template(decision):
    client = FakeClient(reply("You have 99% equity."), reply("Still 99% equity."))
    e = explain(SPOT, decision, client=client)
    assert e.source == "template"
    assert "99%" in e.bad_numbers
    assert "number check" in e.error


def test_refusal_falls_back_to_template(decision):
    e = explain(SPOT, decision, client=FakeClient(reply("", stop_reason="refusal")))
    assert e.source == "template"
    assert "declined" in e.error


def test_api_error_falls_back_to_template(decision):
    e = explain(SPOT, decision, client=FakeClient(error=ConnectionError("offline")))
    assert e.source == "template"
    assert "offline" in e.error
