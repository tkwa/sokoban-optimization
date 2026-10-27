# Verification protocol

This document describes the staged `sokogap-benchmark-v1` protocol. A release is
identified by the SHA-256 of its frozen manifest. Its lock pins all verifier
modules, board files, baseline certificates and solutions, source audit
references, rules, runtime requirements and resource limits.

## Inputs and scoring

A benchmark contains exactly ten distinct canonical board hashes, with a
positive gap on each board. Boxes and goals have equal counts. Board characters
are the standard XSB wall, floor, player, box and goal symbols. Coordinates in
certificates are zero-based row-major cell IDs in the canonical rectangular
board, whose text is hashed as ASCII. Boxes are sorted by cell ID. The player
is represented by the smallest cell in the region reachable without pushing.

A submission has exactly two top-level fields:

```json
{
  "benchmark_sha256": "SHA-256 of the exact frozen manifest bytes",
  "instances": {
    "xsokoban-50": {
      "solution": "a complete LURD move sequence",
      "lower_certificate": {"...": "a complete supported certificate"}
    }
  }
}
```

Either evidence field and any instance may be omitted. An empty `instances`
object scores zero. A solution is a string; a certificate is an embedded JSON
object. Bare numerical bounds and unknown submission fields are rejected.
The placeholders above illustrate structure and are not a valid submission.

The judge verifies the whole baseline before checking a submission. It combines
the submitted result with that baseline using maximum lower bounds and minimum
upper bounds. A submission should include the accumulated best evidence for the
run being evaluated. The CLI is stateless: separate invocations do not implicitly
merge submissions. `score_percent_exact` is the authoritative rational
percentage; floating-point values are provided for display.

## Lower-bound certificates

`sokogap-potential-v1` contains `format`, `board_sha256`, `lower`, and `states`.
Each state contains sorted `boxes`, a canonical `player` cell, and a nonnegative
integer `h`. Unlisted states use the minimum-cost box-to-goal matching bound,
with wall-aware single-box push distances. Listed solved states must have zero
potential. Every other listed value must be at most one plus the value of every
legal push successor. Following a solution until its first unlisted state proves
the initial bound. The verifier retains a stronger default initial bound when
the explicit table understates it.

`sokogap-abstraction-v1` partitions the original boxes into groups of one to
three boxes and assigns signed integer prices to goals. The verifier reconstructs
each abstract reverse push graph and recomputes the exact priced distances.
`sokogap-abstraction-v2` also permits four-box groups, strengthened by a finite
table of signed potentials with checked terminal and successor inequalities.
Full schemas and the additive proof argument are in
[research/abstraction/README.md](../research/abstraction/README.md).

The returned lower bound uses the certificate's recomputed value and the matching
baseline, rounded upward to the solution parity. Understating the numerical
claim does not make the baseline or scored result ignore that stronger value.
These are the accepted proof formats for this protocol. An argument in another
proof language requires a separately versioned checker extension to earn credit.

## Resource policy

The CLI verifier runs in a separate Python subprocess, with input treated as
data. Fixed caps apply to an entire invocation, including baseline verification:

| Resource | Limit |
| --- | ---: |
| JSON document | 64 MiB |
| Board rectangle | 4,096 cells |
| Trace | 2,000,000 actions |
| General explicit potential table | 100,000 states |
| Matching evaluations | 1,000,000 |
| Checked push transitions | 30,000,000 |
| Process address space | 2 GiB |
| Process CPU time | 600 seconds |
| Elapsed verification time | 900 seconds |
| Abstraction floor | 192 cells |
| Abstraction box count | 32 |
| States per abstract graph | 600,000 |
| Box configurations per abstract graph | 300,000 |
| Absolute goal price | 2,000,000 |
| Claimed lower bound | 2,000,000 |
| Total explicit four-box states | 100,000 |
| Absolute four-box potential | 10,000,000 |

Duplicate JSON keys, nonfinite numbers, oversized integers, malformed objects
and invalid file references are rejected. Input files are size-checked while
being read. Baseline references stay inside the release directory.

Fixed work caps make the main accounting reproducible. CPU, wall and memory
limits also protect the host; near those limits, hardware and runtime can affect
completion. Exhaustion reports `accepted: null` and `outcome: resource_exhausted`.
It earns no score and does not claim the underlying bound false. A checker
failure also earns no score and must be investigated separately.

| Exit code | Meaning |
| --- | --- |
| 0 | Successful verification; score accepted, or complete frozen audit |
| 1 | Invalid input or evidence |
| 2 | Draft audit or missing baseline/release evidence |
| 3 | Resource exhausted; no validity decision or score |
| 4 | Checker failure; no validity decision or score |

`freeze` is a local maintainer operation. It refuses incomplete baseline evidence
and existing output files. It writes a new manifest and lock, then requires the
result to pass the resource-limited audit. Changing any pinned verifier, limit
or evidence file invalidates that snapshot's audit.
