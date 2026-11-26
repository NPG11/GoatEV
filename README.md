# GoatEV

A study and training app for live no-limit hold'em cash games (9-max).
Recreate a hand after your session, and the coach recommends fold / call / raise
with the exact math and a plain-language explanation, adjusted for the opponent type.

## Status

| Part | State |
|---|---|
| Engine Step 1: scenario validation, pot odds, effective stack, SPR | ✅ |
| Engine Step 2: equity (exact on flop, Monte Carlo preflop, ranges, card removal) | ✅ |
| Engine Step 3: range builder + villain types | ⏳ next |
| Decision engine, LLM explanations, API, frontend | later |

## Engine

```powershell
cd engine
python -m pip install treys pytest
python -m pytest -q
```

## Stack

Python engine (treys, pytest) → FastAPI → Next.js / TypeScript → Postgres.
