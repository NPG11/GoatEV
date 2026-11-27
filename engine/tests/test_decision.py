import pytest

from goatev_engine.decision import (
    decide, fold_chance, in_position, playability, realization,
)
from goatev_engine.numbers import pot_odds
from goatev_engine.scenario import Scenario, ScenarioError

FAST = dict(samples=60, seed=1)   # fewer samples keeps the test suite quick


def spot(**kw) -> Scenario:
    base = dict(hero_position="BTN", villain_position="CO", villain_action="open",
                villain_type="unknown", hero_stack=180, villain_stack=180,
                street="flop", hero_cards=["As", "Kd"], board=["Ah", "7c", "2d"],
                pot=30, to_call=10)
    base.update(kw)
    return Scenario(**base)


def actions(d):
    return {o.action for o in d.options}


# --- structure of the answer ------------------------------------------------------

def test_facing_a_bet_offers_fold_call_raise():
    d = decide(spot(), **FAST)
    assert {"fold", "call", "raise"} <= actions(d)
    fold = next(o for o in d.options if o.action == "fold")
    assert fold.ev == 0


def test_no_bet_offers_check_and_bet_sizes():
    d = decide(spot(to_call=0, pot=20), **FAST)
    assert "check" in actions(d) and "bet" in actions(d)
    assert "fold" not in actions(d)


def test_best_is_one_of_the_options_and_highest_is_the_max():
    d = decide(spot(), **FAST)
    assert d.best in d.options
    assert d.highest_ev.ev == max(o.ev for o in d.options)


def test_numbers_sheet_matches_step_1_math():
    d = decide(spot(), **FAST)
    assert d.numbers["pot_odds"] == pytest.approx(pot_odds(30, 10))
    assert d.numbers["spr"] == pytest.approx(180 / 30)
    assert 0 <= d.numbers["equity"] <= 1


def test_limitations_are_always_reported():
    assert len(decide(spot(), **FAST).limitations) >= 3


# --- real spots: does the advice make poker sense? -------------------------------

def test_top_pair_never_folds_to_a_small_bet():
    d = decide(spot(villain_type="nit"), **FAST)
    assert d.best.action != "fold"
    assert next(o for o in d.options if o.action == "call").ev > 0


def test_trash_folds_to_a_pot_bet():
    d = decide(spot(villain_type="nit", hero_cards=["5s", "4d"],
                    board=["Ah", "Kc", "Qd"], pot=40, to_call=20), **FAST)
    assert d.best.action == "fold"


def test_bluff_the_nit_but_not_the_station():
    air = dict(hero_cards=["Qs", "Jh"], pot=20, to_call=0)
    vs_nit = decide(spot(villain_type="nit", **air), **FAST)
    vs_station = decide(spot(villain_type="calling_station", **air), **FAST)
    assert vs_nit.best.action == "bet"
    assert vs_station.best.action == "check"


def test_jacks_3bet_vs_cutoff_open():
    d = decide(spot(street="preflop", board=[], hero_cards=["Js", "Jh"],
                    pot=9, to_call=6), **FAST)
    assert d.best.action == "raise"


def test_72o_folds_in_the_big_blind():
    d = decide(spot(street="preflop", board=[], hero_position="BB",
                    villain_position="BTN", hero_cards=["7s", "2h"],
                    pot=9, to_call=4), **FAST)
    assert d.best.action == "fold"


# --- the building blocks -------------------------------------------------------------

def test_in_position():
    assert in_position(spot(hero_position="BTN", villain_position="CO"))
    assert not in_position(spot(hero_position="BB", villain_position="BTN"))


def test_playability_ranks_aces_over_junk():
    assert playability(["As", "Ah"]) == pytest.approx(1.10)
    assert playability(["7s", "2h"]) == pytest.approx(0.75)


def test_realization_is_1_on_the_flop_and_lower_out_of_position_preflop():
    assert realization(spot()) == 1.0
    ip = realization(spot(street="preflop", board=[], pot=9, to_call=6))
    oop = realization(spot(street="preflop", board=[], pot=9, to_call=4,
                           hero_position="BB", villain_position="CO"))
    assert ip > oop


def test_bigger_bets_get_more_folds():
    small = fold_chance(0.45, pot=20, to_call=0, risk=6.6, cap=1.0)
    big = fold_chance(0.45, pot=20, to_call=0, risk=15, cap=1.0)
    assert small < 0.45 < big


def test_fold_chance_is_capped_by_hands_that_can_fold():
    assert fold_chance(0.7, pot=20, to_call=0, risk=20, cap=0.3) == 0.3


def test_preflop_fold_rate_is_not_size_adjusted():
    assert fold_chance(0.55, pot=9, to_call=4, risk=16, cap=1.0, preflop=True) == 0.55


# --- bad input -------------------------------------------------------------------------

def test_invalid_scenario_raises():
    with pytest.raises(ScenarioError):
        decide(spot(hero_cards=["As"]), **FAST)


def test_impossible_villain_action_raises():
    with pytest.raises(ValueError, match="can't"):
        decide(spot(villain_position="BB", villain_action="open"), **FAST)
