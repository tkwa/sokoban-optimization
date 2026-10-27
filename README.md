# Sokoban Optimization

A benchmark of ten difficult Sokoban instances. Each push of certified
gap closure has equal value across the benchmark. The overall score is 0–100%.

**Provisional gap: 762 pushes.** All ten lower bounds have checked certificates.
The advertised upper records were checked on 2026-10-26; their exact solution
traces are still needed before the benchmark can be frozen and scored.

## Baseline

| XSokoban instance | Certified lower | Recorded upper | Gap | Share of total |
| --- | ---: | ---: | ---: | ---: |
| 50 | 104 | 370 | 266 | 34.91% |
| 69 | 223 | 433 | 210 | 27.56% |
| 66 | 193 | 325 | 132 | 17.32% |
| 52 | 379 | 421 | 42 | 5.51% |
| 37 | 246 | 284 | 38 | 4.99% |
| 74 | 194 | 212 | 18 | 2.36% |
| 13 | 224 | 238 | 14 | 1.84% |
| 15 | 108 | 122 | 14 | 1.84% |
| 22 | 310 | 324 | 14 | 1.84% |
| 31 | 236 | 250 | 14 | 1.84% |
| **Total** | **2,217** | **2,979** | **762** | **100%** |

The record counts match the live Let's Logic **Site Push Record** observations
and the [2026-04-28 solver statistics table](https://sokoban-solver-statistics.sourceforge.io/statistics/XSokoban/XSokoban.html).
Exact URLs and observations are in [the live-record report](research/live-records-2026-10-26.json).

The lower certificates reproduce or exceed every selected initial-state bound
in [Pereira et al., IJCAI 2016, Table 1](https://ijcai.org/proceedings/2016/0100.pdf).
They improve board 50 from 102 to 104 and board 74 from 190 to 194, reducing the
earlier 768-push denominator by six. These are improvements over that table.
The [public-source audit](research/current-bound-audit/audit.json) found no newer
numerical lower record for these boards and documents its coverage.

Selection starts from the 17 XSokoban boards unresolved in the published
[Sokolution 7.32 optimal test](https://sokoban-solver-statistics.sourceforge.io/statistics/Push-OptimalTestSuite/Sokolution%20-%20XSokoban.html),
with 30 minutes per board, and takes the ten largest documented gaps. Later
published results inspected during the audit did not establish an optimum for
any selected board. The three largest gaps account for 79.79% of the total.
The original selection data is preserved in [research/candidates.json](research/candidates.json).

Every board matches the original Cornell XSokoban 3.3c archive after exterior
space normalization. The manifest pins each canonical board's SHA-256.

## Scoring

For each instance, freeze starting bounds `L0 <= OPT <= U0`. After verifying
submitted proofs and replaying submitted solutions, compute:

```
G0 = sum(U0[i] - L0[i])
L[i] = max(L0[i], verified submitted lower bounds for i)
U[i] = min(U0[i], verified submitted solution lengths for i)
closed_pushes = G0 - sum(U[i] - L[i])
score_percent = 100 * closed_pushes / G0
```

An upper-bound decrease and a lower-bound increase earn the same credit per
push. Proving all ten instances optimal earns 100%. Omitted instances retain
their starting bounds; worse or repeated evidence adds no credit. Contradictory
bounds reject the submission. Scores use exact rational arithmetic.

Each push flips one box's checkerboard color. The initial box cells and final
goal cells therefore determine the parity of every solution's push count.
Lower bounds are rounded upward to that parity, and baseline bounds must
already have it. Gaps and improvements are consequently even. With a 762-push
baseline, each two-push improvement earns **0.262467192 percentage points**.

The baseline uses the full strength of its bundled evidence. Its lower bounds
must equal the checker results and its upper bounds must equal the replayed
trace lengths. This prevents giving credit for improvements already available
before evaluation. Future records belong to a new version after the freeze.

## Verification

The player walks orthogonally around fixed walls and may push one adjacent box
one square into empty floor. Walking costs zero; each push costs one. Completion
means all boxes occupy goals. A trace contains `LURDlurd`; case is ignored.
Only ASCII spaces, tabs, CR and LF are ignored. Illegal moves, incomplete traces,
and actions after completion are rejected.

Lower proofs use a finite table of state potentials or additive box-pattern
abstractions. The checker reconstructs the graphs and checks every required
inequality. It uses Python's standard library and executes no submitted code.
See [the protocol](docs/protocol.md) for formats, limits and outcomes, and
[the certificate construction](research/abstraction/README.md) for the
mathematical argument and reproduction commands.

The CLI runs verification in a separate Linux process with deterministic work
caps, 2 GiB address-space allowance, 600 CPU seconds and a 900-second wall limit.
The release lock pins the rules, limits, verifier source and every baseline
evidence file. Missing evidence prevents freezing. Resource exhaustion produces
an unscored result whose validity remains undecided.

Independent review covered legal transitions, exhaustive small-board optima,
parity, signed abstractions and forged proofs. All 23 unit tests pass. The ten
lower certificates take about 29 seconds and 177 MiB peak RAM on the development
host. The implementation has a written soundness argument and independent
exhaustive checks; it has not been verified in a proof assistant.
See [the review](research/checker-review/REVIEW.md).

## Run locally

Use CPython 3.10 or newer on Linux. No third-party runtime packages are required.

```sh
python3 -m unittest discover -s tests -v
python3 -m sokogap audit benchmark.draft.json
python3 -m sokogap verify-lower instances/xsokoban-50.xsb evidence/lower/xsokoban-50-abstraction.json
python3 -m sokogap replay instances/xsokoban-50.xsb evidence/solutions/xsokoban-50-audit-best.lurd
```

The draft audit currently exits with code 2 and reports the ten missing record
witnesses. Alternative traces in `evidence/solutions/` are useful for replay
checks. The best available alternatives total 3,377 pushes, after two local
JSoko optimizations. Their provenance is in [the witness audit](research/upper-witness-audit/audit.json).

The full integration check creates a temporary ten-board fixture with the
documented downloadable alternatives, exercises freezing and scoring, then
removes that fixture:

```sh
python3 -m scripts.check_release_bundle
```

[The completed integration run](research/integration-check.json) used the
3,393-push alternative total before those two optimizations. Freezing, the
limited audit, an empty submission and resubmission of all baseline evidence
passed; both submissions scored exactly zero. The official draft was unchanged.

Once every record witness is available, the approved release can be created:

```sh
python3 -m sokogap freeze benchmark.draft.json benchmark.json
python3 -m sokogap score benchmark.json submission.json
```

Submission examples and return codes are in [docs/protocol.md](docs/protocol.md).
Original software is MIT-licensed; puzzle and source provenance are recorded
in [NOTICE](NOTICE).
