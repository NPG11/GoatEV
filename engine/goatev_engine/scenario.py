"""
scenario.py — describes ONE poker spot and checks that it makes sense.

A "scenario" is a snapshot of a hand at the moment hero has to decide:
who is in the hand, their stacks, hero's cards, the board, the pot,
and how much hero has to call.

v1 scope: heads-up decisions (hero vs one villain), preflop or flop.
All money amounts are in chips/dollars. The UI's BB toggle just divides
by `big_blind` (see `to_bb`).
"""

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Constants: the "allowed values" for each field
# ---------------------------------------------------------------------------

# 9-max seats, in preflop acting order.
POSITIONS = ("UTG", "UTG1", "MP", "LJ", "HJ", "CO", "BTN", "SB", "BB")

VILLAIN_TYPES = ("unknown", "nit", "calling_station", "lag", "maniac")

# What villain did PREFLOP. This picks which chart their range comes from.
#   open       raised first in          call       called someone's raise
#   3bet       re-raised                call_3bet  opened, then called a 3-bet
#   4bet       re-raised a 3-bet        limp       just called the big blind
VILLAIN_ACTIONS = ("open", "call", "3bet", "call_3bet", "4bet", "limp")

STREETS = ("preflop", "flop")  # v1 only. turn/river come later.

# How many board cards each street must have.
BOARD_SIZE = {"preflop": 0, "flop": 3}

RANKS = "23456789TJQKA"   # T = ten
SUITS = "shdc"            # spades, hearts, diamonds, clubs


class ScenarioError(ValueError):
    """Raised when a scenario is impossible or incomplete."""


# ---------------------------------------------------------------------------
# Card helpers
# ---------------------------------------------------------------------------

def is_valid_card(card: str) -> bool:
    """'As' -> True, 'Ah' -> True, '1s' -> False, 'Ax' -> False."""
    return (
        isinstance(card, str)
        and len(card) == 2
        and card[0] in RANKS
        and card[1] in SUITS
    )


# ---------------------------------------------------------------------------
# The Scenario itself
# ---------------------------------------------------------------------------

@dataclass
class Scenario:
    # Who
    hero_position: str
    villain_position: str
    villain_type: str = "unknown"
    villain_action: str = "open"     # villain's preflop action (see VILLAIN_ACTIONS)

    # Stacks BEHIND (chips not yet put in the pot), at the moment of decision
    hero_stack: float = 200.0
    villain_stack: float = 200.0

    # Cards
    hero_cards: list[str] = field(default_factory=list)   # e.g. ["As", "Kd"]
    board: list[str] = field(default_factory=list)        # [] preflop, 3 on flop

    # Money in the middle
    street: str = "preflop"
    pot: float = 0.0       # total in the pot BEFORE hero acts (includes villain's bet)
    to_call: float = 0.0   # what hero must add to continue (0 = hero can check)

    # Stakes ($1/$2 by default)
    small_blind: float = 1.0
    big_blind: float = 2.0

    # -- validation -------------------------------------------------------

    def validate(self) -> None:
        """Raise ScenarioError with a clear message if anything is wrong.
        Returns None if everything is fine."""
        errors = self.errors()
        if errors:
            raise ScenarioError("; ".join(errors))

    def errors(self) -> list[str]:
        """Collect EVERY problem (not just the first), so the UI can show
        them all at once."""
        e: list[str] = []

        # Positions
        if self.hero_position not in POSITIONS:
            e.append(f"unknown hero position '{self.hero_position}'")
        if self.villain_position not in POSITIONS:
            e.append(f"unknown villain position '{self.villain_position}'")
        if self.hero_position == self.villain_position:
            e.append("hero and villain can't sit in the same seat")

        if self.villain_type not in VILLAIN_TYPES:
            e.append(f"unknown villain type '{self.villain_type}'")
        if self.villain_action not in VILLAIN_ACTIONS:
            e.append(f"unknown villain action '{self.villain_action}'")

        # Street + board size
        if self.street not in STREETS:
            e.append(f"street must be one of {STREETS}")
        elif len(self.board) != BOARD_SIZE[self.street]:
            e.append(
                f"{self.street} needs {BOARD_SIZE[self.street]} board cards, "
                f"got {len(self.board)}"
            )

        # Cards: format, count, duplicates
        if len(self.hero_cards) != 2:
            e.append(f"hero needs exactly 2 cards, got {len(self.hero_cards)}")
        all_cards = list(self.hero_cards) + list(self.board)
        bad = [c for c in all_cards if not is_valid_card(c)]
        if bad:
            e.append(f"invalid card(s): {bad} (use like 'As', 'Td', '9c')")
        dupes = sorted({c for c in all_cards if all_cards.count(c) > 1})
        if dupes:
            e.append(f"duplicate card(s): {dupes}")

        # Money
        if self.small_blind <= 0 or self.big_blind <= 0:
            e.append("blinds must be positive")
        if self.hero_stack < 0 or self.villain_stack < 0:
            e.append("stacks can't be negative")
        if self.pot < 0 or self.to_call < 0:
            e.append("pot and to_call can't be negative")
        if self.street == "preflop" and self.pot < self.small_blind + self.big_blind:
            e.append("preflop pot must at least contain the blinds")
        if self.street == "flop" and self.pot <= 0:
            e.append("flop pot must be greater than 0")
        if self.to_call > self.pot:
            # The bet hero faces is already IN the pot, so it can't exceed it.
            e.append("to_call can't be bigger than the pot (the bet is part of the pot)")

        return e

    # -- convenience --------------------------------------------------------

    def to_bb(self, amount: float) -> float:
        """Convert chips to big blinds. $10 at $1/$2 -> 5.0 BB."""
        return amount / self.big_blind
