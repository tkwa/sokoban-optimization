from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sokogap.core import Invalid
from sokogap.judge import audit, judge
from sokogap.proofs import RULES_VERSION
from sokogap.runner import run_limited
from sokogap.search import prove
import test_judge


class ProofPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest, _, self.board = test_judge.EndToEndTests().fixture(self.root)
        self.manifest_hash = audit(self.manifest)[0]["manifest_sha256"]
        self.cert, _ = prove(self.board, expansions=1000, seconds=5)
        self.submission = self.root / "submission.json"
        self.registry = self.root / "trusted-reviews.json"

    def submit(self, evidence):
        self.submission.write_text(json.dumps({"benchmark_sha256": self.manifest_hash, "instances": {"0": evidence}}))

    def review(self, digest, lower=8):
        data = {"format": "sokogap-proof-reviews-v1", "benchmark_sha256": self.manifest_hash,
                "submission_sha256": sha256(self.submission.read_bytes()).hexdigest(),
                "rules_version": RULES_VERSION,
                "decisions": [{"instance": "0", "board_sha256": self.board.digest,
                               "proof_sha256": digest, "status": "accepted", "verified_lower": lower,
                               "reviewer": "test-fixture operator",
                               "verification": "Independently checked the external potential certificate fixture"}]}
        self.registry.write_text(json.dumps(data))
        return data

    def test_best_valid_proof_counts_even_with_weaker_and_invalid_proofs(self):
        weak = {"format": "sokogap-potential-v1", "board_sha256": self.board.digest, "lower": 6, "states": []}
        invalid = weak | {"lower": 9}
        self.submit({"lower_certificates": [weak, invalid, self.cert, weak, {"format": []}]})
        result = judge(self.manifest, self.submission)
        self.assertEqual(result["score_percent"], 10)
        self.assertTrue(result["accepted"])
        self.assertEqual([p["status"] for p in result["lower_proofs"]["0"]],
                         ["accepted", "rejected", "accepted", "accepted", "rejected"])

    def test_arbitrary_artifact_pending_then_trusted_review_counts(self):
        artifact = self.root / "proof.any-format"
        artifact.write_text(json.dumps(self.cert))  # A real valid proof, carried as an arbitrary artifact.
        self.submit({"lower_proofs": [{"lower": 1000, "artifact": artifact.name}]})
        result = judge(self.manifest, self.submission)
        self.assertEqual(result["outcome"], "pending_review")
        self.assertIsNone(result["accepted"])
        self.assertNotIn("score_percent", result)
        self.assertEqual(result["provisional_score_percent"], 0)
        limited, code = run_limited("score", [self.manifest, self.submission])
        self.assertEqual(code, 2)
        self.assertEqual(limited["outcome"], "pending_review")
        self.review(sha256(artifact.read_bytes()).hexdigest())
        result, code = run_limited("score", [self.manifest, self.submission, self.registry])
        self.assertEqual(code, 0)
        self.assertEqual(result["score_percent"], 10)  # Approved8, not the participant's1000.
        self.assertEqual(result["instances"][0]["lower"], 8)
        self.assertIsNotNone(result["reviews_sha256"])
        artifact.write_text("changed proof")
        result = judge(self.manifest, self.submission, self.registry)
        self.assertEqual(result["outcome"], "pending_review")

    def test_unknown_inline_language_pending_and_approval_cannot_self_authorize(self):
        self.submit({"lower_certificate": {"format": "some-new-proof-language", "theorem": "OPT>=8"}})
        result = judge(self.manifest, self.submission)
        self.assertEqual(result["outcome"], "pending_review")
        self.submit({"lower_proofs": [{"lower": 8, "artifact": "trusted-reviews.json", "status": "accepted"}]})
        with self.assertRaises(Invalid):
            judge(self.manifest, self.submission)

    def test_adapter_limit_can_be_resolved_by_independent_review(self):
        sample = Path(__file__).resolve().parents[1] / "examples/two-box-detour.sat-lrat.json"
        certificate = json.loads(sample.read_text())
        self.submit({"lower_certificates": [certificate, self.cert]})
        with patch("sokogap.sat.MAX_PUSHES", 0):
            # The published fixture lock also pins MAX_PUSHES. Patch only the
            # adapter call after baseline audit so the frozen baseline stays valid.
            from sokogap.proofs import evaluate_lower_proofs
            lower, records, waiting = evaluate_lower_proofs(
                self.board, "0", {"lower_certificates": [certificate, self.cert]}, self.root, {})
        self.assertEqual(lower, 8)
        self.assertEqual(waiting, 1)
        self.assertEqual(records[0]["status"], "pending_review")
        self.review(records[0]["proof_sha256"])
        result = judge(self.manifest, self.submission, self.registry)
        self.assertEqual(result["score_percent"], 10)
        self.assertEqual(result["pending_proofs"], 0)

    def test_review_hashes_rules_and_bound_are_trusted_separately(self):
        proof = self.root / "proof"
        proof.write_text(json.dumps(self.cert))
        self.submit({"lower_proofs": [{"lower": 8, "artifact": "proof"}]})
        data = self.review(sha256(proof.read_bytes()).hexdigest())
        for field in ("benchmark_sha256", "submission_sha256", "rules_version"):
            changed = data | {field: "changed"}
            self.registry.write_text(json.dumps(changed))
            with self.subTest(field=field), self.assertRaises(Invalid):
                judge(self.manifest, self.submission, self.registry)
        self.registry.write_text(json.dumps(data))
        self.submission.write_text(self.submission.read_text() + "\n")
        with self.assertRaisesRegex(Invalid, "different"):
            judge(self.manifest, self.submission, self.registry)


if __name__ == "__main__":
    unittest.main()
