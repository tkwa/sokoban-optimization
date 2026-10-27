"""End-to-end checked SAT certificates against independent exact puzzle costs."""
from pathlib import Path
import json
import random
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from sat_review import cases
from scripts.prove_sat import produce
from sokogap.certificates import verify_lower
from sokogap.core import Invalid


def main():
    viable = [case for case in cases() if case[2] is not None and case[2] > 0]
    chosen = {}
    for case in viable:
        if case[0] not in chosen or case[2] > chosen[case[0]][2]:
            chosen[case[0]] = case
    samples = list(chosen.values())
    samples.extend(random.Random(291857).sample(viable, 6))
    distinct = {board.digest: (name, board, exact) for name, board, exact in samples}
    records = []
    for name, board, exact in distinct.values():
        certificate = produce(board, exact)
        checked = verify_lower(board, certificate)
        assert checked == exact
        try:
            produce(board, exact + 1)
        except Invalid as error:
            assert "solution exists" in str(error)
        else:
            raise AssertionError("producer refuted a satisfiable bound")
        for change in ({"lower": exact + 1}, {"cnf_sha256": "0" * 64},
                       {"proof": certificate["proof"] + "2147483647 0 0\n"}):
            try:
                verify_lower(board, certificate | change)
            except Invalid:
                pass
            else:
                raise AssertionError(("altered certificate accepted", name, change))
        records.append({"layout": name, "exact_pushes": exact, "verified_lower": checked,
                        "proof_bytes": len(certificate["proof"]),
                        "proof_lines": len(certificate["proof"].splitlines())})
    return {"certificates": len(records), "satisfiable_larger_bounds_refused": len(records),
            "altered_certificates_rejected": 3 * len(records), "records": records}


if __name__ == "__main__":
    started = time.monotonic()
    result = main()
    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    print(json.dumps(result, indent=2))
