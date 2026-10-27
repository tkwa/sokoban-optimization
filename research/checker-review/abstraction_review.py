"""Independent finite-state cross-check of additive priced abstractions."""
from collections import deque
from itertools import combinations
from pathlib import Path
import json
import random
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from review_checks import graph, region
from sokogap.core import Board
from sokogap.abstraction import AbstractGraph, positions, verify_abstraction


def canonical_graph(states, outgoing, reverse):
    canonical = {}
    components = {}
    for state in states:
        if state not in canonical:
            component = region(state, outgoing)
            key = tuple(sorted(state[0])), min(p for _, p in component)
            canonical.update((s, key) for s in component)
            components[key] = component
    reverse_pushes = {key: set() for key in components}
    for key, component in components.items():
        for walked in component:
            for child, cost in outgoing[walked]:
                if cost:
                    reverse_pushes[canonical[child]].add(key)
    return canonical, reverse_pushes


def exact_priced(states, reverse, goals, prices):
    # Label-correcting queue on the full player-step graph, independent of both
    # the production bitset component graph and its heap-based shortest paths.
    goal_prices = dict(zip(sorted(goals), prices))
    best = {state: -sum(goal_prices[b] for b in state[0])
            for state in states if state[0] <= goals}
    queue = deque(best)
    queued = set(best)
    while queue:
        state = queue.popleft()
        queued.remove(state)
        for previous, cost in reverse[state]:
            value = best[state] + cost
            if previous not in best or value < best[previous]:
                best[previous] = value
                if previous not in queued:
                    queued.add(previous)
                    queue.append(previous)
    return best


def main():
    rng = random.Random(582171)
    stats = {"goal_layouts": 0, "abstract_graphs": 0, "reverse_edge_sets": 0,
             "priced_state_distances": 0, "partition_certificates": 0}
    width = 6
    interior = {y * width + x for y in range(1, 4) for x in range(1, 5)}
    for floor in [interior, interior - {14}, interior - {8, 15}]:
        full_states, full_outgoing, full_reverse = graph(width, floor, 3)
        all_goals = list(combinations(sorted(floor), 3))
        for chosen_goals in rng.sample(all_goals, 8):
            goals = frozenset(chosen_goals)
            initial = full_states[0]
            board = Board(width, 5, frozenset(floor), goals,
                          tuple(sorted(initial[0])), initial[1])
            stats["goal_layouts"] += 1
            price_sets = [(0, 0, 0), (-2_000_000, 2_000_000, 17),
                          tuple(rng.randrange(-20, 21) for _ in goals)]
            for size in (1, 2, 3):
                states, outgoing, reverse = graph(width, floor, size)
                canonical, ref_reverse = canonical_graph(states, outgoing, reverse)
                abstract = AbstractGraph(board, size)
                keys = [(tuple(positions(mask)), (reg & -reg).bit_length() - 1)
                        for mask, reg in abstract.nodes]
                included = set(keys)
                for node, key in enumerate(keys):
                    expected = ref_reverse[key] & included
                    actual = {keys[parent] for parent in abstract.reverse[node]}
                    assert actual == expected, (board.text(), size, key, expected, actual)
                    stats["reverse_edge_sets"] += 1
                for prices in price_sets:
                    truth = exact_priced(states, reverse, goals, prices)
                    distances = abstract.distances(prices)
                    for node, key in enumerate(keys):
                        raw = frozenset(key[0]), key[1]
                        assert distances[node] == truth.get(raw), (board.text(), size, prices, key,
                                                                  distances[node], truth.get(raw))
                        stats["priced_state_distances"] += 1
                    # Every finite-distance state must survive live-cell pruning.
                    assert all(canonical[raw] in included for raw in truth)
                stats["abstract_graphs"] += 1
            truth = exact_priced(full_states, full_reverse, goals, (0, 0, 0))
            candidates = [state for state, distance in truth.items() if distance > 0]
            for initial in rng.sample(candidates, min(3, len(candidates))):
                boxes = sorted(initial[0])
                board = Board(width, 5, frozenset(floor), goals, tuple(boxes), initial[1])
                for groups in [[boxes], [[boxes[0]], boxes[1:]], [[b] for b in boxes]]:
                    for prices in price_sets:
                        certificate = {"format": "sokogap-abstraction-v1", "board_sha256": board.digest,
                                       "lower": 0, "groups": groups, "goal_prices": list(prices)}
                        lower = verify_abstraction(board, certificate)
                        assert lower <= truth[initial], (board.text(), groups, prices, lower, truth[initial])
                        assert lower % 2 == board.push_parity
                        if len(groups) == 1:
                            assert lower == truth[initial]
                        stats["partition_certificates"] += 1
    return stats


if __name__ == "__main__":
    started = time.monotonic()
    report = main()
    report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    print(json.dumps(report, indent=2))
