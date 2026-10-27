"""LRAT reference fixtures and independent small-formula soundness probes.

The paper fixture is from Cruz-Filipe et al., Efficient Certified RAT
Verification, Figure 2: https://www.cs.cmu.edu/~mheule/publications/lrat.pdf
"""
from itertools import product
from pathlib import Path
import json
import random
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from sokogap.core import Invalid
from sokogap.sat import CNF
from sokogap.lrat import check_lrat


def make_cnf(rows):
    result = CNF()
    for _ in range(max((abs(lit) for row in rows for lit in row), default=0)):
        result.var()
    for row in rows:
        result.add(*row)
    return result


def satisfiable(rows):
    n = max((abs(lit) for row in rows for lit in row), default=0)
    return any(all(any(values[abs(lit)-1] == (lit > 0) for lit in row) for row in rows)
               for values in product((False, True), repeat=n))


def accepted_prefix(cnf, proof):
    try:
        check_lrat(cnf, proof)
        return True
    except Invalid as error:
        # This diagnostic is reached only after all supplied additions passed.
        return str(error) == "LRAT proof does not derive the empty clause"


def run():
    stats = {"reference_proofs": 0, "rejected_invalid_proofs": 0,
             "random_sat_formulas": 0, "accepted_prefixes_checked": 0,
             "random_deletion_prefixes": 0}
    paper = [[1, 2, -3], [-1, -2, 3], [2, 3, -4], [-2, -3, 4],
             [-1, -3, -4], [1, 3, 4], [-1, 2, 4], [1, -2, -4]]
    paper_proof = ("9 1 0 -2 6 8 -5 1 8 -7 6 1 0\n"
                   "9 d 8 6 1 0\n"
                   "10 2 0 9 7 5 3 0\n"
                   "10 d 7 3 0\n"
                   "11 0 9 10 2 4 5 0\n")
    positives = [
        ([[1], [-1]], "3 0 1 2 0\n"),
        (paper, paper_proof),
        (paper + [[5]], "10 1 0 9 -2 6 8 -5 1 8 -7 6 1 0\n"
                         "10 d 8 6 1 0\n11 2 0 10 7 5 3 0\n"
                         "11 d 7 3 0\n12 0 10 11 2 4 5 0\n"),
        ([[-1, -2], [3], [-3]], "4 1 2 0 -1 0\n5 0 2 3 0\n"),
        ([[1], [-1]], "3 2 0 0\n4 0 1 2 0\n"),
        ([[1], [-1]], "3 1 0 1 0\n3 d 1 0\n4 0 3 2 0\n"),
        ([[1], [-1]], "3 1 1 0 1 0\n4 0 3 2 0\n"),
        ([[1], [-1]], "3 2 -2 0 0\n4 0 1 2 0\n"),
        ([[1], [-1], [1, 2]], "4 0 1 3 2 0\n"),
        ([[]], "2 0 1 0\n"),
    ]
    for rows, proof in positives:
        assert not satisfiable(rows)
        check_lrat(make_cnf(rows), proof)
        stats["reference_proofs"] += 1
    negatives = [
        ([[1]], "2 0 1 0\n"),
        ([[1]], "2 -1 0 0\n3 0 1 2 0\n"),
        ([[1]], "2 d 1 0\n3 -1 0 0\n4 0 1 3 0\n"),
        ([[1]], "2 2 0 0\n2 -1 0 0\n3 0 1 2 0\n"),
        ([[1, 2]], "2 0 1 0\n"),
        (paper, paper_proof.replace(" -7 6 1", "")),
        (paper, paper_proof.replace("-2 6 8", "-1 6 8")),
        (paper, paper_proof.replace("-2 6 8", "-2 6")),
        ([[1], [-1]], "3 0 1 99 0\n"),
        ([[1], [-1]], "3 0 1 2 0\n4 0 1 2 0\n"),
        ([[1], [-1]], "0 0 1 2 0\n"),
        ([[1], [-1]], "3 0 1 2 0\n\u2603"),
        ([[1], [-1]], "2147483648 0 1 2 0\n"),
    ]
    for rows, proof in negatives:
        try:
            check_lrat(make_cnf(rows), proof)
        except Invalid:
            stats["rejected_invalid_proofs"] += 1
        else:
            raise AssertionError(("invalid proof accepted", rows, proof))
    rng = random.Random(816379)
    for sample in range(5000):
        n = rng.randrange(1, 5)
        chosen_model = [rng.choice((False, True)) for _ in range(n)]
        lits = [s * i for i in range(1, n + 1) for s in (-1, 1)]
        rows = []
        for _ in range(rng.randrange(1, 9)):
            row = rng.sample(lits, rng.randrange(1, min(4, len(lits)) + 1))
            if not any(chosen_model[abs(lit)-1] == (lit > 0) for lit in row):
                i = rng.randrange(n)
                row.append((i + 1) * (1 if chosen_model[i] else -1))
            rows.append(row)
        active = set(range(1, len(rows) + 1))
        prefix = ""
        if rng.randrange(4) == 0:
            removed = rng.sample(sorted(active), rng.randrange(len(active) + 1))
            if removed:
                prefix = f"{len(rows)} d " + " ".join(map(str, removed)) + " 0\n"
                active -= set(removed)
                stats["random_deletion_prefixes"] += 1
        new = rng.sample(lits, rng.randrange(0, min(4, len(lits)) + 1))
        hints = rng.sample(sorted(active), rng.randrange(min(len(active), 4) + 1))
        if new:
            candidates = [cid for cid in active if -new[0] in rows[cid - 1]]
            rng.shuffle(candidates)
            for cid in candidates:
                if rng.randrange(8):
                    hints.append(-cid)
                    hints.extend(rng.sample(sorted(active), rng.randrange(min(len(active), 4) + 1)))
        proof = prefix + " ".join(map(str, [len(rows) + 1, *new, 0, *hints, 0])) + "\n"
        cnf = make_cnf(rows)
        assert satisfiable(rows)
        stats["random_sat_formulas"] += 1
        if accepted_prefix(cnf, proof):
            assert satisfiable([rows[i - 1] for i in sorted(active)] + [new]), (rows, proof)
            stats["accepted_prefixes_checked"] += 1
    return stats


if __name__ == "__main__":
    started = time.monotonic()
    result = run()
    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    print(json.dumps(result, indent=2))
