"""Method-independent proof adjudication, separate from participant claims.

The optional review registry is a trusted *operator* input, like the frozen
baseline. A participant must never choose or upload it as an authority.
"""

from hashlib import sha256
import json

from .budget import Exhausted, spend
from .certificates import verify_lower
from .core import Invalid
from .scoring import integer

FORMATS = {"sokogap-potential-v1", "sokogap-abstraction-v1",
           "sokogap-abstraction-v2", "sokogap-sat-lrat-v1"}
MAX_PROOFS = 64
MAX_ARTIFACT_BYTES = 256 * 1024**2
RULES_VERSION = "orthogonal-sokoban-pushes-v1"


def load_reviews(path, benchmark_sha256, submission_sha256):
    if path is None:
        return {}, None
    from .judge import read_json
    from .release import digest_file
    data = read_json(path)
    required = {"format", "benchmark_sha256", "submission_sha256", "rules_version", "decisions"}
    if not isinstance(data, dict) or set(data) != required or data["format"] != "sokogap-proof-reviews-v1":
        raise Invalid("invalid trusted proof review registry")
    if (data["benchmark_sha256"] != benchmark_sha256 or data["submission_sha256"] != submission_sha256
            or data["rules_version"] != RULES_VERSION):
        raise Invalid("trusted reviews target different rules, benchmark or submission")
    if not isinstance(data["decisions"], list):
        raise Invalid("review decisions must be a list")
    decisions = {}
    for row in data["decisions"]:
        keys = {"instance", "board_sha256", "proof_sha256", "status", "reviewer", "verification"}
        if not isinstance(row, dict) or row.get("status") not in {"accepted", "rejected"}:
            raise Invalid("invalid trusted review decision")
        if row["status"] == "accepted":
            keys.add("verified_lower")
            integer(row.get("verified_lower"), "reviewed lower bound")
        if set(row) != keys or any(not isinstance(row[k], str) or not row[k].strip() for k in keys - {"verified_lower"}):
            raise Invalid("review decisions require identity, bound, method and evidence binding")
        for key in ("board_sha256", "proof_sha256"):
            if len(row[key]) != 64 or any(c not in "0123456789abcdef" for c in row[key]):
                raise Invalid("review digest must be SHA-256")
        key = row["instance"], row["board_sha256"], row["proof_sha256"]
        if key in decisions:
            raise Invalid("duplicate trusted proof review decision")
        decisions[key] = row
    return decisions, digest_file(path)


def artifact_digest(root, value):
    from .judge import local_path
    path = local_path(root, value)
    if not path.is_file():
        raise Invalid("proof artifact must be a regular file")
    digest, size = sha256(), 0
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024**2), b""):
            spend("artifact_bytes", len(chunk))
            size += len(chunk)
            if size > MAX_ARTIFACT_BYTES:
                raise Exhausted("proof artifact exceeds the automatic hashing allowance")
            digest.update(chunk)
    return digest.hexdigest()


def evaluate_lower_proofs(board, name, evidence, root, decisions):
    """Return strongest independently verified lower, evidence log, pending count.

    Invalid individual certificates earn no credit; other valid proofs still
    count. Unfamiliar proof languages are pending, rather than mathematically
    invalid merely because they have no built-in adapter.
    """
    certificates = evidence.get("lower_certificates", [])
    artifacts = evidence.get("lower_proofs", [])
    if not isinstance(certificates, list) or not isinstance(artifacts, list):
        raise Invalid("lower_certificates and lower_proofs must be lists")
    certificates = ([evidence["lower_certificate"]] if "lower_certificate" in evidence else []) + certificates
    if len(certificates) + len(artifacts) > MAX_PROOFS:
        raise Exhausted("proof count exceeds automatic review allowance")
    records = []
    lower, pending = None, 0
    for certificate in certificates:
        raw = json.dumps(certificate, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        digest = sha256(raw).hexdigest()
        record = {"proof_sha256": digest, "kind": "inline_certificate"}
        decision = decisions.get((name, board.digest, digest))
        if decision is not None:
            record.update(decision)
        elif not isinstance(certificate, dict) or not isinstance(certificate.get("format"), str):
            record.update(status="rejected", error="inline certificate needs a text format identifier")
        elif certificate["format"] in FORMATS:
            try:
                record.update(status="accepted", verified_lower=verify_lower(board, certificate),
                              verification="built-in certificate checker")
            except (Invalid, ValueError, KeyError, TypeError, RecursionError) as error:
                record.update(status="rejected", error=str(error))
            except Exhausted as error:
                record.update(status="pending_review", error=str(error))
        else:
            record.update(status="pending_review", reason="proof language needs independent review")
        records.append(record)
    for proof in artifacts:
        if (not isinstance(proof, dict) or set(proof) - {"lower", "artifact", "description"}
                or not {"lower", "artifact"} <= set(proof)):
            raise Invalid("external lower proof requires lower and artifact")
        integer(proof["lower"], "claimed lower bound")
        if "description" in proof and not isinstance(proof["description"], str):
            raise Invalid("proof description must be text")
        digest = artifact_digest(root, proof["artifact"])
        record = {"proof_sha256": digest, "kind": "artifact", "claimed_lower": proof["lower"]}
        decision = decisions.get((name, board.digest, digest))
        record.update(decision or {"status": "pending_review", "reason": "proof awaits independent review"})
        records.append(record)
    for record in records:
        if record["status"] == "accepted":
            value = record["verified_lower"]
            value += (board.push_parity - value) % 2
            lower = max(lower or 0, value)
            record["verified_lower"] = value
        elif record["status"] == "pending_review":
            pending += 1
    return lower, records, pending
