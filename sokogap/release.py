"""Pin the verifier, rules, resource limits and every baseline evidence file."""

from hashlib import sha256
import json
from pathlib import Path

from .budget import PROCESS_LIMITS, WORK_LIMITS
from .core import Invalid, MAX_CELLS, MAX_MOVES
from .certificates import MAX_BOUND, MAX_PROOF_STATES


PACKAGE = Path(__file__).resolve().parent
RULES = {
    "version": "orthogonal-sokoban-pushes-v1",
    "walking_cost": 0,
    "single_box_single_square_push_cost": 1,
    "completion": "all boxes on goals; no further actions",
    "trace_alphabet": "LURDlurd",
    "ignored_trace_characters": " \t\r\n",
    "lower_rounding": "up to checkerboard solution parity",
    "aggregation": "total verified push gap closed / frozen total push gap",
    "lower_bound_policy": "strongest independently verified model-proved bound, regardless of proof method",
    "external_reviews": "trusted operator registry bound to rules, manifest, submission, board and proof hashes",
    "instances": 10,
    "arithmetic": "integer bounds and exact rational score",
}


def limits():
    from . import abstraction, lrat, proofs, sat
    return {"max_board_cells": MAX_CELLS, "max_trace_actions": MAX_MOVES,
            "max_json_bytes": 64 * 1024**2, "max_potential_states": MAX_PROOF_STATES,
            "max_claimed_bound": MAX_BOUND, "work": WORK_LIMITS, "process": PROCESS_LIMITS,
            "abstraction": {"max_floor_cells": abstraction.MAX_ABSTRACT_FLOOR,
                            "max_boxes": abstraction.MAX_ABSTRACT_BOXES,
                            "max_graph_states": abstraction.MAX_ABSTRACT_STATES,
                            "max_box_configurations": abstraction.MAX_BOX_PATTERNS,
                            "max_absolute_goal_price": abstraction.MAX_PRICE,
                            "max_four_box_proof_states": abstraction.MAX_PATTERN_PROOF_STATES,
                            "max_absolute_four_box_potential": abstraction.MAX_PATTERN_POTENTIAL},
            "sat": {"encoding": sat.ENCODING, "max_floor": sat.MAX_FLOOR,
                    "max_pushes": sat.MAX_PUSHES, "max_variables": sat.MAX_VARIABLES,
                    "max_clauses": sat.MAX_CLAUSES, "max_literals": sat.MAX_LITERALS},
            "lrat": {"max_proof_bytes": lrat.MAX_PROOF_BYTES, "max_steps": lrat.MAX_STEPS,
                     "max_line_bytes": lrat.MAX_LINE_BYTES, "max_id": lrat.MAX_ID,
                     "max_variable": lrat.MAX_VARIABLE},
            "reviews": {"max_proofs_per_instance": proofs.MAX_PROOFS,
                        "max_artifact_bytes": proofs.MAX_ARTIFACT_BYTES}}


def digest_file(path: Path) -> str:
    if not path.is_file():
        raise Invalid(f"expected regular file: {path.name}")
    digest = sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024**2), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expected_data_paths(manifest: dict) -> list[str]:
    paths = set()
    for row in manifest["instances"]:
        for key in ("board", "lower_certificate", "upper_solution", "audit_reference"):
            value = row.get(key)
            if value:
                if not isinstance(value, str):
                    raise Invalid(f"{key} must be a relative file path")
                paths.add(value)
    for key in ("record_audit", "witness_audit"):
        if manifest.get(key):
            paths.add(manifest[key])
    return sorted(paths)


def build_lock(root: Path, manifest: dict) -> dict:
    from .judge import local_path
    return {"format": "sokogap-release-lock-v1", "rules": RULES, "limits": limits(),
            "runtime": {"implementation": "CPython", "minimum_version": "3.10", "platform": "Linux"},
            "checker_files": {p.name: digest_file(p) for p in sorted(PACKAGE.glob("*.py"))},
            "data_files": {p: digest_file(local_path(root, p)) for p in expected_data_paths(manifest)}}


def check_lock(root: Path, manifest: dict) -> list[str]:
    from .judge import local_path, read_json
    problems = []
    if not manifest.get("release_lock") or not manifest.get("release_lock_sha256"):
        return ["release lock missing; pin rules, limits, verifier and baseline evidence before freezing"]
    try:
        path = local_path(root, manifest["release_lock"])
        if digest_file(path) != manifest["release_lock_sha256"]:
            return ["release lock hash mismatch"]
        lock = read_json(path)
        expected = build_lock(root, manifest)
        if not isinstance(lock, dict) or set(lock) != set(expected):
            return ["invalid release lock fields"]
        for key in expected:
            if lock[key] != expected[key]:
                problems.append(f"release lock differs from current {key}")
    except (Invalid, OSError, ValueError, TypeError) as error:
        problems.append(f"release lock: {error}")
    return problems


def prepare_freeze(draft_path: Path, output_path: Path):
    """Write a new local snapshot only when its complete baseline passes audit."""
    from .judge import audit, read_json
    if output_path.exists():
        raise Invalid("freeze output already exists; releases are immutable")
    if output_path.parent.resolve() != draft_path.parent.resolve():
        raise Invalid("freeze output must share the draft's directory")
    report, _, _ = audit(draft_path)
    if not report["evidence_ready"]:
        raise Invalid("baseline evidence is incomplete or disagrees with declared bounds")
    manifest = read_json(draft_path)
    lock_name = output_path.stem + ".lock.json"
    lock_path = output_path.with_name(lock_name)
    if lock_path.exists():
        raise Invalid("freeze lock already exists")
    lock = build_lock(draft_path.parent, manifest)
    lock_path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    manifest.update(status="frozen", release_lock=lock_name, release_lock_sha256=digest_file(lock_path))
    output_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    result, _, _ = audit(output_path)
    if not result["scoreable"]:
        raise Invalid("new snapshot did not pass final audit")
    from .runner import run_limited
    limited, code = run_limited("audit", [output_path])
    if code != 0 or not limited.get("scoreable"):
        raise Invalid("new snapshot exceeds the limited runner or fails its audit")
    return limited
