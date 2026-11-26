import pytest

from goatev_engine.strength import chen_score, hands_by_strength


@pytest.mark.parametrize("hand,score", [
    ("AA", 20),     # A = 10, doubled
    ("KK", 16),
    ("22", 5),      # 1 doubled = 2, but pairs are at least 5
    ("AKs", 12),    # 10 + 2 suited
    ("AKo", 10),
    ("T9s", 8),     # 5 + 2 suited + 1 connected below Q
    ("K9o", 4),     # 8 - 4: missing ranks Q, J, T = gap of 3
    ("72o", -1.5),  # 3.5 - 5: gap of 4 (6, 5, 4, 3)
])
def test_chen_scores(hand, score):
    assert chen_score(hand) == score


def test_order_has_all_169_hands_once():
    order = hands_by_strength()
    assert len(order) == len(set(order)) == 169


def test_aces_are_best_and_72o_is_worst():
    order = hands_by_strength()
    assert order[0] == "AA"
    assert order[-1] == "72o"


def test_suited_beats_offsuit():
    order = hands_by_strength()
    assert order.index("AKs") < order.index("AKo")
