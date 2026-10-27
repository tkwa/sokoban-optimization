from hashlib import sha256
from importlib.util import find_spec
from pathlib import Path
import tempfile
import unittest

from sokogap.certificates import verify_lower
from sokogap.core import Board, Invalid
from sokogap.lrat import check_lrat
from sokogap.runner import run_limited
from sokogap.sat import CNF, encode_push_bound


def formula(*clauses):
    cnf = CNF()
    cnf.nvars = max((abs(v) for row in clauses for v in row), default=0)
    for row in clauses:
        cnf.add(*row)
    return cnf


class LRATTests(unittest.TestCase):
    def test_checked_example_verifies_without_a_solver(self):
        import json
        root = Path(__file__).resolve().parents[1] / "examples"
        board = Board.parse((root / "two-box-detour.xsb").read_text())
        certificate = json.loads((root / "two-box-detour.sat-lrat.json").read_text())
        self.assertEqual(verify_lower(board, certificate), 8)

    def test_rup_empty_and_deletion_with_repeated_line_id(self):
        cnf = formula((1,), (-1,))
        check_lrat(cnf, "3 2 0 0\n3 d 3 0\n4 0 1 2 0\n")
        check_lrat(cnf, "c test\n3 0 1 2 0\n")

    def test_rat_shared_prefix_and_all_opposite_clauses(self):
        cnf = formula((1,), (-1,), (-3, 4), (-3, -4))
        check_lrat(cnf, "5 3 0 1 -3 2 -4 2 0\n6 0 1 2 0\n")
        for proof in ("5 3 0 1 -3 2 0\n6 0 1 2 0\n",
                      "5 3 0 1 -3 2 -3 2 -4 2 0\n6 0 1 2 0\n"):
            with self.assertRaises(Invalid):
                check_lrat(cnf, proof)

    def test_invalid_steps_cannot_refute_satisfiable_formula(self):
        cnf = formula((1, 2), (-1, 2))
        for proof in ("3 0 1 2 0\n", "3 1 0 0\n4 0 3 0\n",
                      "3 2 0 1 2 0\n4 0 3 0\n", "3 0 999 0\n"):
            with self.subTest(proof=proof), self.assertRaises(Invalid):
                check_lrat(cnf, proof)

    def test_bad_syntax_reused_deleted_ids_and_truncation(self):
        cnf = formula((1,), (-1,))
        for proof in ("", "3 2 0 0\n", "3 0 1 2\n", "3 0 1 2 0 0\n",
                      "3 2 0 0\n3 0 1 2 0\n", "3 d 1 0\n4 0 1 2 0\n",
                      "3 0 1 2 0\n4 d 1 0\n", "3 0 ☃ 0\n"):
            with self.subTest(proof=proof), self.assertRaises(Invalid):
                check_lrat(cnf, proof)

    def test_dimacs_hash_tracks_variable_header(self):
        cnf = formula((1,))
        before = cnf.digest
        cnf.var()
        self.assertNotEqual(cnf.digest, before)
        self.assertEqual(cnf.digest, sha256("".join(cnf.dimacs()).encode("ascii")).hexdigest())


@unittest.skipUnless(find_spec("pysat"), "optional python-sat research dependency")
class SATTests(unittest.TestCase):
    def test_exact_push_budget_and_noop_padding(self):
        from pysat.solvers import Glucose4
        for text, optimum in (("#######\n#@ $ .#\n#     #\n#######\n", 2),
                              ("#####\n#@* #\n#####\n", 0),
                              ("#######\n#@# $.#\n#######\n", None)):
            board = Board.parse(text)
            for k in range(5):
                with self.subTest(text=text, k=k):
                    cnf = encode_push_bound(board, k)
                    with Glucose4(bootstrap_with=cnf) as solver:
                        self.assertEqual(solver.solve(), optimum is not None and k >= optimum)

    def test_sat_certificate_and_hostile_changes(self):
        from scripts.prove_sat import produce
        board = Board.parse("#######\n#.@ # #\n#  $$ #\n#   # #\n#    .#\n#######\n")
        certificate = produce(board, 8)
        self.assertEqual(verify_lower(board, certificate), 8)
        for change in ({"lower": 9}, {"board_sha256": "0" * 64}, {"cnf_sha256": "0" * 64},
                       {"encoding": "other"}, {"proof": ""}, {"lower": True}):
            with self.subTest(change=change), self.assertRaises(Invalid):
                verify_lower(board, certificate | change)
        with self.assertRaisesRegex(Invalid, "solution exists"):
            produce(board, 9)

    def test_limited_encoder_and_certificate(self):
        from scripts.prove_sat import produce
        import json
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            board = Board.parse("#######\n#@ $ .#\n#     #\n#######\n")
            bp, cp, pp = root / "board.xsb", root / "bound.cnf", root / "certificate.json"
            bp.write_text(board.text())
            result, code = run_limited("encode-sat", [bp, cp], parameters=["2"])
            self.assertEqual(code, 0)
            self.assertEqual(result["cnf_sha256"], sha256(cp.read_bytes()).hexdigest())
            self.assertEqual(result["max_pushes"], 1)
            pp.write_text(json.dumps(produce(board, 2)))
            result, code = run_limited("verify-lower", [bp, pp])
            self.assertEqual(code, 0)
            self.assertEqual(result["verified_lower"], 2)


if __name__ == "__main__":
    unittest.main()
