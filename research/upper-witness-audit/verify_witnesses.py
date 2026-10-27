"""Recheck retained audit alternatives using two different replay implementations.

Run from the repository root:
    python3 research/upper-witness-audit/verify_witnesses.py

The independent implementation uses coordinate pairs directly from the XSB text;
it does not import Board, step, reachable, or replay from the benchmark kernel.
The separate kernel pass supplies the canonical board digest and cross-check.
"""

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def independent_replay(board_text, trace):
    lines = board_text.splitlines()
    tiles = {(x, y): c for y, line in enumerate(lines) for x, c in enumerate(line)}
    boxes = {p for p, c in tiles.items() if c in "$*"}
    goals = {p for p, c in tiles.items() if c in ".*+"}
    players = [p for p, c in tiles.items() if c in "@+"]
    assert len(players) == 1 and len(boxes) == len(goals) > 0
    player = players[0]
    moves = pushes = 0
    vectors = {"l": (-1, 0), "r": (1, 0), "u": (0, -1), "d": (0, 1)}
    for action in trace:
        if action in " \t\r\n":
            continue
        assert boxes != goals, "action after completion"
        assert action.lower() in vectors, "unknown action"
        dx, dy = vectors[action.lower()]
        destination = player[0] + dx, player[1] + dy
        assert destination in tiles and tiles[destination] != "#", "wall/outside"
        if destination in boxes:
            beyond = destination[0] + dx, destination[1] + dy
            assert beyond in tiles and tiles[beyond] != "#", "push into wall/outside"
            assert beyond not in boxes, "push into box"
            boxes.remove(destination)
            boxes.add(beyond)
            pushes += 1
        player = destination
        moves += 1
    assert boxes == goals, "incomplete solution"
    return moves, pushes


def main():
    from sokogap.core import Board, replay

    audit = ROOT / "research/upper-witness-audit"
    results = []
    for row in json.loads((audit / "best-available-witnesses.json").read_text()):
        board_path = ROOT / f"instances/xsokoban-{row['number']}.xsb"
        solution_path = ROOT / row["solution_path"]
        board_text = board_path.read_text()
        trace = solution_path.read_text()
        moves, pushes = independent_replay(board_text, trace)
        board = Board.parse(board_text)
        kernel = replay(board, trace)
        assert (moves, pushes) == (kernel.moves, kernel.pushes)
        assert (moves, pushes) == (row["moves"], row["pushes"])
        assert board.digest == row["board_sha256"]
        assert hashlib.sha256(solution_path.read_bytes()).hexdigest() == row["solution_sha256"]
        results.append({
            "number": row["number"],
            "moves": moves,
            "pushes": pushes,
            "board_sha256": board.digest,
            "solution_sha256": row["solution_sha256"],
            "independent_coordinate_replay": "accepted",
            "benchmark_kernel_replay": "accepted",
            "live_record_pushes": row["live_record_pushes"],
            "matches_live_record": pushes == row["live_record_pushes"],
        })
    (audit / "independent-replay-results.json").write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
