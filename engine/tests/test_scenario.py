import pytest

from goatev_engine.scenario import Scenario, ScenarioError, is_valid_card


def flop_spot(**overrides) -> Scenario:
    """A valid flop spot we can tweak one field at a time."""
    base = dict(
        hero_position="BTN",
        villain_position="BB",
        villain_type="calling_station",
        hero_stack=190, villain_stack=170,
        hero_cards=["As", "Kd"],
        board=["Ah", "7c", "2d"],
        street="flop",
        pot=30, to_call=10,
    )
    base.update(overrides)
    return Scenario(**base)


def test_valid_flop_spot_passes():
    flop_spot().validate()  # no exception = pass


def test_valid_preflop_spot_passes():
    Scenario(hero_position="CO", villain_position="UTG",
             hero_cards=["Qh", "Qc"], pot=9, to_call=6).validate()


@pytest.mark.parametrize("card,ok", [
    ("As", True), ("Td", True), ("2c", True),
    ("10s", False), ("1s", False), ("Ax", False), ("as", False), ("", False),
])
def test_is_valid_card(card, ok):
    assert is_valid_card(card) is ok


@pytest.mark.parametrize("overrides,message", [
    ({"hero_position": "BUTTON"}, "unknown hero position"),
    ({"villain_position": "BTN"}, "same seat"),
    ({"villain_type": "fish"}, "unknown villain type"),
    ({"street": "turn"}, "street must be"),
    ({"board": ["Ah", "7c"]}, "needs 3 board cards"),
    ({"hero_cards": ["As"]}, "exactly 2 cards"),
    ({"hero_cards": ["As", "Ah"]}, "duplicate"),      # Ah is also on the board
    ({"board": ["Ah", "7c", "Zz"]}, "invalid card"),
    ({"hero_stack": -5}, "negative"),
    ({"to_call": 40}, "bigger than the pot"),
    ({"pot": 0, "to_call": 0}, "greater than 0"),
])
def test_invalid_spots_are_rejected(overrides, message):
    with pytest.raises(ScenarioError, match=message):
        flop_spot(**overrides).validate()


def test_errors_lists_every_problem():
    s = flop_spot(hero_cards=["As"], villain_type="fish")
    assert len(s.errors()) == 2


def test_preflop_pot_must_include_blinds():
    s = Scenario(hero_position="BTN", villain_position="BB",
                 hero_cards=["As", "Kd"], pot=2)
    with pytest.raises(ScenarioError, match="blinds"):
        s.validate()


def test_to_bb():
    assert flop_spot().to_bb(10) == 5.0   # $10 at $1/$2 = 5 BB
