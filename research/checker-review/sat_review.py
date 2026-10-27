"""Independent bounded-SAT versus exhaustive player-step search comparison.

PySAT is an untrusted test oracle, not part of the release verifier. The exact
reference graph never calls the production transition or reachability methods.
Run after sokogap.sat is available; optional --case-limit trims the sample.
"""
from hashlib import sha256
from itertools import combinations
from pathlib import Path
import argparse
import json
import random
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from review_checks import graph
from abstraction_review import exact_priced
from sokogap.core import Board


def cases():
    rng = random.Random(713831)
    layouts = [
        ("two_cells", 4, 3, {5, 6}),
        ("three_cell_corridor", 5, 3, {6, 7, 8}),
        ("four_cell_corridor", 6, 3, {7, 8, 9, 10}),
        ("four_cell_square", 4, 4, {5, 6, 9, 10}),
        ("eight_disconnected", 7, 4, {8, 9, 11, 12, 15, 16, 18, 19}),
        ("nine_open", 5, 5, {5*y+x for y in range(1, 4) for x in range(1, 4)}),
        ("eight_ring", 5, 5, {5*y+x for y in range(1, 4) for x in range(1, 4)} - {12}),
        ("ten_choke", 7, 5, {8, 9, 11, 12, 15, 16, 17, 18, 19, 24}),
        ("twelve_open", 6, 5, {6*y+x for y in range(1, 4) for x in range(1, 5)}),
    ]
    for name, width, height, floor in layouts:
        for count in (1, 2):
            if count >= len(floor):
                continue
            states, _, reverse = graph(width, floor, count)
            goals_list = list(combinations(sorted(floor), count))
            if len(goals_list) > 7:
                goals_list = rng.sample(goals_list, 7)
            for goals in goals_list:
                goals = frozenset(goals)
                exact = exact_priced(states, reverse, goals, [0] * count)
                selected = set(rng.sample(states, min(4, len(states))))
                if exact:
                    selected.add(max(exact, key=exact.get))
                    selected.add(next(s for s in exact if exact[s] == 0))
                dead = [state for state in states if state not in exact]
                if dead:
                    selected.add(rng.choice(dead))
                for boxes, player in sorted(selected, key=lambda s: (tuple(sorted(s[0])), s[1])):
                    board = Board(width, height, frozenset(floor), goals,
                                  tuple(sorted(boxes)), player)
                    yield name, board, exact.get((boxes, player))
    board = Board.parse("#######\n#.@ # #\n#  $$ #\n#   # #\n#    .#\n#######\n")
    states, _, reverse = graph(board.width, set(board.floor), len(board.boxes))
    exact = exact_priced(states, reverse, board.goals, [0] * len(board.boxes))
    yield "two_box_detour", board, exact[(frozenset(board.boxes), board.player)]


def run(case_limit=None):
    from pysat.solvers import Solver
    from sokogap.sat import encode_push_bound
    stats = {"boards": 0, "sat_checks": 0, "unsat_checks": 0, "zero_stage_checks": 0,
             "noop_padding_checks": 0, "max_exact_pushes": 0, "max_variables": 0,
             "max_clauses": 0, "layouts": {}, "dimacs_hash_checks": 0}
    for index, (name, board, exact) in enumerate(cases()):
        if case_limit is not None and index >= case_limit:
            break
        bounds = {0, 3, 7} if exact is None else {0, max(0, exact - 1), exact, exact + 1}
        for bound in sorted(bounds):
            cnf = encode_push_bound(board, bound)
            with Solver(name="g3", bootstrap_with=cnf.clauses) as solver:
                answer = solver.solve()
            expected = exact is not None and exact <= bound
            assert answer == expected, {"layout": name, "board": board.text(), "bound": bound,
                                        "exact": exact, "sat": answer}
            stats["sat_checks" if answer else "unsat_checks"] += 1
            stats["zero_stage_checks"] += bound == 0
            stats["noop_padding_checks"] += exact is not None and bound > exact
            stats["max_variables"] = max(stats["max_variables"], cnf.nvars)
            stats["max_clauses"] = max(stats["max_clauses"], len(cnf.clauses))
            if index % 17 == 0:
                raw = b"".join(line if isinstance(line, bytes) else line.encode("ascii") for line in cnf.dimacs())
                assert sha256(raw).hexdigest() == cnf.digest
                assert encode_push_bound(board, bound).digest == cnf.digest
                stats["dimacs_hash_checks"] += 1
        stats["boards"] += 1
        stats["layouts"][name] = stats["layouts"].get(name, 0) + 1
        if exact is not None:
            stats["max_exact_pushes"] = max(stats["max_exact_pushes"], exact)
    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-limit", type=int)
    args = parser.parse_args()
    started = time.monotonic()
    report = run(args.case_limit)
    report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    print(json.dumps(report, indent=2))
