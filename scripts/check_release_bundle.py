"""Exercise freezing and scoring on a temporary ten-board validation fixture.

The fixture uses replayable alternative solutions. It never changes or freezes
the official draft, whose advertised-record witnesses are still missing.
"""

import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import tempfile
import time

from sokogap.release import digest_file, expected_data_paths, prepare_freeze
from sokogap.runner import run_limited


ROOT = Path(__file__).resolve().parents[1]


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def main():
    source = ROOT / "benchmark.draft.json"
    original_hash = digest_file(source)
    manifest = json.loads(source.read_text())
    alternatives = json.loads((ROOT / "research/upper-witness-audit/best-available-witnesses.json").read_text())
    alternatives = {f"xsokoban-{row['number']}": row for row in alternatives}
    report = {
        "purpose": "Local ten-board release-path validation using alternative solutions; not an official benchmark release",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "official_draft_sha256": original_hash,
        "official_draft_gap": sum(r["upper"] - r["lower"] for r in manifest["instances"]),
        "checks": {},
    }
    start = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="sokogap-release-validation-") as directory:
        root = Path(directory)
        fixture = copy.deepcopy(manifest)
        fixture["benchmark_id"] = "validation-fixture-only-2026-10-26"
        for row in fixture["instances"]:
            witness = alternatives[row["id"]]
            assert row["board_sha256"] == witness["board_sha256"]
            assert digest_file(ROOT / witness["solution_path"]) == witness["solution_sha256"]
            row["upper"] = witness["pushes"]
            row["upper_solution"] = witness["solution_path"]
            row["upper_source"] = "Alternative replayable solution used only for release-path validation"
        for relative in expected_data_paths(fixture):
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)
        draft = root / "fixture.draft.json"
        frozen = root / "fixture.json"
        write_json(draft, fixture)
        freeze_start = time.monotonic()
        print("Verifying and freezing temporary ten-board fixture", flush=True)
        audited = prepare_freeze(draft, frozen)
        assert audited["scoreable"] and audited["evidence_ready"] and audited["release_ready"]
        report["checks"]["freeze_and_limited_audit"] = {
            "passed": True, "seconds": round(time.monotonic() - freeze_start, 3),
            "verification_work": audited["verification_work"],
            "lower_total": sum(row["verified_lower"] for row in audited["instances"]),
            "upper_total": sum(row["replayed_upper"] for row in audited["instances"]),
            "gap": audited["declared_total_gap"],
        }
        for label, entries in (
            ("empty_submission", {}),
            ("all_baseline_evidence_resubmitted", {
                row["id"]: {
                    "solution": (root / row["upper_solution"]).read_text(),
                    "lower_certificate": json.loads((root / row["lower_certificate"]).read_text()),
                } for row in fixture["instances"]
            }),
        ):
            submission = root / f"{label}.json"
            write_json(submission, {"benchmark_sha256": digest_file(frozen), "instances": entries})
            check_start = time.monotonic()
            print(f"Checking {label} in limited worker", flush=True)
            result, code = run_limited("score", [frozen, submission])
            assert code == 0 and result["accepted"], result
            assert result["pushes_closed"] == 0 and result["score_percent_exact"] == "0/1", result
            report["checks"][label] = {
                "passed": True, "seconds": round(time.monotonic() - check_start, 3),
                "verification_work": result["verification_work"],
                "score_percent_exact": result["score_percent_exact"],
            }
    assert digest_file(source) == original_hash
    report.update(passed=True, official_draft_unchanged=True,
                  total_seconds=round(time.monotonic() - start, 3))
    output = ROOT / "research/integration-check.json"
    write_json(output, report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
