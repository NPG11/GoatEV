"""
schemas.py — the exact shape of what the app may SEND and will GET BACK.

FastAPI uses these (pydantic models) to:
  - reject bad input before the engine ever sees it
    (e.g. "pot": "abc", or a position that doesn't exist -> 422 error)
  - write the interactive docs page at /docs automatically

Field names match the engine's Scenario, so the API stays a thin layer.
"""

from typing import Literal

from pydantic import BaseModel, Field

from goatev_engine.scenario import POSITIONS, STREETS, VILLAIN_ACTIONS, VILLAIN_TYPES

Position = Literal[POSITIONS]
VillainType = Literal[VILLAIN_TYPES]
VillainAction = Literal[VILLAIN_ACTIONS]
Street = Literal[STREETS]


# ---------------------------------------------------------------------------
# What the app sends
# ---------------------------------------------------------------------------

class HandIn(BaseModel):
    """One decision point, as built in the Scenario Builder."""
    hero_position: Position
    villain_position: Position
    villain_type: VillainType = "unknown"
    villain_action: VillainAction = "open"

    hero_stack: float = Field(200, ge=0, description="Your chips behind, in dollars")
    villain_stack: float = Field(200, ge=0)

    hero_cards: list[str] = Field(..., examples=[["As", "Kd"]])
    board: list[str] = Field(default_factory=list, examples=[["Ah", "7c", "2d"]])

    street: Street = "preflop"
    pot: float = Field(..., ge=0, description="Pot before you act, INCLUDING villain's bet")
    to_call: float = Field(0, ge=0)

    small_blind: float = Field(1, gt=0)
    big_blind: float = Field(2, gt=0)


class CoachIn(HandIn):
    """A hand plus coaching options."""
    fold_override: float | None = Field(
        None, ge=0, le=1,
        description="Your own read: how often this villain folds to a bet (0-1)")
    explain_with_claude: bool = Field(
        True, description="False = skip Claude and use the template explanation")


# ---------------------------------------------------------------------------
# What the app gets back
# ---------------------------------------------------------------------------

class ValidateOut(BaseModel):
    valid: bool
    errors: list[str]


class VillainTypeOut(BaseModel):
    key: str
    label: str
    summary: str


class OptionOut(BaseModel):
    action: str                     # fold, check, call, bet, raise, allin
    label: str                      # "raise to $30"
    amount: float                   # dollars hero puts in
    amount_bb: float
    ev: float                       # average profit vs folding, dollars
    ev_bb: float
    villain_folds: float | None = None
    equity_when_called: float | None = None
    folds_needed_for_bluff: float | None = None
    villain_reraises: float | None = None
    answer_to_reraise: str | None = None


class CoachOut(BaseModel):
    verdict: str                    # written by code, never by the LLM
    best: OptionOut
    close_spot: bool
    options: list[OptionOut]        # best EV first
    numbers: dict                   # every number the engine used
    how_sure: str | None            # fold-rate sensitivity sentence
    explanation: str
    explained_by: Literal["claude", "template"]
    explain_note: str | None        # why Claude wasn't used, if it wasn't
    limitations: list[str]
