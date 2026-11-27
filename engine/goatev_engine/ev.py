"""
ev.py — Expected Value: how much an option wins or loses ON AVERAGE.

EV answers: "If I made this exact play 1,000 times, what would I average?"

    EV = (chance of each outcome) x (what I win or lose in it), added up.

We measure from the moment of decision. Chips already in the pot are no
longer "yours" — so folding is always worth exactly 0, and every other
option is compared to that:

    EV > 0  -> better than folding (makes money long-term)
    EV < 0  -> worse than folding

v1 model (simple on purpose):
  - After hero's action, villain either FOLDS or CALLS. No re-raises.
  - If villain calls, the hand goes to showdown at hero's equity
    (no more betting on later streets).
These are the standard "one-street" formulas. Later steps can add more.
"""

INF = float("inf")


def _check_prob(name: str, p: float) -> None:
    if not 0 <= p <= 1:
        raise ValueError(f"{name} must be between 0 and 1, got {p}")


def ev_fold() -> float:
    """Folding: you neither win nor lose anything more. Always 0."""
    return 0.0


def ev_call(pot: float, call: float, equity: float) -> float:
    """EV of calling a bet.

        EV = equity x (pot + call)  -  call
             ^ the share of the final   ^ what you put in
               pot you win on average

    `pot` already includes villain's bet.
    Example: pot $30, call $10, equity 50% -> 0.5 x 40 - 10 = +$10.
    """
    _check_prob("equity", equity)
    if call < 0 or pot < 0:
        raise ValueError("pot and call can't be negative")
    return equity * (pot + call) - call


def ev_raise(
    pot: float,
    to_call: float,
    risk: float,
    fold_pct: float,
    equity_when_called: float,
    villain_stack: float = INF,
    reraise_pct: float = 0.0,
    reraise_value: float | None = None,
) -> float:
    """EV of betting or raising.

    pot                 money in the middle now (includes villain's bet, if any)
    to_call             what hero would need just to call (0 when hero bets first)
    risk                total chips hero puts in with this bet/raise
    fold_pct            chance villain folds (0..1)
    equity_when_called  hero's equity against the hands that CALL
                        (usually lower than vs villain's whole range:
                        weak hands fold, strong hands call)
    villain_stack       villain's chips behind; they can't call more than this
    reraise_pct         chance villain re-raises (default 0 = only folds or calls)
    reraise_value       what hero ends up with when villain re-raises, after
                        choosing the better of calling or folding.
                        Default: hero folds and loses `risk`.

    Outcomes:
      villain folds     -> hero wins the pot as it is now             (+pot)
      villain re-raises -> reraise_value (at worst -risk)
      villain calls     -> villain adds (risk - to_call), showdown:
                           equity x final_pot - risk

        EV = fold% x pot + reraise% x reraise_value + call% x (equity x final_pot - risk)
    """
    _check_prob("fold_pct", fold_pct)
    _check_prob("reraise_pct", reraise_pct)
    _check_prob("equity_when_called", equity_when_called)
    if fold_pct + reraise_pct > 1 + 1e-9:
        raise ValueError("fold_pct + reraise_pct can't be more than 1")
    if risk < to_call:
        raise ValueError("a raise must put in at least the amount to call")
    if min(pot, to_call, risk, villain_stack) < 0:
        raise ValueError("amounts can't be negative")

    # If villain is short, they can only call part of it; hero gets the rest back.
    villain_adds = min(risk - to_call, villain_stack)
    hero_risk = to_call + villain_adds
    final_pot = pot + hero_risk + villain_adds

    when_called = equity_when_called * final_pot - hero_risk
    call_pct = max(0.0, 1 - fold_pct - reraise_pct)
    if reraise_value is None:
        reraise_value = -risk
    return fold_pct * pot + reraise_pct * reraise_value + call_pct * when_called


def ev_vs_shove(pot: float, to_call: float, risk: float, hero_stack: float,
                villain_stack: float, equity_vs_shove: float) -> tuple[float, str]:
    """Hero bet/raised `risk`; villain re-raises ALL-IN. Hero's best response.

    Calling: hero puts in up to their whole stack (capped by what villain has),
             final pot = pot + hero_total + villain_total, hero wins equity x final.
    Folding: hero loses the `risk` already put in.
    Returns (value of the better choice, "call" or "fold").
    """
    hero_total = min(hero_stack, villain_stack + to_call)
    villain_total = hero_total - to_call
    final_pot = pot + hero_total + villain_total
    call_value = equity_vs_shove * final_pot - hero_total
    return (call_value, "call") if call_value > -risk else (-risk, "fold")


def ev_bet(pot: float, bet: float, fold_pct: float, equity_when_called: float,
           villain_stack: float = INF) -> float:
    """A bet is a raise when there's nothing to call."""
    return ev_raise(pot, 0, bet, fold_pct, equity_when_called, villain_stack)


def breakeven_fold_pct(pot: float, risk: float) -> float:
    """How often a PURE BLUFF (0% equity when called) must work to break even.

        fold% needed = risk / (pot + risk)

    Half-pot bet ($10 into $20): 10 / 30 = 33%.  Pot-size bet: 50%.
    """
    if pot + risk <= 0:
        raise ValueError("pot + risk must be positive")
    return risk / (pot + risk)
