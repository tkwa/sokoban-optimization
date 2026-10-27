"""Reference A* baseline that emits independently checkable potentials."""

from heapq import heappop, heappush
from itertools import count
from time import monotonic

from .core import Board, INFINITY, MatchingBound


def prove(board: Board, expansions: int = 1000, seconds: float = 10.0) -> tuple[dict, dict]:
    base = MatchingBound(board)
    start = board.initial
    start_h = base.cost(start[0])
    if start_h >= INFINITY:
        raise ValueError("initial state has no finite box-goal matching")
    serial = count()
    frontier = [(start_h, 0, next(serial), start)]
    distance = {start: 0}
    expanded = set()
    started = monotonic()
    lower = start_h
    while frontier:
        f, neg_g, _, state = frontier[0]
        g = -neg_g
        if distance[state] != g or state in expanded:
            heappop(frontier)
            continue
        lower = f
        if len(expanded) >= expansions or monotonic() - started >= seconds:
            break
        if frozenset(state[0]) == board.goals:
            break
        heappop(frontier)
        expanded.add(state)
        for child in board.successors(state):
            new_g = g+1
            if new_g >= distance.get(child, INFINITY):
                continue
            h = base.cost(child[0])
            if h >= INFINITY:
                continue
            distance[child] = new_g
            expanded.discard(child)
            heappush(frontier, (new_g+h, -new_g, next(serial), child))
    if not frontier:
        # The benchmark contains solvable boards. Leave infeasibility claims to
        # a future certificate version instead of inventing a finite record.
        raise ValueError("no solution in the reachable state space")
    states = []
    for state in sorted(expanded):
        h = lower-distance[state]
        if h > base.cost(state[0]):
            states.append({"boxes": list(state[0]), "player": state[1], "h": h})
    certificate = {"format": "sokogap-potential-v1", "board_sha256": board.digest,
                   "lower": lower, "states": states}
    report = {"lower": lower, "matching_lower": start_h, "expanded": len(expanded),
              "discovered": len(distance), "proof_states": len(states),
              "seconds": round(monotonic()-started, 3)}
    return certificate, report
