# Exact bounded-push SAT proofs

`sokogap-sat-lrat-v1` is an automatic route for proving any push lower bound
within the published resource allowance. It makes no assumption about pattern
databases or the algorithm that discovered the bound. The trusted part is the
deterministic encoder and LRAT checker. Solvers and proof elaborators are
untrusted producers.

To prove `OPT >= L`, the encoder constructs a CNF satisfiable exactly when a
legal solution with at most `L - 1` pushes exists. A checked UNSAT refutation of
that CNF establishes the lower bound. The returned bound rounds upward to the
board's solution parity. A proof of a larger `L` must target its own formula.

## Encoding and argument

The encoding identifier is `sokogap-push-cnf-v1`. Cells, directions, variables
and clauses have deterministic order in [sat.py](../sokogap/sat.py). DIMACS is
ASCII with LF line endings, one header and one clause per line. Original LRAT
clause IDs are one-based clause numbers after the header. The certificate hashes
these exact bytes; the checker regenerates them from the board and bound.

There is a box-occupancy bit per floor cell at each time, and exactly one player
position on an unoccupied cell. Initial occupancies and player are fixed.
Final box bits equal the goal set. Each time step selects exactly one directed
push or a no-op. A selected push requires its source occupied, destination
empty, and support reachable by walking; it empties the source, fills the
destination and leaves the player at the source. Explanatory frame clauses
require every other occupancy bit to persist. A no-op preserves boxes and
player. It pads solutions using fewer than the allowed pushes.

Free walking uses a witness rooted at the current player. Every marked reachable
cell is unoccupied. Every marked non-root cell chooses an adjacent marked parent
whose binary rank is exactly one less. The player has rank zero and increment
overflow is forbidden. Following parents must therefore terminate at the player,
which proves that every marked support is walkable. Conversely, a BFS tree of
any reachable region supplies parents and ranks below the floor count; thus the
witness permits every real walk. Binary width is `max(1, ceil(log2(floor_count)))`.
The XOR/carry clauses share carry bits for each potential parent.

These observations give both directions: a satisfying assignment describes
legal pushes with walkable supports, and every solution up to the budget can
be extended with no-ops and BFS witnesses to satisfy the formula. Budget zero
compares the fixed initial box set directly with the goals. If a padded trace
visits a solved state earlier, its prefix is already a solution within budget.

## Producing and checking a proof

```sh
python3 -m sokogap encode-sat board.xsb 180 bound.cnf
```

This writes the formula for at most 179 pushes, refuses to overwrite an existing
file, and prints the board hash, encoding, formula hash and dimensions. Run a
SAT solver and LRAT proof producer of your choice on that formula. Package the
ASCII LRAT text as an embedded JSON string:

```json
{
  "format": "sokogap-sat-lrat-v1",
  "board_sha256": "canonical board SHA-256",
  "encoding": "sokogap-push-cnf-v1",
  "lower": 180,
  "cnf_sha256": "exact generated DIMACS SHA-256",
  "proof": "ASCII LRAT statements, including the final empty clause"
}
```

```sh
python3 -m sokogap verify-lower board.xsb certificate.json
```

The checker accepts ASCII LRAT additions with ordered RUP hints, RAT blocks
and clause deletion. It checks all active clauses containing the opposite
pivot for RAT; new variables are allowed within the pinned ID limit. Positive
shared propagation hints precede negative clause-ID RAT blocks. Addition IDs
are fresh and increasing. Deletion-line IDs may equal the preceding addition
ID. Blank lines and `c` comments are allowed. The empty clause must be derived,
and no further statements may follow it. Compressed/binary LRAT must first be
converted to this ASCII form. See the [authors' LRAT specification](https://www.cs.cmu.edu/~mheule/publications/lrat.pdf).

There is a readable optional producer for small puzzles:

```sh
python3 -m pip install -e '.[research]'
python3 -m scripts.prove_sat examples/two-box-detour.xsb 8 example-proof.json
python3 -m sokogap verify-lower examples/two-box-detour.xsb example-proof.json
```

It uses PySAT/Glucose4 and a simple DRUP-to-LRAT elaborator, then checks its own
output with the production verifier. For large instances use an efficient
solver/elaborator. Solver installation is unnecessary to verify a certificate.
The repository includes [a complete checked example](../examples/two-box-detour.sat-lrat.json).
The example's optimal push count is 8 and its matching bound is 6.

The exact encoding matched 1,703 independent exhaustive-search comparisons on
595 small boards, including disconnected player regions, no-op padding, rank
width boundaries and an 8-push detour. These tests and the written argument
support the implementation; they are not a proof-assistant verification of the
Python encoder. Results and reproduction code are in
[the independent review directory](../research/checker-review/).

SAT formula, proof, work and process limits are listed in [the protocol](protocol.md)
and pinned in the release lock. Exceeding the automatic allowance leaves a
validity question for review; it does not make a mathematically valid proof
ineligible under [the general proof policy](proof-policy.md).
