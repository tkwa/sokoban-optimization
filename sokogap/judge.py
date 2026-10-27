"""Verify baseline evidence and submitted evidence before assigning any score."""

from hashlib import sha256
import json
from pathlib import Path
import re

from .certificates import verify_lower
from .core import Board, Invalid, MatchingBound, replay
from .scoring import Bounds, score

MAX_JSON_BYTES = 64 * 1024 * 1024


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Invalid(f"duplicate JSON key: {key[:120]}")
        result[key] = value
    return result


def read_text(path: Path, maximum: int, encoding: str = "ascii") -> str:
    if not path.is_file():
        raise Invalid("expected a regular input file")
    with path.open("rb") as source:
        raw = source.read(maximum + 1)
    if len(raw) > maximum:
        raise Invalid("input file exceeds size limit")
    return raw.decode(encoding)


def read_json(path: Path):
    def parse_integer(value):
        if len(value) > 20:
            raise Invalid("JSON integer exceeds digit limit")
        return int(value)
    try:
        return json.loads(read_text(path, MAX_JSON_BYTES, "utf-8"), object_pairs_hook=unique_object,
                          parse_int=parse_integer,
                          parse_constant=lambda value: (_ for _ in ()).throw(Invalid(f"invalid JSON number: {value}")))
    except RecursionError as error:
        raise Invalid("JSON nesting exceeds parser limit") from error


def local_path(root: Path, value: str) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise Invalid("baseline file must have a relative path")
    path = (root/value).resolve()
    if not path.is_relative_to(root.resolve()):
        raise Invalid("baseline file escapes the benchmark directory")
    return path


def audit(path: Path) -> tuple[dict, dict[str, Board], dict[str, Bounds]]:
    manifest = read_json(path)
    if not isinstance(manifest, dict) or manifest.get("format") != "sokogap-benchmark-v1":
        raise Invalid("invalid benchmark manifest")
    if manifest.get("metric") != "pushes" or manifest.get("aggregation") != "total_gap_closed":
        raise Invalid("unsupported benchmark metric or aggregation")
    if manifest.get("status") not in ("draft", "frozen"):
        raise Invalid("benchmark status must be draft or frozen")
    if not isinstance(manifest.get("benchmark_id"), str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,120}", manifest["benchmark_id"]):
        raise Invalid("invalid benchmark id")
    rows = manifest.get("instances")
    if not isinstance(rows, list) or len(rows) != 10:
        raise Invalid("benchmark must have exactly 10 instances")
    boards, bounds, reports = {}, {}, []
    board_hashes = set()
    for row in rows:
        if not isinstance(row, dict):
            raise Invalid("each instance must be an object")
        required = {"id", "board", "board_sha256", "lower", "upper"}
        if not required <= set(row):
            raise Invalid("instance is missing required fields")
        name = row.get("id")
        if not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,120}", name) or name in boards:
            raise Invalid("invalid or duplicate instance id")
        board_path = local_path(path.parent, row["board"])
        board = Board.parse(read_text(board_path, 2 * 4096))
        if board.digest != row["board_sha256"]:
            raise Invalid(f"{name}: board hash mismatch")
        if board.digest in board_hashes:
            raise Invalid("benchmark contains duplicate boards")
        board_hashes.add(board.digest)
        baseline = Bounds(row["lower"], row["upper"])
        if baseline.gap <= 0:
            raise Invalid("baseline gap must be positive")
        boards[name], bounds[name] = board, baseline
        problems = []
        if baseline.lower % 2 != board.push_parity:
            problems.append("round baseline lower bound up to the board's solution parity before freezing")
        if baseline.upper % 2 != board.push_parity:
            problems.append("baseline upper bound must have the board's solution parity")
        lower = MatchingBound(board).cost(board.boxes)
        if row.get("lower_certificate"):
            try:
                lower = max(lower, verify_lower(board, read_json(local_path(path.parent, row["lower_certificate"]))))
            except (Invalid, OSError, ValueError) as error:
                problems.append(f"lower certificate: {error}")
        if lower < baseline.lower:
            problems.append(f"lower-bound evidence reaches {lower}; required {baseline.lower}")
        elif lower > baseline.lower:
            problems.append(f"baseline lower must use the bundled evidence's stronger bound {lower}")
        upper = None
        if row.get("upper_solution"):
            try:
                solution_path = local_path(path.parent, row["upper_solution"])
                upper = replay(board, read_text(solution_path, 4_000_000)).pushes
                if upper > baseline.upper:
                    problems.append(f"upper-bound witness uses {upper}; required at most {baseline.upper}")
                elif upper < baseline.upper:
                    problems.append(f"baseline upper must use the bundled solution's shorter length {upper}")
            except (Invalid, OSError, ValueError) as error:
                problems.append(f"upper solution: {error}")
        else:
            problems.append("upper-bound witness missing")
        if upper is not None and lower > upper:
            problems.append("verified bounds contradict each other")
        reports.append({"id": name, "declared_lower": baseline.lower, "declared_upper": baseline.upper,
                        "push_parity": board.push_parity,
                        "verified_lower": lower, "replayed_upper": upper, "problems": problems})
    evidence_ready = all(not row["problems"] for row in reports)
    from .release import check_lock
    release_problems = check_lock(path.parent, manifest)
    report = {"benchmark_id": manifest.get("benchmark_id"), "status": manifest.get("status"),
              "manifest_sha256": sha256(path.read_bytes()).hexdigest(),
              "evidence_ready": evidence_ready, "release_ready": not release_problems,
              "release_problems": release_problems,
              "scoreable": evidence_ready and not release_problems and manifest.get("status") == "frozen",
              "declared_total_gap": sum(b.gap for b in bounds.values()), "instances": reports}
    return report, boards, bounds


