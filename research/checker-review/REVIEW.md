# Independent checker review — 2026-10-26

Scope: the Python rules, matching heuristic, finite potential verifier, reference
A* generator, baseline audit, exact scorer, and command-line input handling.
The review did not establish that any published record is current, or certify
the proposed numerical baseline. Production files were not edited by the reviewer.

## Findings requiring release changes

1. **A frozen baseline can include already closed gap.** `audit()` accepts a
   lower declared bound than its own verified lower evidence, and a greater
   declared upper bound than the bundled replay length. A fixture with ten rows
   declared `[0,4]`, matching lower bound 2, and a 2-push replay is reported
   `scoreable: true`, with a declared gap of 40 and actual evidence gap of 0.
   Freeze the strongest verified available lower bound and the exact replay
   length; require equality before marking a release scoreable. This is a
   benchmark definition problem, not a false mathematical bound.
2. **Malformed JSON can escape the structured rejection path.** A 4,001-byte
   document consisting of 2,000 nested arrays raises `RecursionError` from
   `read_json()`. A manifest row of `null` raises `AttributeError` from `audit()`.
   Neither is caught by the CLI. Validate manifest schema and convert parser
   depth failures to clean rejections. The reproductions are in
   `review_checks.py` and their observations in `results-initial.json`.
3. **State and byte limits do not give practical verifier limits.** A valid
   16,284-byte certificate containing 100 random zero-potential states on
   XSokoban 22 took 2.428 seconds and 2,151 Hungarian evaluations on this host.
   Linear extrapolation to the permitted 100,000 states is approximately
   40 minutes for one certificate; this is an extrapolation, not a measured
   upper bound. Zero potentials can skip transition checks entirely, and
   nonsolved states with potential one also require no successor evaluation.
   Other valid potentials can still cause substantial work. Use deterministic
   work budgets together with isolated-process CPU, elapsed-time, and memory
   caps. Calibrate the final limits against the completed baseline certificates.
4. **Not every entry point checks file size before reading.** The replay,
   verify-lower, and prove commands read complete board files before parsing;
   replay reads the complete trace before its string-length limit. Prefer
   bounded reads for every external file. A `stat()` size check alone also
   leaves a check/read race or special-file exception.
5. **The release identifier does not yet freeze the verifier and resources.**
   The manifest hash binds board hashes and numerical rows, but currently does
   not pin the rule/kernel version, proof implementations, resource policy,
   or hashes of baseline evidence. A release bundle must pin these as well.

Operational limit suggestion for initial calibration: 2 GiB memory, 600 CPU
seconds, and 900 elapsed seconds for a whole submission. These are provisional
engineering values, not established adequate limits. The advertised 100,000-state
ceiling alone does not promise every permitted-size proof will finish within
these limits. Resource exhaustion should be reported distinctly from a failed
mathematical certificate check. Deterministic work accounting would improve
cross-machine reproducibility.

## Mathematical argument checked

The finite potential scheme is sound. Consider any actual solution path from
a listed state. Follow checked inequalities through listed states until either
a solved state, whose potential is required to be zero, or the first unlisted
state. At that first unlisted state, the independent matching lower bound is
at most the remaining solution length. Telescoping only this prefix proves
that the starting potential is admissible. If the starting state is unlisted,
the matching argument applies immediately. Unreachable states, cycles, and
dead states cause no exception to this argument. Global consistency across
unlisted-to-listed edges is not required.

The matching heuristic is admissible: each completed box trajectory ends at
a distinct goal; ignoring other boxes and player accessibility can only shorten
its push distance. The minimum perfect assignment cannot exceed the assignment
induced by any real solution. Reverse BFS correctly retains both a box predecessor
square and the necessary pusher support square. With at most 4,096 board cells,
the artificial infinity value is larger than any all-finite matching cost.

Collapsing player positions to the minimum cell in their connected free-floor
component preserves exactly the possible next pushes. Every real push moves
one box to the opposite checkerboard color, so all complete solutions share
the fixed initial-to-goal parity. Rounding an independently valid integer lower
bound upward to that parity is sound.

