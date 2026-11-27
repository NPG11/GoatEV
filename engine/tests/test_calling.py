import pytest

from goatev_engine.calling import (
    combo_class, continuing_weights, has_flush_draw, has_open_ended_draw,
    max_fold_share, never_folds, strength_key,
)
from goatev_engine.equity import equity_by_combo, equity_vs_range, weighted_equity
from goatev_engine.ranges import parse_range, range_to_combos
from goatev_engine.scenario import Scenario, ScenarioError, VILLAIN_ACTIONS
from goatev_engine.charts import ACTIONS

BOARD = ["Ah", "7c", "2d"]


# --- villain_action on the Scenario ---------------------------------------------

def test_villain_actions_cover_every_chart_plus_limp():
    assert set(VILLAIN_ACTIONS) == set(ACTIONS) | {"limp"}


def test_bad_villain_action_is_rejected():
    s = Scenario(hero_position="BTN", villain_position="CO", villain_action="shove",
                 hero_cards=["As", "Kd"], pot=9, to_call=4)
    with pytest.raises(ScenarioError, match="villain action"):
        s.validate()


# --- per-combo equity ---------------------------------------------------------------

def test_equity_by_combo_averages_to_range_equity():
    combos, weights = range_to_combos(parse_range("QQ, 77, KJs"), ["As", "Kd"] + BOARD)
    per = equity_by_combo(["As", "Kd"], combos, BOARD)
    whole = equity_vs_range(["As", "Kd"], combos, BOARD, weights=weights)
    assert weighted_equity(per, weights) == pytest.approx(whole.equity)


def test_equity_by_combo_single_known_value():
    # Same spot as Step 2: AK vs QhQc on A-7-2 = 903/990.
    assert equity_by_combo(["As", "Kd"], [("Qh", "Qc")], BOARD) == [pytest.approx(903 / 990)]


def test_equity_by_combo_rejects_blocked_combo():
    with pytest.raises(ValueError, match="known card"):
        equity_by_combo(["As", "Kd"], [("Ah", "Qc")], BOARD)


# --- describing villain hands -------------------------------------------------------

@pytest.mark.parametrize("combo,cls", [
    (("Kd", "As"), "AKo"), (("As", "Ks"), "AKs"), (("Qh", "Qc"), "QQ"),
])
def test_combo_class(combo, cls):
    assert combo_class(combo) == cls


def test_flush_draw():
    assert has_flush_draw(("Kc", "Qc"), ["Ac", "7c", "2d"])        # 4 clubs
    assert not has_flush_draw(("Kh", "Qc"), ["Ac", "7c", "2d"])    # only 3


def test_open_ended_draw():
    assert has_open_ended_draw(("9s", "8s"), ["7c", "6d", "2h"])      # 5 or T
    assert not has_open_ended_draw(("9s", "4s"), ["7c", "6d", "2h"])  # gutshot at best
    assert has_open_ended_draw(("Ks", "Qs"), ["Jc", "Td", "2h"])      # K-Q-J-T: A or 9


def test_stronger_hands_sort_first():
    set_ = strength_key(("7s", "7h"), BOARD)
    top_pair = strength_key(("Ac", "Kc"), BOARD)
    air = strength_key(("Qs", "Js"), BOARD)
    assert set_ < top_pair < air


def test_draws_rank_above_air_but_below_top_pair():
    board = ["Kc", "7c", "2d"]
    draw = strength_key(("Qc", "Jc"), board)
    air = strength_key(("Qs", "Jh"), board)
    top_pair = strength_key(("Ks", "9h"), board)
    assert top_pair < draw < air


@pytest.mark.parametrize("combo,expected", [
    (("7s", "7h"), True),    # set
    (("Ac", "Kc"), True),    # top pair
    (("Ks", "Kd"), False),   # KK is UNDER the ace on board -> not top pair
    (("Qs", "Js"), False),   # nothing
    (("8s", "8h"), False),   # pair below the ace
])
def test_never_folds_on_flop(combo, expected):
    assert never_folds(combo, BOARD) is expected


def test_overpair_never_folds():
    assert never_folds(("Ks", "Kd"), ["Qh", "7c", "2d"])   # KK above every board card


def test_board_pair_is_not_villains_pair():
    # Board 7-7-2: villain's Q-J has only the board's pair -> can fold.
    assert never_folds(("Qs", "Jh"), ["7h", "7c", "2d"]) is False


def test_never_folds_preflop_premiums():
    assert never_folds(("As", "Ah"), [])
    assert never_folds(("Ad", "Kc"), [])
    assert not never_folds(("Js", "Jh"), [])


# --- range-level helpers ---------------------------------------------------------------

def test_max_fold_share():
    # Range: 77 (3 combos left, sets) + QJs (4 combos, air). Max fold = 4/7.
    combos, weights = range_to_combos(parse_range("77, QJs"), ["As", "Kd"] + BOARD)
    assert max_fold_share(combos, weights, BOARD) == pytest.approx(4 / 7)


def test_continuing_weights_keep_strongest():
    combos, weights = range_to_combos(parse_range("77, QJs"), ["As", "Kd"] + BOARD)
    kept = continuing_weights(combos, weights, BOARD, continue_share=3 / 7)
    for c, w in zip(combos, kept):
        assert (w == 1.0) == (c[0][0] == "7")   # only the sets continue


def test_continuing_weights_partial_edge():
    combos, weights = range_to_combos(parse_range("77, QJs"), ["As", "Kd"] + BOARD)
    kept = continuing_weights(combos, weights, BOARD, continue_share=0.5)
    assert sum(kept) == pytest.approx(3.5)     # 3 sets + half of one QJs combo