def judge(manifest_path: Path, submission_path: Path, reviews_path: Path | None = None) -> dict:
    report, boards, baseline = audit(manifest_path)
    if not report["scoreable"]:
        raise Invalid("benchmark is not frozen with verified baseline evidence; run audit for details")
    submission = read_json(submission_path)
    if not isinstance(submission, dict) or set(submission) != {"benchmark_sha256", "instances"}:
        raise Invalid("invalid submission fields")
    if submission["benchmark_sha256"] != report["manifest_sha256"]:
        raise Invalid("submission targets a different benchmark snapshot")
    entries = submission["instances"]
    if not isinstance(entries, dict) or set(entries) - set(baseline):
        raise Invalid("invalid submission instances")
    from .proofs import evaluate_lower_proofs, load_reviews
    from .release import digest_file
    submission_digest = digest_file(submission_path)
    decisions, review_digest = load_reviews(reviews_path, report["manifest_sha256"], submission_digest)
    results, proof_reports, pending = {}, {}, 0
    for name, evidence in entries.items():
        if not isinstance(evidence, dict) or set(evidence) - {"solution", "lower_certificate", "lower_certificates", "lower_proofs"}:
            raise Invalid(f"{name}: expected solution or lower-bound proof evidence, no raw bound claims")
        lower = upper = None
        if "solution" in evidence:
            if not isinstance(evidence["solution"], str):
                raise Invalid("solution must be a LURD string")
            upper = replay(boards[name], evidence["solution"]).pushes
        lower, proof_reports[name], waiting = evaluate_lower_proofs(
            boards[name], name, evidence, submission_path.parent, decisions)
        pending += waiting
        results[name] = baseline[name].improve(lower, upper)
    result = score(baseline, results)
    result["benchmark_sha256"] = report["manifest_sha256"]
    result["benchmark_id"] = report["benchmark_id"]
    result.update(submission_sha256=submission_digest, reviews_sha256=review_digest,
                  lower_proofs=proof_reports, pending_proofs=pending,
                  accepted=None if pending else True,
                  outcome="pending_review" if pending else "accepted")
    if pending:
        # Verified progress may be shown, but an unreviewed submission has no
        # final score. It cannot be misread as having scored the raw claim.
        result["provisional_score_percent"] = result.pop("score_percent")
        result["provisional_score_percent_exact"] = result.pop("score_percent_exact")
    return result
