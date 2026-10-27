from collections import deque
from itertools import permutations
import json
from pathlib import Path
import random
import tempfile
import unittest

from sokogap.certificates import verify_lower
from sokogap.core import Board, Invalid, MatchingBound, assignment_cost, replay
from sokogap.judge import audit, judge, read_json, read_text
from sokogap.release import prepare_freeze
from sokogap.runner import run_limited
from sokogap.scoring import Bounds, score
from sokogap.search import prove


SIMPLE = "#######\n#@ $ .#\n#     #\n#######\n"
GAP_BOARD = "#######\n#.@ # #\n#  $$ #\n#   # #\n#    .#\n#######\n"
GAP_SOLUTION = "rdllddrrrruulldluruldddrr"


def exact_distance(board, boxes, player):
    """Independent 0-1 BFS over individual player steps, without pruning."""
    initial = frozenset(boxes), player
    best = {initial: 0}
    queue = deque([initial])
    while queue:
        state = queue.popleft()
        boxes, player = state
        if boxes == board.goals:
            return best[state]
        x, y = player % board.width, player // board.width
        for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            nx, ny = x+dx, y+dy
            if not (0 <= nx < board.width and 0 <= ny < board.height):
                continue
            dest = ny*board.width+nx
            if dest not in board.floor:
                continue
            cost = 0
            moved = boxes
            if dest in boxes:
                bx, by = nx+dx, ny+dy
                beyond = by*board.width+bx
                if not (0 <= bx < board.width and 0 <= by < board.height) or beyond not in board.floor or beyond in boxes:
                    continue
                moved = (boxes-{dest}) | {beyond}
                cost = 1
            child = moved, dest
            if best[state]+cost < best.get(child, 10**9):
                best[child] = best[state]+cost
                (queue.append if cost else queue.appendleft)(child)
    return None


class RulesTests(unittest.TestCase):
    def test_push_parity_for_even_and_odd_boards(self):
        even = Board.parse(SIMPLE)
        odd = Board.parse("######\n#@ $.#\n#    #\n######\n")
        self.assertEqual(even.push_parity, 0)
        self.assertEqual(odd.push_parity, 1)
        self.assertEqual(replay(even, "rrr").pushes % 2, even.push_parity)
        self.assertEqual(replay(odd, "rr").pushes % 2, odd.push_parity)

    def test_replay_counts_actual_pushes(self):
        board = Board.parse(SIMPLE)
        self.assertEqual(vars(replay(board, "rRr")), {"moves": 3, "pushes": 2})
        self.assertEqual(replay(board, "rrr"), replay(board, "RRR"))
        for bad in ("u", "rr", "rrrl", "rrrx", "r0r", "rrr☃"):
            with self.subTest(bad=bad), self.assertRaises(Invalid):
                replay(board, bad)

    def test_cannot_push_two_boxes_or_a_wall(self):
        board = Board.parse("#######\n#@$$..#\n#######\n")
        with self.assertRaises(Invalid):
            replay(board, "r")

    def test_malformed_boards_rejected(self):
        for text in ("", "###\n#@$ .\n###", "####\n#@.#\n####", "####\n#@@#\n#$*#\n####"):
            with self.subTest(text=text), self.assertRaises(Invalid):
                Board.parse(text)

    def test_matching_against_exhaustive_permutations(self):
        rng = random.Random(512)
        for n in range(1, 7):
            for _ in range(20):
                costs = [[rng.randrange(30) for _ in range(n)] for _ in range(n)]
                exact = min(sum(costs[i][j] for i, j in enumerate(p)) for p in permutations(range(n)))
                self.assertEqual(assignment_cost(costs), exact)

    def test_bound_and_push_search_against_independent_walk_search(self):
        rng = random.Random(42)
        # Varied walls, goals, box placements, deadlocks, and player regions.
        for sample in range(45):
            floor = {y*6+x for y in range(1, 4) for x in range(1, 5)}
            for pos in rng.sample(sorted(floor), rng.randrange(3)):
                floor.remove(pos)
            pieces = rng.sample(sorted(floor), 5)
            board = Board(6, 5, frozenset(floor), frozenset(pieces[:2]), tuple(sorted(pieces[2:4])), pieces[4])
            exact = exact_distance(board, board.boxes, board.player)
            if exact is None:
                continue
            with self.subTest(sample=sample):
                self.assertLessEqual(MatchingBound(board).cost(board.boxes), exact)
                certificate, result = prove(board, expansions=10_000, seconds=5)
                self.assertEqual(result["lower"], exact)
                self.assertEqual(verify_lower(board, certificate), exact)


