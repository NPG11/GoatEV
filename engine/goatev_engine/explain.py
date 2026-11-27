"""
explain.py — Step 5: turn the engine's numbers into a plain-language lesson.

The rule: CODE decides, CLAUDE explains.

  1. The verdict line ("Raise to $30") is written by code from the Decision,
     so the recommendation can never be changed by the language model.
  2. Claude gets the fact sheet (facts.py) and writes the "why".
  3. The checker pulls every number out of Claude's text and compares it
     with the fact sheet. A number that isn't there = the check fails.
  4. On a failed check, Claude gets ONE retry with the bad numbers listed.
     If it fails again (or there's no API key, or the request errors),
     a template explanation built only from the facts is used instead.

So the user always gets an explanation, and every number in it is real.
"""

import json
import re
from dataclasses import dataclass, field

from .decision import Decision, decide
from .facts import allowed_numbers, build_facts
from .scenario import Scenario

MODEL = "claude-opus-5-5"
EFFORT = "low"            # short, well-specified writing task
MAX_TOKENS = 4000

SYSTEM_PROMPT = """\
You are the coach inside GoatEV, a study app for live no-limit hold'em cash games.
The player is reviewing a hand after their session. They play regularly but are
new to poker math, so explain like a friendly coach, not a textbook.

You will get a FACT SHEET in JSON. It was produced by a poker math engine and it
is the only source of truth.

Rules:
- Use only numbers that appear in the fact sheet, written the same way
  (for example "87%" or "$29.42"). Never calculate, round differently, or
  estimate a new number. If you want to compare two numbers, name both;
  don't compute the difference unless it is in the fact sheet.
- The recommendation in the fact sheet is final. Explain why it is best;
  never suggest a different play.
- If close_spot is true, say plainly that it's close and why the
  recommended option was chosen.
- If the fact sheet has "how_sure", include it: it tells the player how far
  the fold-rate estimate can be wrong before the advice changes.
- Do not restate the recommendation as a headline; the app shows it above
  your text.

Write 3 short paragraphs, about 120-170 words total, in plain text (no markdown
headings, no bullet lists):
1. The main reason this play is best, using the most important 2-3 numbers.
2. How this villain type changes the answer (their range or fold rate).
3. One simple rule of thumb the player can remember at the table.
Briefly explain a poker term the first time you use it (equity, pot odds,
fold equity, SPR).
"""

# Numbers up to this size may appear without being in the fact sheet:
# "1 in 3", "3 paragraphs", card ranks like "a 7".
FREE_SMALL_NUMBER = 10

_NUMBER = re.compile(
    r"(?P<dollar>\$)?(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>%|BB\b|bb\b)?"
)


@dataclass
class Explanation:
    verdict: str                     # written by code, e.g. "Raise to $30 (15 BB)"
    body: str                        # the explanation text
    source: str                      # "claude" or "template"
    check_passed: bool
    bad_numbers: list[str] = field(default_factory=list)
    limitations: tuple[str, ...] = ()
    facts: dict = field(default_factory=dict)
    error: str | None = None         # why Claude wasn't used, if it wasn't


# ---------------------------------------------------------------------------
# The number checker
# ---------------------------------------------------------------------------

def find_bad_numbers(text: str, facts: dict) -> list[str]:
    """Every number in `text` that does not appear in the fact sheet.

    - Dollar and BB amounts must match a fact-sheet number exactly.
    - Percents may differ by at most 0.5 (so "87%" is fine for 87%).
    - Plain whole numbers up to 10 are always allowed ("1 in 3", "a 7").
    """
    allowed = allowed_numbers(facts)
    bad = []
    for m in _NUMBER.finditer(text):
        token = m.group(0).strip()
        value = float(m.group("num"))
        if m.group("dollar") is None and m.group("unit") is None \
                and value.is_integer() and value <= FREE_SMALL_NUMBER:
            continue
        if any(abs(value - a) < 1e-9 for a in allowed):
            continue
        if m.group("unit") == "%" and any(abs(value - a) <= 0.5 for a in allowed):
            continue
        bad.append(token)
    return bad


def mentions_other_play(text: str, facts: dict) -> bool:
    """Crude guard: the text must not tell the player to make a different play."""
    best = facts["recommendation"]["play"].split()[0]          # fold/check/call/bet/raise/go
    others = {"fold", "call", "raise", "bet", "check"} - {best}
    lowered = text.lower()
    return any(re.search(rf"\byou should {o}\b", lowered) for o in others)


