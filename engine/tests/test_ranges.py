import pytest

from goatev_engine.equity import equity_vs_range
from goatev_engine.ranges import (
    TOTAL_COMBOS, all_hand_classes, combo_count, expand_token, hand_combos,
    parse_range, range_percent, range_to_combos,
)


# --- hand classes and combos --------------------------------------------------

def test_there_are_169_hand_classes_and_1326_combos():
    classes = all_hand_classes()
    assert len(classes) == 169
    assert sum(len(hand_combos(h)) for h in classes) == TOTAL_COMBOS


@pytest.mark.parametrize("hand,count", [("QQ", 6), ("AKs", 4), ("AKo", 12)])
def test_combo_counts(hand, count):
    assert len(hand_combos(hand)) == count


def test_suited_combos_share_a_suit():
    assert all(a[1] == b[1] for a, b in hand_combos("AKs"))


def test_offsuit_combos_never_share_a_suit():
    assert all(a[1] != b[1] for a, b in hand_combos("AKo"))


# --- notation -----------------------------------------------------------------

@pytest.mark.parametrize("token,expected", [
    ("QQ",      ["QQ"]),
    ("QQ+",     ["QQ", "KK", "AA"]),
    ("AKs",     ["AKs"]),
    ("AK",      ["AKs", "AKo"]),
    ("ATs+",    ["ATs", "AJs", "AQs", "AKs"]),
    ("KTo+",    ["KTo", "KJo", "KQo"]),
    ("99-66",   ["66", "77", "88", "99"]),
    ("A5s-A2s", ["A2s", "A3s", "A4s", "A5s"]),
    ("aks",     ["AKs"]),         # lowercase is fine
    ("KA",      ["AKs", "AKo"]),  # backwards is fine
])
def test_expand_token(token, expected):
    assert sorted(expand_token(token)) == sorted(expected)


@pytest.mark.parametrize("bad", ["AAs", "AX", "QQ++", "A5s-K2s", "A"])
def test_bad_tokens_raise(bad):
    with pytest.raises(ValueError):
        expand_token(bad)


def test_parse_range_with_weights():
    r = parse_range("QQ+, AKs, AJs:0.5")
    assert r == {"QQ": 1.0, "KK": 1.0, "AA": 1.0, "AKs": 1.0, "AJs": 0.5}


def test_weight_out_of_range_raises():
    with pytest.raises(ValueError, match="between 0 and 1"):
        parse_range("AKs:2")


# --- counting -------------------------------------------------------------------

def test_combo_count_and_percent():
    r = parse_range("QQ+, AKs")          # 3 pairs x 6 + 4 = 22 combos
    assert combo_count(r) == 22
    assert range_percent(r) == pytest.approx(22 / 1326)


def test_weights_count_partially():
    assert combo_count(parse_range("AKs, QQ:0.5")) == 4 + 3


def test_card_removal_lowers_combo_count():
    # Hero holds the As: AA drops 6 -> 3, AKs drops 4 -> 3.
    assert combo_count(parse_range("AA, AKs"), dead=["As", "7d"]) == 3 + 3


# --- plugs straight into equity ---------------------------------------------------

def test_range_feeds_equity():
    board = ["Ah", "7c", "2d"]
    combos, weights = range_to_combos(parse_range("QQ, 77"), dead=["As", "Kd"] + board)
    r = equity_vs_range(["As", "Kd"], combos, board, weights=weights)
    # QQ: 6 combos, hero ~91%. 77: only 3 combos left (7c on board), hero ~4%.
    assert r.combos_used == 9
    assert 0.55 < r.equity < 0.65