The replay code derives push counts from transitions, checks walls and occupied
destinations, and requires complete goal occupancy. Stopping at first completion
preserves the optimal push objective. The scorer uses exact integer/Fraction
arithmetic and combines lower-bound improvement with upper-bound improvement
without double counting. Its standalone API assumes its bounds have already
been certified, which the judge enforces.

No false acceptance of an invalid push bound was found in the reviewed code.
This is an independent code review and executable cross-check, not a machine-
checked formal proof of the Python interpreter or implementation.

## Independent executable checks

`review_checks.py` independently constructs the complete player-step state
graph on small boards, with zero-cost walking and unit-cost pushes. It computes
exact distances by reverse 0–1 BFS, without importing production transition or
reachability methods. Across the original implementation it checked:

- 6 combinations of floor layout and box count, and 69 goal layouts;
- 21,874 raw states, including 3,236 solvable-state heuristic/parity checks;
- 3,269 comparisons of canonical push successors against independently walked
  one-push transitions;
- 4,650 matching-consistency edge inequalities;
- 58 full exact-distance potential certificates.

All these checks passed. The existing 16 tests also passed. The measurements and
initial vulnerability reproductions are saved in `results-initial.json` and
`resource-initial.json`. `resource_profile.py` reproduces the resource profile.

## Practical completeness and next verification work

Finite potential tables can represent exact distances for a finite puzzle in
principle, but the current 100,000-state cap and matching fallback do not imply
that a compact certificate of every attainable lower bound exists. A large part
of this benchmark's challenge may therefore be proof compression. The current
matching bounds are weaker than every proposed baseline row, so the numerical
baseline still requires a stronger checked proof system or larger proofs.

Additional formats based on exact abstract subproblems can be sound and much
more compact, but their abstraction, goal assignments, and combination rules
must be reviewed separately. In particular, summing overlapping patterns without
a cost partition would double count pushes. Such formats do not by themselves
establish completeness for all optimum proofs.

Before release, rerun these independent checks after fixes; add explicit tests
for new schema/rules/resource binding, baseline exactness, malformed inputs,
and the actual ten bundled baseline certificates. Publish the checked evidence
and exact verifier source version alongside the release.

## Additional review: additive priced abstractions

Reviewed the new `sokogap/abstraction.py` implementation independently. Its
certificate partitions the original boxes into groups of one, two, or three,
and supplies signed integer goal prices. For each group, the checker computes
the exact minimum of abstract pushes minus the prices of the group's terminal
goals. Summing these values and all goal prices is admissible: project any real
solution onto the disjoint groups, charge every real push to its unique group,
and cancel each goal price exactly once at final completion. Removing other
boxes relaxes accessibility; their pushes project to free walking within the
retained group's player region.

The reverse-live pruning retains every successful abstract trajectory. The
reverse-push construction correctly requires the current player to reach the
old box square and places the predecessor player at the supporting square.
Arbitrary signed initial terminal labels are compatible with the multi-source
Dijkstra calculation because every graph edge has nonnegative cost. Negative
final totals may be clamped to zero, and parity rounding remains valid.

The independent `abstraction_review.py` script compares this bitset/heap
implementation with the complete player-step graph and a label-correcting queue
algorithm. Across 24 goal layouts it checked 72 graphs with one, two, or three
boxes, 2,127 entire reverse-edge sets, 6,381 priced state distances, and 612
partition certificates. Prices included both -2,000,000 and +2,000,000. All
checks passed; every mixed-group bound was no greater than the exact optimum,
and full three-box abstractions equaled the exact optimum. Successful paths
also survived pruning in every checked state. Results are saved in
`abstraction-results.json`.

No soundness issue was found in the additive-price format. Its graph work needs
to count toward the release's deterministic resource budget, and its actual
baseline certificates must still be measured under the final process limits.

## Follow-up on implementation fixes

After the root agent's changes, the original repro script reported clean
`Invalid` exceptions for both deeply nested JSON and a non-object manifest row.
The loose-baseline fixture is no longer scoreable. All original independent
graph checks still pass (`results-after-fixes.json`). Skipping automatic
zero/one-potential inequalities reduced the 100-row zero-potential example from
2.428 seconds and 2,151 matching computations to 0.022 seconds and one matching
computation (`resource-after-fixes.json`). These are measurements on this host.