class CertificateTests(unittest.TestCase):
    def setUp(self):
        self.board = Board.parse(SIMPLE)

    def test_matching_certificate_and_forgery(self):
        cert = {"format": "sokogap-potential-v1", "board_sha256": self.board.digest, "lower": 2, "states": []}
        self.assertEqual(verify_lower(self.board, cert), 2)
        for change in ({"lower": 3}, {"lower": True}, {"board_sha256": "wrong"}):
            with self.subTest(change=change), self.assertRaises(Invalid):
                verify_lower(self.board, cert | change)

    def test_transition_and_goal_forgery(self):
        state = self.board.initial
        cert = {"format": "sokogap-potential-v1", "board_sha256": self.board.digest, "lower": 3,
                "states": [{"boxes": list(state[0]), "player": state[1], "h": 3}]}
        with self.assertRaisesRegex(Invalid, "transition"):
            verify_lower(self.board, cert)
        goal = self.board.state(tuple(self.board.goals), self.board.player)
        cert["states"] = [{"boxes": list(goal[0]), "player": goal[1], "h": 1}]
        with self.assertRaisesRegex(Invalid, "goal"):
            verify_lower(self.board, cert)

    def test_stronger_bound_and_one_push_forgery(self):
        board = Board.parse("#######\n#.@ # #\n#  $$ #\n#   # #\n#    .#\n#######\n")
        self.assertEqual(MatchingBound(board).cost(board.boxes), 6)
        self.assertEqual(exact_distance(board, board.boxes, board.player), 8)
        certificate, _ = prove(board, expansions=1000, seconds=5)
        self.assertGreater(len(certificate["states"]), 0)
        self.assertEqual(verify_lower(board, certificate), 8)
        certificate["lower"] = 9
        certificate["states"][0]["h"] = 9
        with self.assertRaisesRegex(Invalid, "transition"):
            verify_lower(board, certificate)

    def test_valid_lower_bound_rounded_to_solution_parity(self):
        board = Board.parse("#######\n#.@ # #\n#  $$ #\n#   # #\n#    .#\n#######\n")
        certificate, _ = prove(board, expansions=1000, seconds=5)
        certificate["lower"] = 7
        for row in certificate["states"]:
            row["h"] = min(row["h"], 7)
        self.assertEqual(verify_lower(board, certificate), 8)
        odd = Board.parse("######\n#@ $.#\n#    #\n######\n")
        certificate = {"format": "sokogap-potential-v1", "board_sha256": odd.digest, "lower": 0, "states": []}
        self.assertEqual(verify_lower(odd, certificate), 1)


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.baseline = {str(i): Bounds(100, 110 if i else 200) for i in range(10)}

    def test_each_push_has_equal_weight(self):
        a = score(self.baseline, {"0": Bounds(101, 200)})
        b = score(self.baseline, {"1": Bounds(100, 109)})
        self.assertEqual(a["score_percent_exact"], b["score_percent_exact"])
        self.assertEqual(a["score_percent_exact"], "10/19")

    def test_zero_full_missing_and_worse(self):
        self.assertEqual(score(self.baseline, {})["score_percent"], 0)
        self.assertEqual(score(self.baseline, {"1": Bounds(99, 112)})["score_percent"], 0)
        full = {name: Bounds(b.upper, b.upper) for name, b in self.baseline.items()}
        self.assertEqual(score(self.baseline, full)["score_percent"], 100)

    def test_both_sides_and_repeat_are_not_double_counted(self):
        update = {"0": Bounds(101, 199)}
        self.assertEqual(score(self.baseline, update)["pushes_closed"], 2)
        self.assertEqual(score(self.baseline, update), score(self.baseline, update))

    def test_contradictions_and_unknown_instances_rejected(self):
        with self.assertRaises(Invalid):
            self.baseline["0"].improve(lower=201)
        with self.assertRaises(Invalid):
            score(self.baseline, {"unknown": Bounds(1, 1)})


