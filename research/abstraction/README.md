# Independently checked baseline lower bounds

These certificates reproduce or exceed all ten initial lower bounds in the 2016
IJCAI table without trusting the paper, a solver executable, an optimizer, or
precomputed distance tables. The source comparison remains useful as an audit
reference; it is not part of the proof.

| Board | Published lower | Checked lower | Format | Explicit four-box states |
|---|---:|---:|---|---:|
| XSokoban 50 | 102 | 104 | v1 | 0 |
| XSokoban 69 | 223 | 223 | v1 | 0 |
| XSokoban 66 | 193 | 193 | v1 | 0 |
| XSokoban 52 | 379 | 379 | v2 | 16 |
| XSokoban 37 | 246 | 246 | v1 | 0 |
| XSokoban 74 | 190 | 194 | v1 | 0 |
| XSokoban 13 | 224 | 224 | v2 | 3 |
| XSokoban 15 | 108 | 108 | v2 | 4 |
| XSokoban 22 | 310 | 310 | v1 | 0 |
| XSokoban 31 | 236 | 236 | v1 | 0 |
| **Total** | **2,211** | **2,217** | | **23** |

The checked total gives a 762-push gap against the provisional record upper total
of 2,979. Record solution sequences still need separate replay verification.
The two improved lower numbers are improvements over the cited table; this
comparison does not establish new community records.

## Mathematical argument

Partition the original boxes into disjoint groups. An abstract state retains
only the boxes of its group and the player's reachable component. Other boxes
are removed. Each real push contributes one push to exactly one projected group;
for every other group that push projects to free player walking.

Choose any integer goal prices, in sorted goal-cell order. For each group,
compute a lower bound on

```
number of pushes - sum(prices of the group's occupied final goals).
```

Every real solution eventually places the groups on disjoint goal sets covering
all goals. Consequently, the sum of these group lower bounds plus the sum of all
goal prices is a lower bound on the original solution's push count. The checker
rounds that result up to the board's required checkerboard parity.

For groups containing one to three boxes, `sokogap/abstraction.py` reconstructs
the entire reverse push graph. The graph retains player access, walls, and box
collisions. Cells that cannot reach any goal even with a single box are omitted;
such cells cannot occur on a successful abstract path. Multi-source Dijkstra
starts every goal configuration at its negative total goal price. Negative
initial source distances are valid because all graph edges cost one.

For four-box groups, the default potential is the maximum over every disjoint
3+1 and 2+2 partition of their already checked projected values. A finite table
may strengthen that potential. Every listed value must be at most one plus the
value of **every** legal push successor. At a terminal four-box configuration it
must be at most the negative price sum of its occupied goals. Following any
solution until its first unlisted state, or to its terminal state, proves the
initial bound. This argument permits negative potentials and needs no trust in
the search that produced them. The checker also retains a stronger default
initial potential when a supplied table understates it.

## Certificate formats

The v1 format is `sokogap-abstraction-v1`, with exactly these fields:

- `format`
- `board_sha256`
- `lower` (a nonnegative claimed integer)
- `groups` (lists of one to three sorted original box cells, partitioning all boxes)
- `goal_prices` (signed integers, ordered by sorted goal cells)

The v2 format is `sokogap-abstraction-v2`. Groups may contain four boxes. It adds
`pattern_potentials`, containing exactly one object for each four-box group:

```
{"group": [original box cells], "states": [
  {"boxes": [four sorted current box cells], "player": minimum reachable cell, "h": signed integer}
]}
```

The verifier returns the recomputed bound, which may exceed `lower`. All finite
potentials and every transition are checked from the board rules.

## Reproduction

Certificate verification uses only Python's standard library. The optional
search script uses NumPy, SciPy, and NetworkX to choose box partitions and goal
prices; its output is independently checked. Cached `.npz` matrices are optional
optimizer inputs and never read by the verifier.

From the repository root:

```
python -m unittest discover -s tests -p test_abstraction.py -v
OPENBLAS_NUM_THREADS=1 python scripts/certify_baselines.py --triples --restarts 3
OPENBLAS_NUM_THREADS=1 python scripts/certify_baselines.py --four --levels 52 13 15 --patterns 1500 --expansions 100
```

Existing stronger certificate files are preserved. `final-verification.json`
records all ten verified results and resource measurements from one process:
29.13 seconds, 181,344 KiB peak RSS, and 7,693,845 checked push transitions.

The focused tests compare 144 one/two/three-box priced distances with an
independent player-step 0-1 BFS. They also test push accounting, negative prices,
four-box signed potentials, terminal and transition forgeries, malformed data,
understated proof values, and resource limits. A separate reviewer built broader
independent checks in `research/checker-review/`.
