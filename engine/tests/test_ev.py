import pytest

from goatev_engine.ev import breakeven_fold_pct, ev_bet, ev_call, ev_fold, ev_raise
from goatev_engine.numbers import pot_odds


def test_fold_is_always_zero():
    assert ev_fold() == 0


# --- calling ------------------------------------------------------------------

def test_call_with_exactly_pot_odds_breaks_even():
    # Pot $30, call $10 -> need 25%. With exactly 25%: 0.25 x 40 - 10 = 0.
    assert ev_call(30, 10, 0.25) == pytest.approx(0)


def test_call_with_more_equity_makes_money():
    assert ev_call(30, 10, 0.50) == pytest.approx(10)    # 0.5 x 40 - 10


def test_call_with_less_equity_loses_money():
    assert ev_call(30, 10, 0.10) == pytest.approx(-6)    # 0.1 x 40 - 10


@pytest.mark.parametrize("pot,call", [(30, 10), (40, 20), (100, 75)])
def test_pot_odds_is_the_breakeven_point_of_a_call(pot, call):
    # Ties Step 1 to Step 4: pot odds = the equity where calling EV = 0.
    assert ev_call(pot, call, pot_odds(pot, call)) == pytest.approx(0)


# --- betting ------------------------------------------------------------------

def test_pure_bluff_at_breakeven_fold_rate():
    # $10 bluff into $20, called = always lose. Needs 1/3 folds.
    # 1/3 x 20 + 2/3 x (0 - 10) = 6.67 - 6.67 = 0
    assert ev_bet(20, 10, fold_pct=1 / 3, equity_when_called=0) == pytest.approx(0)


def test_value_bet_that_always_gets_called():
    # $10 into $20, villain always calls, hero wins 70%:
    # 0.7 x (20 + 10 + 10) - 10 = 18
    assert ev_bet(20, 10, fold_pct=0, equity_when_called=0.7) == pytest.approx(18)


def test_folds_make_a_bet_better_when_hero_is_behind():
    weak_hand = dict(pot=20, bet=10, equity_when_called=0.2)
    assert ev_bet(**weak_hand, fold_pct=0.6) > ev_bet(**weak_hand, fold_pct=0.2)


# --- raising ------------------------------------------------------------------

def test_raise_hand_checked_example():
    # Pot $30 (villain bet $10 into $20). Hero raises to $30.
    # Folds 50%: hero wins 30.
    # Calls 50%: villain adds 20 -> final pot 30 + 30 + 20 = 80; hero 40%:
    #            0.4 x 80 - 30 = 2
    # EV = 0.5 x 30 + 0.5 x 2 = 16
    assert ev_raise(30, 10, 30, fold_pct=0.5, equity_when_called=0.4) == pytest.approx(16)


def test_raise_with_no_folds_and_raise_equal_to_call_is_a_call():
    # "Raising" by exactly the call amount = calling.
    assert ev_raise(30, 10, 10, 0, 0.6) == pytest.approx(ev_call(30, 10, 0.6))


def test_short_villain_can_only_call_what_they_have():
    # Hero bets $20 into $20, but villain has only $5 left.
    # Villain calls 5 -> pot 20 + 5 + 5 = 30; hero's extra 15 comes back.
    # Hero always wins: 1.0 x 30 - 5 = 25
    assert ev_bet(20, 20, 0, 1.0, villain_stack=5) == pytest.approx(25)


def test_raise_smaller_than_call_is_rejected():
    with pytest.raises(ValueError, match="at least the amount to call"):
        ev_raise(30, 10, 5, 0.5, 0.5)


@pytest.mark.parametrize("bad", [-0.1, 1.5])
def test_probabilities_must_be_0_to_1(bad):
    with pytest.raises(ValueError):
        ev_call(30, 10, bad)
    with pytest.raises(ValueError):
        ev_bet(20, 10, bad, 0.5)


def test_reraise_makes_hero_lose_the_raise():
    # Pot 9, hero 3-bets risking 16. Villain folds 50%, 4-bets 10% (hero folds),
    # calls 40% with hero at 30%: final pot 9 + 16 + 12 = 37.
    # EV = 0.5 x 9 - 0.1 x 16 + 0.4 x (0.3 x 37 - 16) = 4.5 - 1.6 - 1.96 = 0.94
    ev = ev_raise(9, 4, 16, fold_pct=0.5, equity_when_called=0.3, reraise_pct=0.1)
    assert ev == pytest.approx(0.94)


def test_fold_plus_reraise_over_100_percent_raises():
    with pytest.raises(ValueError, match="can't be more than 1"):
        ev_raise(9, 4, 16, fold_pct=0.8, equity_when_called=0.3, reraise_pct=0.3)


# --- bluff math ----------------------------------------------------------------

@pytest.mark.parametrize("pot,risk,needed", [
    (20, 10, 1 / 3),   # half pot
    (20, 20, 1 / 2),   # pot size
    (30, 10, 1 / 4),   # third pot
])
def test_breakeven_fold_pct(pot, risk, needed):
    assert breakeven_fold_pct(pot, risk) == pytest.approx(needed)