class EndToEndTests(unittest.TestCase):
    def fixture(self, root):
        # Ten distinct encoded boards with a genuine matching6/solution8 gap.
        rows = []
        for i in range(10):
            board = Board.parse("\n".join(line + "#" * i for line in GAP_BOARD.splitlines()))
            name = f"board-{i}.xsb"
            (root/name).write_text(board.text())
            rows.append({"id": str(i), "board": name, "board_sha256": board.digest,
                         "lower": 6, "upper": 8, "upper_solution": "solution.lurd"})
        (root/"solution.lurd").write_text(GAP_SOLUTION)
        draft = {"format": "sokogap-benchmark-v1", "benchmark_id": "test-fixture-only",
                 "status": "draft", "metric": "pushes", "aggregation": "total_gap_closed", "instances": rows}
        draft_path, path = root/"draft.json", root/"benchmark.json"
        draft_path.write_text(json.dumps(draft))
        prepare_freeze(draft_path, path)
        return path, read_json(path), Board.parse((root/"board-0.xsb").read_text())

    def test_score_requires_evidence_and_exact_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            mp, manifest, board = self.fixture(root)
            sp = root/"submission.json"
            report, _, _ = audit(mp)
            self.assertTrue(report["scoreable"])
            manifest["instances"][0]["lower"] = 5
            mp.write_text(json.dumps(manifest))
            parity_audit, _, _ = audit(mp)
            self.assertFalse(parity_audit["scoreable"])
            self.assertIn("solution parity", parity_audit["instances"][0]["problems"][0])
            manifest["instances"][0]["lower"] = 6
            manifest["instances"][0]["upper"] = 9
            mp.write_text(json.dumps(manifest))
            self.assertFalse(audit(mp)[0]["scoreable"])
            manifest["instances"][0]["upper"] = 8
            mp.write_text(json.dumps(manifest))
            # Whitespace changes to a manifest also require its new identity.
            report, _, _ = audit(mp)
            cert, _ = prove(board, expansions=1000, seconds=5)
            submission = {"benchmark_sha256": report["manifest_sha256"], "instances": {"0": {"lower_certificate": cert}}}
            sp.write_text(json.dumps(submission))
            self.assertEqual(judge(mp, sp)["score_percent"], 10)
            limited, status = run_limited("score", [mp, sp])
            self.assertEqual(status, 0)
            self.assertEqual(limited["score_percent_exact"], "10/1")
            submission["instances"]["0"] = {"lower": 2}
            sp.write_text(json.dumps(submission))
            with self.assertRaisesRegex(Invalid, "raw bound"):
                judge(mp, sp)
            manifest["instances"][0]["upper_solution"] = None
            mp.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(Invalid, "baseline evidence"):
                judge(mp, sp)

    def test_baseline_uses_all_bundled_evidence_and_pins_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path, manifest, board = self.fixture(root)
            original = path.read_text()
            for key, value in (("lower", 4), ("upper", 10)):
                changed = json.loads(original)
                changed["instances"][0][key] = value
                path.write_text(json.dumps(changed))
                result, _, _ = audit(path)
                self.assertFalse(result["evidence_ready"])
                self.assertIn("must use", " ".join(result["instances"][0]["problems"]))
            path.write_text(original)
            (root/"solution.lurd").write_text(GAP_SOLUTION + "\n")
            result, _, _ = audit(path)
            self.assertTrue(result["evidence_ready"])
            self.assertFalse(result["scoreable"])
            self.assertIn("data_files", " ".join(result["release_problems"]))
            with self.assertRaisesRegex(Invalid, "already exists"):
                prepare_freeze(root/"draft.json", path)

    def test_malformed_and_oversize_inputs_fail_cleanly(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            deep = root/"deep.json"
            deep.write_text("[" * 2000 + "0" + "]" * 2000)
            with self.assertRaisesRegex(Invalid, "nesting"):
                read_json(deep)
            with self.assertRaisesRegex(Invalid, "size limit"):
                read_text(deep, 100)
            path, manifest, _ = self.fixture(root)
            manifest["instances"][0] = None
            path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(Invalid, "instance must be an object"):
                audit(path)
            result, status = run_limited("audit", [path])
            self.assertEqual(status, 1)
            self.assertEqual(result["outcome"], "invalid")

    def test_duplicate_json_keys_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"invalid.json"
            path.write_text('{"lower": 1, "lower": 99}')
            with self.assertRaises(Invalid):
                read_json(path)


if __name__ == "__main__":
    unittest.main()
