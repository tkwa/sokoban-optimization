"""Optional, untrusted PySAT/Glucose proof producer for small instances.

Install the research extra. For larger proofs use a SAT solver and an LRAT
elaborator of your choice on `sokogap encode-sat` output. This simple DRUP
elaborator deliberately favors readability over speed.
"""

import argparse
from hashlib import sha256
import json
from pathlib import Path

from sokogap.certificates import verify_lower
from sokogap.core import Board, Invalid
from sokogap.lrat import check_lrat
from sokogap.sat import ENCODING, encode_push_bound


def elaborate_drup(cnf, proof):
    clauses = list(cnf)
    lines = []
    # Glucose can detect an initial unit conflict while loading the formula
    # and then return an empty proof log. Elaborate that final conflict too.
    for line in [*proof, "0"]:
        if line.startswith("d") or line.startswith("c"):
            continue  # Keeping deleted clauses is sound for DRUP elaboration.
        values = list(map(int, line.split()))
        if not values or values[-1] != 0:
            raise Invalid("malformed solver DRUP output")
        row = tuple(values[:-1])
        assignment, hints = {}, []
        conflict = False
        for lit in row:
            if abs(lit) in assignment and assignment[abs(lit)] != (lit < 0):
                conflict = True
            assignment[abs(lit)] = lit < 0
        while not conflict:
            changed = False
            for cid, other in enumerate(clauses, 1):
                if any(assignment.get(abs(lit)) == (lit > 0) for lit in other):
                    continue
                free = {lit for lit in other if abs(lit) not in assignment}
                if not free:
                    hints.append(cid)
                    conflict = True
                    break
                if len(free) == 1:
                    lit = next(iter(free))
                    assignment[abs(lit)] = lit > 0
                    hints.append(cid)
                    changed = True
            if not conflict and not changed:
                raise Invalid("solver step is not RUP; use a full LRAT elaborator")
        cid = len(clauses) + 1
        lines.append(f"{cid} " + " ".join(map(str, row)) + (" " if row else "")
                     + "0 " + " ".join(map(str, hints)) + (" " if hints else "") + "0\n")
        clauses.append(row)
        if not row:
            break
    result = "".join(lines)
    check_lrat(cnf, result)
    return result


def produce(board, lower):
    from pysat.solvers import Glucose4
    if type(lower) is not int or lower < 1:
        raise Invalid("lower must be a positive integer")
    cnf = encode_push_bound(board, lower - 1)
    with Glucose4(bootstrap_with=cnf, with_proof=True) as solver:
        if solver.solve():
            raise Invalid("a solution exists below the requested lower bound")
        proof = elaborate_drup(cnf, solver.get_proof())
    certificate = {"format": "sokogap-sat-lrat-v1", "board_sha256": board.digest,
                   "lower": lower, "encoding": ENCODING, "cnf_sha256": cnf.digest, "proof": proof}
    verify_lower(board, certificate)
    return certificate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("board", type=Path)
    parser.add_argument("lower", type=int)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    certificate = produce(Board.parse(args.board.read_text(encoding="ascii")), args.lower)
    with args.output.open("x", encoding="ascii") as target:
        json.dump(certificate, target, separators=(",", ":"))
        target.write("\n")
    print(json.dumps({"verified_lower": verify_lower(Board.parse(args.board.read_text()), certificate),
                      "certificate_sha256": sha256(args.output.read_bytes()).hexdigest()}))


if __name__ == "__main__":
    main()
