"""
main.py — GoatEV's own API: the "front desk" in front of the engine.

    GET  /health          is the server up?
    GET  /villain-types   the 5 villain types, for the picker
    POST /validate        check a hand while it's being built
    POST /coach           the main one: hand in -> verdict + options + explanation

Run it locally (from the api folder):
    python -m uvicorn app.main:app --reload
then open http://localhost:8000/docs to try every endpoint in the browser.
"""

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException

# Secrets and settings live in GoatEV/.env (never committed - see .env.example).
# Real environment variables win over the file.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")
from fastapi.middleware.cors import CORSMiddleware

from goatev_engine.decision import Decision, Option, decide
from goatev_engine.explain import explain
from goatev_engine.facts import fold_sensitivity_sentence
from goatev_engine.scenario import Scenario, ScenarioError
from goatev_engine.villains import PROFILES, villain_range

from .schemas import (
    CoachIn, CoachOut, HandIn, OptionOut, ValidateOut, VillainTypeOut,
)

app = FastAPI(
    title="GoatEV API",
    version="0.1.0",
    description="Poker coach for live 9-max no-limit hold'em cash games.",
)

# The frontend runs on a different address (localhost:3000 while developing),
# so the browser needs permission to call us. That permission is CORS.
ALLOWED_ORIGINS = os.getenv("GOATEV_CORS_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Dependencies: small functions FastAPI calls for each request.
# Tests swap them out (e.g. a fake Claude) without touching the endpoints.
# ---------------------------------------------------------------------------

def get_samples() -> int:
    """Monte Carlo samples per villain combo (more = slower but steadier)."""
    return int(os.getenv("GOATEV_SAMPLES", "200"))


@lru_cache(maxsize=1)
def _claude_client():
    import anthropic
    return anthropic.Anthropic()      # reads ANTHROPIC_API_KEY from the environment


def get_claude():
    """The Claude client, or None if there's no API key configured."""
    if not os.getenv("ANTHROPIC_API_KEY"):
        return None
    try:
        return _claude_client()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def to_scenario(hand: HandIn) -> Scenario:
    fields = hand.model_dump(include=set(HandIn.model_fields))
    return Scenario(**fields)


def option_out(o: Option, big_blind: float) -> OptionOut:
    return OptionOut(
        action=o.action,
        label=o.label(big_blind),
        amount=o.amount,
        amount_bb=round(o.amount / big_blind, 2),
        ev=round(o.ev, 2),
        ev_bb=round(o.ev / big_blind, 2),
        villain_folds=o.fold_pct,
        equity_when_called=o.equity_when_called,
        folds_needed_for_bluff=o.breakeven_fold,
        villain_reraises=o.reraise_pct,
        answer_to_reraise=o.vs_reraise,
    )


def unprocessable(errors: list[str]) -> HTTPException:
    """422 = 'I understood the request, but the hand itself is impossible.'"""
    return HTTPException(status_code=422, detail={"errors": errors})


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/villain-types", response_model=list[VillainTypeOut])
def villain_types():
    return [VillainTypeOut(key=p.key, label=p.label, summary=p.summary)
            for p in PROFILES.values()]


@app.post("/validate", response_model=ValidateOut)
def validate(hand: HandIn):
    s = to_scenario(hand)
    errors = s.errors()
    if not errors:
        try:   # e.g. "BB can't 'open' preflop"
            villain_range(s.villain_type, s.villain_position, s.villain_action)
        except ValueError as e:
            errors.append(str(e))
    return ValidateOut(valid=not errors, errors=errors)


@app.post("/coach", response_model=CoachOut)
def coach(req: CoachIn, samples: int = Depends(get_samples), claude=Depends(get_claude)):
    s = to_scenario(req)
    try:
        d: Decision = decide(s, samples=samples, fold_override=req.fold_override)
    except ScenarioError as e:
        raise unprocessable(str(e).split("; "))
    except ValueError as e:
        raise unprocessable([str(e)])

    use_claude = req.explain_with_claude and claude is not None
    e = explain(s, d, client=claude, use_claude=use_claude)
    note = e.error
    if req.explain_with_claude and claude is None:
        note = "Claude isn't configured on this server (no ANTHROPIC_API_KEY)."

    ranked = sorted(d.options, key=lambda o: o.ev, reverse=True)
    return CoachOut(
        verdict=e.verdict,
        best=option_out(d.best, s.big_blind),
        close_spot=d.close,
        options=[option_out(o, s.big_blind) for o in ranked],
        numbers=d.numbers,
        how_sure=fold_sensitivity_sentence(d.numbers),
        explanation=e.body,
        explained_by=e.source,
        explain_note=note,
        claude_attempts=e.attempts,
        limitations=list(d.limitations),
    )
