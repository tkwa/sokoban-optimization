"""Independent offline audit of the reference kernel; no production imports for graph generation.

Run from the repository root: python3 research/checker-review/review_checks.py
"""
from collections import defaultdict, deque
from itertools import combinations
from pathlib import Path
import json
import random
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from sokogap.core import Board, MatchingBound, INFINITY, replay
from sokogap.certificates import verify_lower
from sokogap.judge import audit, read_json


def adjacent(pos, width, floor):
    x, y = pos % width, pos // width
    for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
        q = (y + dy) * width + x + dx
        if 0 <= x + dx < width and y + dy >= 0 and q in floor:
            yield q, dx, dy


def graph(width, floor, box_count):
    states = [(frozenset(boxes), player)
              for boxes in combinations(sorted(floor), box_count)
              for player in sorted(floor - set(boxes))]
    reverse = defaultdict(list)
    outgoing = {}
    for boxes, player in states:
        edges = []
        for dest, dx, dy in adjacent(player, width, floor):
            if dest in boxes:
                x, y = dest % width, dest // width
                beyond = (y + dy) * width + x + dx
                if not 0 <= x + dx < width or beyond not in floor or beyond in boxes:
                    continue
                child = ((boxes - {dest}) | {beyond}, dest)
                cost = 1
            else:
                child, cost = (boxes, dest), 0
            edges.append((child, cost))
            reverse[child].append(((boxes, player), cost))
        outgoing[(boxes, player)] = edges
    return states, outgoing, reverse


def region(start, outgoing):
    found = {start}
    todo = [start]
    while todo:
        for child, cost in outgoing[todo.pop()]:
            if not cost and child not in found:
                found.add(child)
                todo.append(child)
    return found


def run_graph_checks():
    rng = random.Random(917251)
    stats = {"floor_layouts": 0, "goal_layouts": 0, "raw_states": 0,
             "solvable_state_checks": 0, "canonical_transition_checks": 0,
             "matching_consistency_edges": 0, "exact_certificates": 0}
    width = 6
    interior = {y * width + x for y in range(1, 4) for x in range(1, 5)}
    layouts = [interior, interior - {14}, interior - {8, 15}]
    for floor in layouts:
        for box_count in (1, 2):
            stats["floor_layouts"] += 1
            states, outgoing, reverse = graph(width, floor, box_count)
            canonical = {}
            for state in states:
                if state not in canonical:
                    component = region(state, outgoing)
                    key = tuple(sorted(state[0])), min(p for _, p in component)
                    canonical.update((s, key) for s in component)
            distinct = set(canonical.values())
            goal_layouts = list(combinations(sorted(floor), box_count))
            if len(goal_layouts) > 12:
                goal_layouts = rng.sample(goal_layouts, 12)
            for goals in goal_layouts:
                goal_set = frozenset(goals)
                exact = {}
                queue = deque()
                for state in states:
                    if state[0] == goal_set:
                        exact[state] = 0
                        queue.append(state)
                while queue:
                    state = queue.popleft()
                    for previous, cost in reverse[state]:
                        value = exact[state] + cost
                        if value < exact.get(previous, INFINITY):
                            exact[previous] = value
                            (queue.append if cost else queue.appendleft)(previous)
                stats["goal_layouts"] += 1
                stats["raw_states"] += len(states)
                initial = next(s for s in states if s in exact)
                board = Board(width, 5, frozenset(floor), goal_set,
                              tuple(sorted(initial[0])), initial[1])
                base = MatchingBound(board)
                for raw in states:
                    if raw in exact:
                        assert base.cost(tuple(sorted(raw[0]))) <= exact[raw]
                        assert exact[raw] % 2 == (sum(p % width + p // width for p in goal_set)
                                                - sum(p % width + p // width for p in raw[0])) % 2
                        stats["solvable_state_checks"] += 1
                for key in distinct:
                    raw = frozenset(key[0]), key[1]
                    expected = {canonical[child]
                                for walked in region(raw, outgoing)
                                for child, cost in outgoing[walked] if cost}
                    actual = set(board.successors(key))
                    assert actual == expected, (board.text(), key, expected, actual)
                    stats["canonical_transition_checks"] += 1
                    for child in actual:
                        assert base.cost(key[0]) <= 1 + base.cost(child[0])
                        stats["matching_consistency_edges"] += 1
                # Exact distances on every quotient state form a complete potential certificate.
                # Set a finite constant on dead states, which cannot lead to a solvable state.
                cap = 100
                proof_rows = [{"boxes": list(key[0]), "player": key[1],
                               "h": exact.get((frozenset(key[0]), key[1]), cap)}
                              for key in sorted(distinct)]
                nontrivial = [s for s in states if 0 < exact.get(s, 0) < cap]
                if nontrivial:
                    initial = max(nontrivial, key=lambda s: exact[s])
                    board = Board(width, 5, frozenset(floor), goal_set,
                                  tuple(sorted(initial[0])), initial[1])
                    cert = {"format": "sokogap-potential-v1", "board_sha256": board.digest,
                            "lower": exact[initial], "states": proof_rows}
                    assert verify_lower(board, cert) == exact[initial]
                    stats["exact_certificates"] += 1
    return stats


def malformed_and_freeze_checks():
    result = {}
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        deep = root / "deep.json"
        deep.write_text("[" * 2000 + "0" + "]" * 2000)
        try:
            read_json(deep)
        except Exception as error:
            result["deep_json_exception"] = type(error).__name__
        board = Board.parse("#######\n#@ $ .#\n#     #\n#######\n")
        (root / "board.xsb").write_text(board.text())
        (root / "solution.lurd").write_text("rrr")
        manifest = {"format": "sokogap-benchmark-v1", "benchmark_id": "review-loose-baseline",
                    "status": "frozen", "metric": "pushes", "aggregation": "total_gap_closed",
                    "instances": [{"id": str(i), "board": "board.xsb", "board_sha256": board.digest,
                                   "lower": 0, "upper": 4, "upper_solution": "solution.lurd"}
                                  for i in range(10)]}
        path = root / "benchmark.json"
        path.write_text(json.dumps(manifest))
        report = audit(path)[0]
        result["loose_baseline_scoreable"] = report["scoreable"]
        result["loose_declared_gap"] = report["declared_total_gap"]
        result["bundled_evidence_actual_gap"] = sum(r["replayed_upper"] - r["verified_lower"]
                                                   for r in report["instances"])
        manifest["instances"][0] = None
        path.write_text(json.dumps(manifest))
        try:
            audit(path)
        except Exception as error:
            result["nonobject_manifest_row_exception"] = type(error).__name__
    return result


if __name__ == "__main__":
    started = time.monotonic()
    report = {"graph_checks": run_graph_checks(), "input_and_freeze": malformed_and_freeze_checks()}
    report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    print(json.dumps(report, indent=2))
