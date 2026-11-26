import pytest

from goatev_engine.numbers import (
    call_amount, effective_stack, pot_odds, pot_odds_ratio, spr, spr_after_call,
)
from goatev_engine.scenario import Scenario


# --- pot odds -------------------------------------------------------------

def test_pot_odds_half_pot_bet():
    # Pot was $20, villain bets $10 -> pot is $30, hero calls $10.
    # Hero risks 10 to win 30 -> needs 10 / 40 = 25%.
    assert pot_odds(30, 10) == pytest.approx(0.25)


def test_pot_odds_pot_sized_bet():
    # Pot $20, villain bets $20 -> pot $40, call $20 -> 20 / 60 = 33.3%.
    assert pot_odds(40, 20) == pytest.approx(1 / 3)


def test_pot_odds_nothing_to_call():
    assert pot_odds(30, 0) == 0.0


def test_pot_odds_ratio():
    assert pot_odds_ratio(30, 10) == pytest.approx(3.0)   # "3 to 1"


# --- calling all-in for less ------------------------------------------------

def test_call_amount_capped_by_stack():
    assert call_amount(to_call=100, hero_stack=60) == 60
    assert call_amount(to_call=10, hero_stack=60) == 10


# --- effective stack --------------------------------------------------------

def test_effective_stack_is_the_smaller_stack():
    assert effective_stack(190, 170) == 170
    assert effective_stack(50, 400) == 50


# --- SPR ----------------------------------------------------------------------

def test_spr_basic():
    assert spr(170, 20) == pytest.approx(8.5)


def test_spr_zero_pot_raises():
    with pytest.raises(ValueError):
        spr(100, 0)


def test_spr_after_call():
    # Hero 190, villain 170 behind, pot 30, hero calls 10.
    # New pot = 40. Hero behind = 180, villain 170 -> eff 170. SPR = 170/40.
    s = Scenario(hero_position="BTN", villain_position="BB",
                 hero_stack=190, villain_stack=170,
                 hero_cards=["As", "Kd"], board=["Ah", "7c", "2d"],
                 street="flop", pot=30, to_call=10)
    assert spr_after_call(s) == pytest.approx(4.25)
