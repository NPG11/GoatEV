import pytest

from goatev_engine.equity import (
    equity_vs_hand, equity_vs_range, remove_blocked,
)


# --- exact (flop) -------------------------------------------------------------

def test_flop_is_exact_and_tries_all_990_runouts():
    r = equity_vs_hand(["As", "Kd"], ["Qh", "Qc"], ["Ah", "7c", "2d"])
    assert r.exact is True
    # One villain hand -> its weight (1.0) is spread over the 990 runouts.
    assert r.total == pytest.approx(1.0)


def test_drawing_dead_is_exactly_100_percent():
    # Hero has quad aces. Villain's kings full can't catch up with 2 cards to come.
    r = equity_vs_hand(["As", "Ad"], ["Ks", "Kh"], ["Ac", "Ah", "Kd"])
    assert r.equity == pytest.approx(1.0)


def test_same_hand_different_suits_is_always_a_split():
    # Both have A-K offsuit with no heart, board is all hearts:
    # every runout ties -> each gets exactly half.
    r = equity_vs_hand(["As", "Ks"], ["Ad", "Kd"], ["2h", "7h", "9h"])
    assert r.tie_pct == pytest.approx(1.0)
    assert r.equity == pytest.approx(0.5)


def test_top_pair_vs_overpair_on_flop():
    # AK on A-7-2 vs QQ: QQ only wins if a queen comes (2 left in the deck).
    # Runouts with NO queen: choose 2 from the 43 non-queens = C(43,2) = 903.
    # So hero wins exactly 903 of 990 -> 91.2%.
    r = equity_vs_hand(["As", "Kd"], ["Qh", "Qc"], ["Ah", "7c", "2d"])
    assert r.equity == pytest.approx(903 / 990)


# --- Monte Carlo (preflop) ----------------------------------------------------

def test_aces_vs_kings_preflop_is_about_82_percent():
    r = equity_vs_hand(["As", "Ah"], ["Ks", "Kh"], seed=1)
    assert r.exact is False
    assert r.equity == pytest.approx(0.82, abs=0.015)


def test_same_seed_gives_same_answer():
    a = equity_vs_hand(["Js", "Tc"], ["8h", "8d"], iterations=2000, seed=42)
    b = equity_vs_hand(["Js", "Tc"], ["8h", "8d"], iterations=2000, seed=42)
    assert a.equity == b.equity


# --- ranges and card removal --------------------------------------------------

KINGS = [("Ks", "Kh"), ("Ks", "Kd"), ("Ks", "Kc"),
         ("Kh", "Kd"), ("Kh", "Kc"), ("Kd", "Kc")]


def test_remove_blocked_drops_hands_using_visible_cards():
    # Kd is on the board -> the 3 KK combos containing Kd are impossible.
    assert len(remove_blocked(KINGS, ["Kd"])) == 3


def test_range_uses_only_unblocked_combos():
    r = equity_vs_range(["As", "Ah"], KINGS, ["Kd", "7c", "2s"])
    assert r.combos_used == 3


def test_range_of_one_hand_matches_single_hand():
    single = equity_vs_hand(["As", "Kd"], ["Qh", "Qc"], ["Ah", "7c", "2d"])
    rng = equity_vs_range(["As", "Kd"], [("Qh", "Qc")], ["Ah", "7c", "2d"])
    assert rng.equity == pytest.approx(single.equity)


def test_weights_change_the_answer():
    # Range = {QQ, 77}. On A-7-2, 77 is a set (hero crushed), QQ is behind.
    board = ["Ah", "7c", "2d"]
    combos = [("Qh", "Qc"), ("7s", "7h")]
    mostly_qq = equity_vs_range(["As", "Kd"], combos, board, weights=[1.0, 0.1])
    mostly_77 = equity_vs_range(["As", "Kd"], combos, board, weights=[0.1, 1.0])
    assert mostly_qq.equity > mostly_77.equity


# --- bad input ------------------------------------------------------------------

def test_hero_and_villain_sharing_a_card_raises():
    with pytest.raises(ValueError, match="duplicate"):
        equity_vs_hand(["As", "Kd"], ["As", "Qc"])


def test_fully_blocked_range_raises():
    with pytest.raises(ValueError, match="blocked"):
        equity_vs_range(["Ks", "Kh"], [("Ks", "Kd"), ("Kh", "Kc")])
