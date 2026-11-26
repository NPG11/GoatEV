# GoatEV

A study and training app for live no-limit hold'em cash games (9-max).
Recreate a hand after your session, and the coach recommends fold / call / raise
with the exact math and a plain-language explanation, adjusted for the opponent type.

## Status

| Part | State |
|---|---|
| Engine Step 1: scenario validation, pot odds, effective stack, SPR | ✅ |
| Engine Step 2: equity (exact on flop, Monte Carlo preflop, ranges, card removal) | ✅ |
| Engine Step 3A: range notation (`QQ+, AKs, A5s-A2s`) → combos | ✅ |
| Engine Step 3B: preflop charts by position + action (open, call, 3bet, call_3bet, 4bet) | ✅ |
| Engine Step 3C: villain types reshape ranges + fold rates, limp ranges | ✅ |
| Engine Step 4: decision engine (fold / call / raise) | ⏳ next |
| LLM explanations, API, frontend | later |

## Engine

```powershell
cd engine
python -m pip install treys pytest
python -m pytest -q
```

## Stack

Python engine (treys, pytest) → FastAPI → Next.js / TypeScript → Postgres.
