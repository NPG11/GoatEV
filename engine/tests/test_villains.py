import pytest

from goatev_engine.charts import chart_range
from goatev_engine.ranges import TOTAL_COMBOS, combo_count, parse_range, range_percent
from goatev_engine.scenario import VILLAIN_TYPES
from goatev_engine.strength import chen_score
from goatev_engine.villains import (
    PROFILES, PREMIUMS, TRAP_LIMP_WEIGHT, get_profile, reshape, villain_range,
)


def pct(vtype, pos, action):
    return range_percent(villain_range(vtype, pos, action))


# --- profiles -----------------------------------------------------------------

def test_every_scenario_villain_type_has_a_profile():
    assert set(PROFILES) == set(VILLAIN_TYPES)


def test_unknown_type_raises():
    with pytest.raises(ValueError, match="unknown villain type"):
        get_profile("fish")


def test_fold_rates_are_valid_fractions():
    for p in PROFILES.values():
        for rate in (p.fold_to_3bet, p.fold_to_cbet, p.fold_to_raise):
            assert 0 <= rate <= 1


def test_nit_folds_most_and_station_folds_least():
    cbet = {k: p.fold_to_cbet for k, p in PROFILES.items()}
    assert max(cbet, key=cbet.get) == "nit"
    assert min(cbet, key=cbet.get) == "calling_station"


# --- reshape --------------------------------------------------------------------

BASE = parse_range("22+, A2s+, KTs+, ATo+")


def test_factor_one_changes_nothing():
    assert reshape(BASE, 1.0) == BASE


@pytest.mark.parametrize("factor", [0.3, 0.5, 1.7, 2.0])
def test_reshape_hits_the_target_size(factor):
    assert combo_count(reshape(BASE, factor)) == pytest.approx(
        combo_count(BASE) * factor, abs=0.01)


def test_reshape_never_exceeds_every_hand():
    assert combo_count(reshape(BASE, 100)) == pytest.approx(TOTAL_COMBOS)


def test_tightening_drops_weakest_hands_first():
    tight = reshape(BASE, 0.5)
    kept = [h for h, w in tight.items() if w == 1.0]
    dropped = [h for h in BASE if h not in tight]
    assert min(chen_score(h) for h in kept) >= max(chen_score(h) for h in dropped)


def test_widening_adds_strongest_missing_hands_first():
    wide = reshape(BASE, 1.5)
    added = [h for h, w in wide.items() if h not in BASE and w == 1.0]
    still_missing = [h for h in parse_range("22+, A2+, K2+, Q2+, J2+, T2+, 92+, 82+, 72+, 62+, 52+, 42+, 32")
                     if h not in wide]
    assert min(chen_score(h) for h in added) >= max(chen_score(h) for h in still_missing)


# --- villain types shape ranges the right way -------------------------------------

def test_unknown_matches_the_baseline_chart():
    assert villain_range("unknown", "CO", "open") == chart_range("CO", "open")


def test_open_width_order():
    sizes = [pct(t, "CO", "open") for t in ("nit", "unknown", "lag", "maniac")]
    assert sizes == sorted(sizes)


def test_station_calls_wide_but_rarely_3bets():
    assert pct("calling_station", "BTN", "call") > 2 * pct("unknown", "BTN", "call")
    assert pct("calling_station", "CO", "3bet") < pct("unknown", "CO", "3bet")


def test_station_3bets_value_only_no_bluffs():
    r = villain_range("calling_station", "CO", "3bet")
    assert "A5s" not in r and "A4s" not in r
    assert {"AA", "KK", "QQ"} <= set(r)


def test_nit_3bet_is_a_subset_of_normal_3bet():
    assert set(villain_range("nit", "CO", "3bet")) <= set(chart_range("CO", "3bet"))


def test_maniac_3bets_far_more_than_nit():
    assert pct("maniac", "CO", "3bet") > 3 * pct("nit", "CO", "3bet")


def test_aces_survive_every_tightening():
    for vtype in PROFILES:
        for action in ("open", "3bet", "4bet"):
            assert villain_range(vtype, "CO", action).get("AA") == 1.0


# --- limping ------------------------------------------------------------------------

def test_limp_range_mostly_excludes_premiums():
    r = villain_range("calling_station", "BTN", "limp")
    for hand in PREMIUMS:
        assert r.get(hand, 0) <= TRAP_LIMP_WEIGHT


def test_station_limps_wider_than_nit():
    assert pct("calling_station", "BTN", "limp") > pct("nit", "BTN", "limp")


def test_bb_cannot_limp():
    with pytest.raises(ValueError, match="can't 'limp'"):
        villain_range("unknown", "BB", "limp")


def test_impossible_chart_spots_still_raise():
    with pytest.raises(ValueError):
        villain_range("maniac", "BB", "open")