# ---------------------------------------------------------------------------
# Template explanation (no Claude needed)
# ---------------------------------------------------------------------------

def template_explanation(facts: dict) -> str:
    """A plain explanation built only from the fact sheet."""
    m, rec, h = facts["math"], facts["recommendation"], facts["hand"]
    opts = facts["options_best_first"]
    best = opts[0] if opts[0]["option"] == rec["play"] else next(
        o for o in opts if o["option"] == rec["play"])

    lines = [f"Your equity is {m['your_equity']} against this {h['villain_type']}'s range."]
    if m["equity_needed_to_call"] != "n/a (no bet to call)":
        lines.append(f"To call you need {m['equity_needed_to_call']}.")
    lines.append(f"The best option, {rec['play']}, averages {rec['ev']}.")
    if "villain_folds" in best:
        lines.append(
            f"They fold about {best['villain_folds']} of the time here, and when they "
            f"call you still have {best['your_equity_when_called']}.")
    if "edge_over_next_best" in rec:
        lines.append(f"That's {rec['edge_over_next_best']} better than {rec['next_best']}.")
    if rec.get("close_spot"):
        lines.append(rec.get("note", "This is a close spot; the lower-risk option is recommended."))
    if rec.get("how_sure"):
        lines.append(rec["how_sure"])
    return " ".join(lines)


# ---------------------------------------------------------------------------
# Calling Claude
# ---------------------------------------------------------------------------

def _default_client():
    import anthropic
    return anthropic.Anthropic()


def _ask_claude(client, messages: list) -> tuple[str, list]:
    """One request. Returns (text, content_blocks). Raises on refusal."""
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        output_config={"effort": EFFORT},
        # If a safety classifier declines, retry on a fallback model server-side.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=messages,
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude declined to write this explanation")
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    return text, response.content


def explain(
    s: Scenario,
    decision: Decision | None = None,
    *,
    client=None,
    use_claude: bool = True,
) -> Explanation:
    """Explain the coach's decision for this scenario.

    client:     an anthropic.Anthropic() (or a test double). Created if None.
    use_claude: False = skip Claude and use the template (offline / tests).
    """
    d = decision or decide(s)
    facts = build_facts(s, d)
    verdict = facts["recommendation"]["play"].capitalize()
    verdict += f"  (EV {facts['recommendation']['ev']})"
    if facts["recommendation"]["close_spot"]:
        verdict += "  - close spot"

    def from_template(bad=(), error=None):
        return Explanation(verdict, template_explanation(facts), "template",
                           check_passed=True, bad_numbers=list(bad),
                           limitations=d.limitations, facts=facts, error=error)

    if not use_claude:
        return from_template()

    try:
        client = client or _default_client()
        messages = [{"role": "user", "content":
                     "FACT SHEET:\n" + json.dumps(facts, indent=2)}]
        text, content = _ask_claude(client, messages)
        bad = find_bad_numbers(text, facts)
        wrong_play = mentions_other_play(text, facts)

        if bad or wrong_play:
            # One retry, telling Claude exactly what was wrong.
            problems = []
            if bad:
                problems.append("these numbers are not in the fact sheet: " + ", ".join(bad))
            if wrong_play:
                problems.append("it suggests a play other than the recommendation")
            messages += [
                {"role": "assistant", "content": content},
                {"role": "user", "content":
                 "Please rewrite it. Problem: " + "; ".join(problems) +
                 ". Use only numbers exactly as written in the fact sheet."},
            ]
            text, content = _ask_claude(client, messages)
            bad = find_bad_numbers(text, facts)
            wrong_play = mentions_other_play(text, facts)
            if bad or wrong_play:
                return from_template(bad, error="Claude's text failed the number check twice")

        return Explanation(verdict, text, "claude", check_passed=True,
                           limitations=d.limitations, facts=facts)

    except Exception as e:   # no key, network down, refusal, bad response...
        return from_template(error=f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    # Demo:  python -m goatev_engine.explain
    # Uses Claude if ANTHROPIC_API_KEY is set, otherwise the template.
    demo = Scenario(hero_position="BTN", villain_position="CO", villain_action="open",
                    villain_type="nit", hero_stack=180, villain_stack=180, street="flop",
                    hero_cards=["As", "Kd"], board=["Ah", "7c", "2d"], pot=30, to_call=10)
    result = explain(demo)
    print("VERDICT:", result.verdict)
    print(f"(written by: {result.source}" + (f"; {result.error}" if result.error else "") + ")\n")
    print(result.body)
