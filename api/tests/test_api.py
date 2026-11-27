"""API tests. TestClient sends fake web requests straight to the app -
no server needs to be running, and no real Claude calls are made."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app, get_claude, get_samples

client = TestClient(app)

TOP_PAIR_VS_NIT = {
    "hero_position": "BTN", "villain_position": "CO",
    "villain_type": "nit", "villain_action": "open",
    "hero_cards": ["As", "Kd"], "board": ["Ah", "7c", "2d"],
    "street": "flop", "pot": 30, "to_call": 10,
    "hero_stack": 180, "villain_stack": 180,
}


@pytest.fixture(autouse=True)
def fast_and_offline():
    """Fewer samples for speed, and no Claude unless a test adds a fake one."""
    app.dependency_overrides[get_samples] = lambda: 60
    app.dependency_overrides[get_claude] = lambda: None
    yield
    app.dependency_overrides.clear()


# --- simple endpoints ---------------------------------------------------------------

def test_health():
    r = client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_villain_types():
    r = client.get("/villain-types")
    keys = [v["key"] for v in r.json()]
    assert keys == ["unknown", "nit", "calling_station", "lag", "maniac"]


# --- /validate ------------------------------------------------------------------------

def test_validate_good_hand():
    r = client.post("/validate", json=TOP_PAIR_VS_NIT)
    assert r.json() == {"valid": True, "errors": []}


def test_validate_lists_every_problem():
    bad = {**TOP_PAIR_VS_NIT, "hero_cards": ["As", "Ah"], "board": ["Ah", "7c"]}
    r = client.post("/validate", json=bad)
    body = r.json()
    assert body["valid"] is False
    assert any("duplicate" in e for e in body["errors"])
    assert any("board cards" in e for e in body["errors"])


def test_validate_catches_impossible_villain_action():
    r = client.post("/validate", json={**TOP_PAIR_VS_NIT, "villain_position": "BB",
                                       "villain_action": "open"})
    assert r.json()["valid"] is False


# --- input checking by FastAPI (before the engine) -----------------------------------

@pytest.mark.parametrize("field,value", [
    ("pot", "abc"),
    ("hero_position", "BUTTON"),
    ("villain_type", "fish"),
    ("to_call", -5),
])
def test_bad_input_is_rejected_with_422(field, value):
    r = client.post("/coach", json={**TOP_PAIR_VS_NIT, field: value})
    assert r.status_code == 422


def test_missing_required_field_is_rejected():
    body = {k: v for k, v in TOP_PAIR_VS_NIT.items() if k != "hero_cards"}
    assert client.post("/coach", json=body).status_code == 422


# --- /coach -----------------------------------------------------------------------------

def test_coach_returns_a_full_answer():
    r = client.post("/coach", json=TOP_PAIR_VS_NIT)
    assert r.status_code == 200
    body = r.json()
    assert body["best"]["action"] == "call"            # top pair vs a Nit's bet
    assert body["verdict"].lower().startswith("call")
    assert {o["action"] for o in body["options"]} >= {"fold", "call", "raise"}
    assert body["numbers"]["pot_odds"] == pytest.approx(0.25)
    assert body["limitations"]


def test_options_are_sorted_best_ev_first():
    evs = [o["ev"] for o in client.post("/coach", json=TOP_PAIR_VS_NIT).json()["options"]]
    assert evs == sorted(evs, reverse=True)


def test_impossible_hand_gives_422_with_reasons():
    r = client.post("/coach", json={**TOP_PAIR_VS_NIT, "hero_cards": ["As", "Ah"]})
    assert r.status_code == 422
    assert any("duplicate" in e for e in r.json()["detail"]["errors"])


def test_fold_override_is_used():
    air = {**TOP_PAIR_VS_NIT, "villain_type": "calling_station",
           "hero_cards": ["Qs", "Jh"], "pot": 20, "to_call": 0}
    normal = client.post("/coach", json=air).json()
    override = client.post("/coach", json={**air, "fold_override": 0.7}).json()
    assert normal["best"]["action"] == "check"
    assert override["best"]["action"] == "bet"
    assert override["numbers"]["fold_rate_source"] == "your override"


# --- explanations ------------------------------------------------------------------------

def test_without_claude_the_template_is_used_and_explained():
    body = client.post("/coach", json=TOP_PAIR_VS_NIT).json()
    assert body["explained_by"] == "template"
    assert "ANTHROPIC_API_KEY" in body["explain_note"]


def test_can_skip_claude_on_purpose():
    body = client.post("/coach", json={**TOP_PAIR_VS_NIT, "explain_with_claude": False}).json()
    assert body["explained_by"] == "template"
    assert body["explain_note"] is None


def test_with_claude_the_explanation_comes_from_claude():
    def fake_create(**kwargs):
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(
            type="text", text="Against a Nit, just call: their raises are strong.")])
    fake = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=fake_create)))
    app.dependency_overrides[get_claude] = lambda: fake

    body = client.post("/coach", json=TOP_PAIR_VS_NIT).json()
    assert body["explained_by"] == "claude"
    assert body["explanation"].startswith("Against a Nit")