The added runner uses a CPython isolated-mode subprocess and Linux memory/CPU
limits, plus a parent wall-clock timeout. Resource exhaustion has a separate
indeterminate outcome. The release lock now hashes checker sources and data
files and records rule and resource policies. Final freeze validation should
use that same limited runner, because a direct in-process audit can succeed
even when repeated baseline verification consumes more than the runner's
per-submission allowance. An empty submission and an actual large proof should
also be tested against the completed release.

## Additional review: signed four-box potential tables (v2)

Reviewed `PatternHeuristic` and `verify_pattern_potentials` in the new
`sokogap-abstraction-v2` format. The fallback for a retained four-box state is
the maximum over all disjoint 3+1 and 2+2 decompositions of exact priced
subpattern distances. Each sum is bounded by the cost of every successful
four-box trajectory, with each retained push charged exactly once and each
terminal goal price subtracted once. Taking the maximum preserves this bound.
Other boxes being removed only makes the player's reachable region larger.
A subpattern with no route to a goal subset proves the larger pattern dead.

The finite table may contain signed potentials. At a listed terminal state,
the verifier requires its potential to be no greater than the negative sum
of occupied goal prices. At every listed state it checks every legal push
inequality. The same first-exit argument used for the original format then
works: telescope through listed states until either reaching a listed terminal
or exiting into the independently admissible fallback. The argument requires
neither nonnegative potentials nor consistency across unlisted-to-listed edges.
Enumerating pushes onto reverse-dead squares is safe because their fallback
represents proven infeasibility; no successful projected path can use one.

The original v2 implementation could unnecessarily understate its initial
bound by listing a weaker potential than its already-computed fallback. This
was a baseline-strength issue, not an invalid lower-bound acceptance. The
author changed the return value to the maximum of the listed/implicit initial
potential and the independent initial fallback, and the review confirmed that
the understatement examples no longer weaken the result.

`pattern_review.py` independently checks exact four-box priced distances on
full player-step graphs, and complete four- and five-box optimal push counts.
It constructs sparse finite potential tables from those exact distances,
including finite potentials for dead states that a small-pattern fallback
cannot detect. On seven boards, including rooms with corner goals and varied
player regions, the script checked:

- 6,963 signed fallback bounds against exact priced costs;
- 21 independently generated sparse four-box potential proofs;
- 21 complete v2 certificates, all bounded by the exact full-puzzle optimum;
- 105 rejected forgeries or malformed certificates, including a one-unit
  excess at the initial state, a one-unit excess over a signed terminal cap,
  and missing, duplicated, or overlapping group evidence.

The largest generated proof contained 845 states. Prices included both
-2,000,000 and +2,000,000. A single full four-box group with the exact table
attained the exact puzzle optimum in every tested case. The complete run took
5.175 seconds on this host; results are in `pattern-results.json`.

No mathematical soundness issue was found in v2. Its state/potential caps must
be included in the final release policy, and the completed ten-board bundle
still requires validation through the limited runner before publication.

## Release-path validation status

All five implementation findings identified in this review have been addressed:
baseline bounds must use the bundled evidence, malformed inputs fail cleanly,
verification has explicit work/process limits, external inputs use bounded
reads, and release locks pin rules, limits, checker sources, and evidence.

The measured [integration report](../integration-check.json) records successful
ten-board freeze and limited-audit checks, an empty submission, and resubmission
of every baseline certificate and solution. The last check processed 15,387,690
push transitions in 58.997 seconds and returned the exact score `0/1`, confirming
that resubmitting baseline evidence earns no credit. The empty submission also
returned `0/1`.

This validation used a temporary fixture with certified lower bounds totaling
2,217 and available alternative solution lengths totaling 3,393, giving a
fixture gap of 1,176. It establishes that the implemented release path and
resource limits handle the complete ten-board evidence workload. It does not
establish acquisition of the official record solution witnesses. The official
draft remained unchanged with its provisional 762-push gap.
