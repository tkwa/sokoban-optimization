"""Finite-state potential certificates for stronger push lower bounds.

A certificate assigns nonnegative integer h-values to finitely many states.
Unlisted states use a known admissible matching bound. For every listed state s,
the checker enforces h(s) <= 1+h(t) for EVERY legal push successor t and h(goal)=0.
Along any solution path these inequalities telescope to h(s) <= solution cost.
This argument also covers cycles and unreachable listed states.
"""

from .core import Board, INFINITY, Invalid, MatchingBound, State
from .scoring import integer

MAX_PROOF_STATES = 100_000
MAX_BOUND = 2_000_000


def verify_lower(board: Board, certificate: dict) -> int:
    if isinstance(certificate, dict) and certificate.get("format") in (
            "sokogap-abstraction-v1", "sokogap-abstraction-v2"):
        from .abstraction import verify_abstraction
        return verify_abstraction(board, certificate)
    if not isinstance(certificate, dict) or set(certificate) != {"format", "board_sha256", "lower", "states"}:
        raise Invalid("invalid lower-bound certificate fields")
    if certificate["format"] != "sokogap-potential-v1":
        raise Invalid("unsupported lower-bound certificate format")
    if certificate["board_sha256"] != board.digest:
        raise Invalid("lower-bound certificate is for a different board")
    claimed = integer(certificate["lower"], "claimed lower bound")
    if claimed > MAX_BOUND:
        raise Invalid("claimed lower bound exceeds limit")
    rows = certificate["states"]
    if not isinstance(rows, list) or len(rows) > MAX_PROOF_STATES:
        raise Invalid("invalid certificate state count")
    potentials: dict[State, int] = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"boxes", "player", "h"}:
            raise Invalid("invalid state fields")
        raw_boxes = row["boxes"]
        if not isinstance(raw_boxes, list) or len(raw_boxes) != len(board.boxes):
            raise Invalid("incorrect number of boxes in certificate state")
        boxes = tuple(integer(b, "box position") for b in raw_boxes)
        if boxes != tuple(sorted(set(boxes))) or any(b not in board.floor for b in boxes):
            raise Invalid("box positions must be distinct, sorted floor cells")
        player = integer(row["player"], "player position")
        state = board.state(boxes, player)
        if state[1] != player:
            raise Invalid("player position must be the minimum reachable cell")
        h = integer(row["h"], "state potential")
        if h > MAX_BOUND or state in potentials:
            raise Invalid("duplicate state or excessive potential")
        potentials[state] = h
    base = MatchingBound(board)

    def value(state):
        return potentials[state] if state in potentials else base.cost(state[0])

    for state, h in potentials.items():
        if frozenset(state[0]) == board.goals and h != 0:
            raise Invalid("goal state must have zero potential")
        # All successor values are nonnegative. These inequalities are automatic.
        if h <= 1:
            continue
        for child in board.successors(state):
            if h > 1 + value(child):
                raise Invalid("potential violates a legal push transition")
    initial_value = value(board.initial)
    if claimed > initial_value:
        raise Invalid("claimed bound exceeds the certified initial-state potential")
    if initial_value >= INFINITY:
        raise Invalid("initial state has no finite matching; infeasibility certificates are unsupported")
    # The proved inequality remains true when rounded up to the only parity a
    # complete solution can have. Apply this after validating the raw claim.
    # Use all the supplied evidence, including when the author understates it.
    strongest = max(initial_value, base.cost(board.boxes))
    if strongest >= INFINITY:
        raise Invalid("initial state has no finite matching; infeasibility certificates are unsupported")
    return strongest + ((board.push_parity - strongest) % 2)
