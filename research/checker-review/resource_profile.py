"""Measure valid but gratuitously expensive potential tables on a fixed benchmark board."""
from pathlib import Path
from unittest.mock import patch
import argparse
import json
import random
import resource
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from sokogap.core import Board, MatchingBound
from sokogap.certificates import verify_lower


parser = argparse.ArgumentParser()
parser.add_argument("--board", default="xsokoban-22")
parser.add_argument("--rows", type=int, default=100)
args = parser.parse_args()
board = Board.parse((ROOT / "instances" / (args.board + ".xsb")).read_text())
rng = random.Random(15213)
floor = sorted(board.floor)
states = set()
while len(states) < args.rows:
    raw = rng.sample(floor, len(board.boxes) + 1)
    states.add(board.state(tuple(raw[:-1]), raw[-1]))
certificate = {"format": "sokogap-potential-v1", "board_sha256": board.digest,
               "lower": 0,
               "states": [{"boxes": list(boxes), "player": player, "h": 0}
                          for boxes, player in sorted(states)]}
stats = {"board": args.board, "boxes": len(board.boxes), "states": len(states),
         "json_bytes": len(json.dumps(certificate)), "matching_calls": 0}


class CountedMatching(MatchingBound):
    def _cost(self, boxes):
        stats["matching_calls"] += 1
        return super()._cost(boxes)


started = time.monotonic()
with patch("sokogap.certificates.MatchingBound", CountedMatching):
    stats["accepted_lower"] = verify_lower(board, certificate)
stats["elapsed_seconds"] = round(time.monotonic() - started, 3)
stats["peak_rss_mib"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 3)
print(json.dumps(stats, indent=2))
