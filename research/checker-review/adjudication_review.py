"""Check operator review bindings and strongest-evidence aggregation."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import json
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from sokogap.core import Board, Invalid
from sokogap.proofs import RULES_VERSION, evaluate_lower_proofs, load_reviews
from sokogap.search import prove
from sokogap.certificates import verify_lower
from sokogap.sat import ENCODING


def main():
    stats = {"binding_mismatches_rejected": 0, "unmatched_decisions_pending": 0,
             "malformed_registry_fields_rejected": 0, "aggregation_checks": 0}
    board = Board.parse("#######\n#.@ # #\n#  $$ #\n#   # #\n#    .#\n#######\n")
    certificate, _ = prove(board, expansions=10000, seconds=5)
    assert verify_lower(board, certificate) == 8
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        artifact = root / "proof.external"
        artifact.write_text(json.dumps(certificate))
        registry_path = root / "operator-review.json"
        manifest_hash, submission_hash = "1" * 64, "2" * 64
        evidence = {"lower_proofs": [{"lower": 1000, "artifact": artifact.name}]}
        registry = {"format": "sokogap-proof-reviews-v1", "benchmark_sha256": manifest_hash,
                    "submission_sha256": submission_hash, "rules_version": RULES_VERSION,
                    "decisions": [{"instance": "case", "board_sha256": board.digest,
                                   "proof_sha256": sha256(artifact.read_bytes()).hexdigest(),
                                   "status": "accepted", "verified_lower": 8,
                                   "reviewer": "independent audit fixture",
                                   "verification": "Checked the potential certificate independently"}]}
        def evaluate(data, supplied=evidence):
            registry_path.write_text(json.dumps(data))
            decisions, _ = load_reviews(registry_path, manifest_hash, submission_hash)
            return evaluate_lower_proofs(board, "case", supplied, root, decisions)
        lower, _, pending = evaluate(registry)
        assert (lower, pending) == (8, 0)  # Reviewer bound, never participant's1000.
        stats["aggregation_checks"] += 1
        for field in ("benchmark_sha256", "submission_sha256", "rules_version"):
            bad = deepcopy(registry)
            bad[field] = "changed"
            try:
                evaluate(bad)
            except Invalid:
                stats["binding_mismatches_rejected"] += 1
            else:
                raise AssertionError(field)
        for field, wrong in (("instance", "other"), ("board_sha256", "0" * 64),
                             ("proof_sha256", "0" * 64)):
            changed = deepcopy(registry)
            changed["decisions"][0][field] = wrong
            lower, _, pending = evaluate(changed)
            assert (lower, pending) == (None, 1)
            stats["unmatched_decisions_pending"] += 1
        for field, value in (("verified_lower", -1), ("verified_lower", True),
                             ("verified_lower", 8.0), ("reviewer", ""), ("verification", "")):
            bad = deepcopy(registry)
            bad["decisions"][0][field] = value
            try:
                evaluate(bad)
            except Invalid:
                stats["malformed_registry_fields_rejected"] += 1
            else:
                raise AssertionError((field, value))
        artifact.write_text(artifact.read_text() + "\n")
        lower, _, pending = evaluate(registry)
        assert (lower, pending) == (None, 1)
        stats["unmatched_decisions_pending"] += 1
        # A review file carried as participant evidence has no authority itself.
        participant_evidence = {"lower_proofs": [{"lower": 8, "artifact": registry_path.name}]}
        lower, _, pending = evaluate_lower_proofs(board, "case", participant_evidence, root, {})
        assert (lower, pending) == (None, 1)
        stats["aggregation_checks"] += 1
        mixed = {"lower_certificates": [certificate, {"format": []},
                                        {"format": "new-language", "claim": 1000}, certificate]}
        lower, rows, pending = evaluate_lower_proofs(board, "case", mixed, root, {})
        assert (lower, pending) == (8, 1)
        assert [row["status"] for row in rows] == ["accepted", "rejected", "pending_review", "accepted"]
        stats["aggregation_checks"] += 1
        too_large = {"format": "sokogap-sat-lrat-v1", "board_sha256": board.digest,
                     "encoding": ENCODING, "lower": 2050, "cnf_sha256": "0" * 64, "proof": ""}
        lower, rows, pending = evaluate_lower_proofs(
            board, "case", {"lower_certificates": [too_large, certificate]}, root, {})
        assert (lower, pending) == (8, 1)
        assert rows[0]["status"] == "pending_review"
        stats["aggregation_checks"] += 1
    return stats


if __name__ == "__main__":
    started = time.monotonic()
    result = main()
    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    print(json.dumps(result, indent=2))
