import pytest

from goatev_engine.charts import ACTIONS, OPEN, chart_range, chart_text
from goatev_engine.ranges import range_percent
from goatev_engine.scenario import POSITIONS

OPEN_ORDER = ["UTG", "UTG1", "MP", "LJ", "HJ", "CO", "BTN"]


def _every_valid_spot():
    for pos in POSITIONS:
        for action in ACTIONS:
            try:
                chart_text(pos, action)
            except ValueError:
                continue
            yield pos, action


# --- every chart is valid range text ----------------------------------------

@pytest.mark.parametrize("pos,action", list(_every_valid_spot()))
def test_every_chart_parses(pos, action):
    assert len(chart_range(pos, action)) > 0


# --- opening ranges make poker sense ------------------------------------------

def test_open_ranges_get_wider_toward_the_button():
    sizes = [range_percent(chart_range(p, "open")) for p in OPEN_ORDER]
    assert sizes == sorted(sizes)


def test_each_seat_opens_everything_the_seat_before_opens():
    # If UTG opens a hand, every later seat should open it too.
    for earlier, later in zip(OPEN_ORDER, OPEN_ORDER[1:]):
        missing = set(chart_range(earlier, "open")) - set(chart_range(later, "open"))
        assert not missing, f"{later} is missing {missing} that {earlier} opens"


@pytest.mark.parametrize("pos,low,high", [
    ("UTG", 0.09, 0.14),
    ("HJ", 0.17, 0.24),
    ("CO", 0.24, 0.32),
    ("BTN", 0.38, 0.52),
])
def test_open_sizes_are_realistic(pos, low, high):
    assert low <= range_percent(chart_range(pos, "open")) <= high


@pytest.mark.parametrize("pos", list(OPEN))
def test_premiums_are_always_opened(pos):
    r = chart_range(pos, "open")
    assert {"AA", "KK", "QQ", "AKs", "AKo"} <= set(r)


@pytest.mark.parametrize("pos", list(OPEN))
def test_trash_is_never_opened(pos):
    assert "72o" not in chart_range(pos, "open")


# --- actions narrow the range the right way -----------------------------------

@pytest.mark.parametrize("pos", ["MP", "CO", "BTN", "BB"])
def test_aces_get_3bet_not_flatted(pos):
    assert "AA" not in chart_range(pos, "call")
    assert "AA" in chart_range(pos, "3bet")


def test_3bet_is_tighter_than_open():
    assert range_percent(chart_range("CO", "3bet")) < range_percent(chart_range("CO", "open"))


def test_4bet_is_tighter_than_3bet():
    assert range_percent(chart_range("CO", "4bet")) < range_percent(chart_range("CO", "3bet"))


def test_bb_defends_wider_than_other_seats_call():
    bb = range_percent(chart_range("BB", "call"))
    assert all(bb > range_percent(chart_range(p, "call")) for p in ("MP", "CO", "BTN", "SB"))


# --- impossible spots are rejected ----------------------------------------------

@pytest.mark.parametrize("pos,action", [
    ("BB", "open"),     # folded to BB = BB just wins
    ("UTG", "call"),    # nobody has opened before UTG
    ("UTG", "3bet"),
    ("BB", "4bet"),     # BB never opened, so it can't face a 3-bet as the opener
])
def test_impossible_spots_raise(pos, action):
    with pytest.raises(ValueError, match="can't"):
        chart_text(pos, action)


def test_unknown_action_raises():
    with pytest.raises(ValueError, match="unknown action"):
        chart_text("BTN", "limp")
