"""Independent checks for signed four-box potential certificates."""
from copy import deepcopy
from pathlib import Path
import json
import random
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from review_checks import graph
from abstraction_review import canonical_graph, exact_priced
from sokogap.core import Board, Invalid
from sokogap.abstraction import AbstractGraph, PatternHeuristic, verify_abstraction, verify_pattern_potentials


def must_reject(board, certificate):
    try:
        verify_abstraction(board, certificate)
    except Invalid:
        return
    raise AssertionError("forged or malformed v2 certificate accepted")


def main():
    rng = random.Random(381963)
    width = 6
    interior = {y * width + x for y in range(1, 4) for x in range(1, 5)}
    larger = {y * width + x for y in range(1, 5) for x in range(1, 5)}
    stats = {"boards": 0, "priced_heuristic_checks": 0, "sparse_pattern_checks": 0,
             "full_certificate_checks": 0, "forgeries_rejected": 0, "largest_sparse_proof": 0,
             "initial_understatement_cases": 0}
    for floor in [interior, interior - {14}, interior - {8, 15}, larger]:
        four_states, four_outgoing, four_reverse = graph(width, floor, 4)
        canonical, _ = canonical_graph(four_states, four_outgoing, four_reverse)
        distinct = sorted(set(canonical.values()))
        for box_count in (4, 5):
            full_states, _, full_reverse = graph(width, floor, box_count)
            # Favor at least one live box position while varying congestion/goals.
            goals_list = ([7, 10, 25, 28] + ([14] if box_count == 5 else [])) if floor == larger else rng.sample(sorted(floor), box_count)
            goals = frozenset(goals_list)
            exact_full = exact_priced(full_states, full_reverse, goals, [0] * box_count)
            candidates = [raw for raw, distance in exact_full.items() if distance > 0]
            if not candidates:
                continue
            initial = max(candidates, key=lambda raw: exact_full[raw])
            boxes = tuple(sorted(initial[0]))
            board = Board(width, 6, frozenset(floor), goals, boxes, initial[1])
            group = list(boxes[:4])
            stats["boards"] += 1
            graphs = {size: AbstractGraph(board, size) for size in (1, 2, 3)}
            price_sets = [[0] * box_count,
                          [(-1 if i % 2 else 1) * 2_000_000 for i in range(box_count)],
                          [rng.randrange(-20, 21) for _ in range(box_count)]]
            for prices in price_sets:
                truth = exact_priced(four_states, four_reverse, goals, prices)
                distances = {size: g.distances(prices) for size, g in graphs.items()}
                heuristic = PatternHeuristic(board, prices, graphs, distances)
                rows = []
                for state in distinct:
                    raw = frozenset(state[0]), state[1]
                    default = heuristic.value(state)
                    if raw in truth:
                        assert default <= truth[raw], (board.text(), prices, state, default, truth[raw])
                        stats["priced_heuristic_checks"] += 1
                    target = truth.get(raw, 10_000_000)
                    if target > default:
                        rows.append({"boxes": list(state[0]), "player": state[1], "h": target})
                stats["largest_sparse_proof"] = max(stats["largest_sparse_proof"], len(rows))
                # Exact potentials need only list states where the fallback is weaker.
                expected = truth[(frozenset(group), initial[1])]
                verified = verify_pattern_potentials(board, group, rows, heuristic)
                assert verified == expected, (board.text(), prices, verified, expected)
                stats["sparse_pattern_checks"] += 1
                groups = [group] + [[b] for b in boxes[4:]]
                cert = {"format": "sokogap-abstraction-v2", "board_sha256": board.digest,
                        "lower": 0, "groups": groups, "goal_prices": prices,
                        "pattern_potentials": [{"group": group, "states": rows}]}
                lower = verify_abstraction(board, cert)
                assert 0 <= lower <= exact_full[initial]
                assert lower % 2 == board.push_parity
                if box_count == 4:
                    assert lower == exact_full[initial]
                stats["full_certificate_checks"] += 1
                initial_state = board.state(tuple(group), board.player)
                forged = deepcopy(cert)
                forged_rows = forged["pattern_potentials"][0]["states"]
                forged_rows[:] = [r for r in forged_rows if (tuple(r["boxes"]), r["player"]) != initial_state]
                forged_rows.append({"boxes": list(initial_state[0]), "player": initial_state[1], "h": expected + 1})
                must_reject(board, forged)
                stats["forgeries_rejected"] += 1
                terminal = next(raw for raw in truth if raw[0] <= goals)
                terminal_state = canonical[terminal]
                forged = deepcopy(cert)
                forged_rows = forged["pattern_potentials"][0]["states"]
                forged_rows[:] = [r for r in forged_rows if (tuple(r["boxes"]), r["player"]) != terminal_state]
                cap = heuristic.terminal(terminal_state[0])
                forged_rows.append({"boxes": list(terminal_state[0]), "player": terminal_state[1], "h": cap + 1})
                must_reject(board, forged)
                stats["forgeries_rejected"] += 1
                for mutate in (lambda c: c["pattern_potentials"].append(deepcopy(c["pattern_potentials"][0])),
                               lambda c: c["pattern_potentials"].clear(),
                               lambda c: c["groups"].append([boxes[0]])):
                    forged = deepcopy(cert)
                    mutate(forged)
                    must_reject(board, forged)
                    stats["forgeries_rejected"] += 1
                # Record whether the implementation uses already-computed fallback
                # evidence when a table unnecessarily weakens its initial state.
                weak = [{"boxes": list(state[0]), "player": state[1], "h": -9_999_999}
                        for state in distinct]
                weak_result = verify_pattern_potentials(board, group, weak, heuristic)
                if weak_result < heuristic.value(initial_state):
                    stats["initial_understatement_cases"] += 1
    assert stats["boards"] >= 4
    return stats


if __name__ == "__main__":
    started = time.monotonic()
    report = main()
    report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    print(json.dumps(report, indent=2))
