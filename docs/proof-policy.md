# Lower-bound proof policy

For each instance, the score uses the **best valid lower bound the model proves**.
The mathematical criterion is `every legal solution uses at least L pushes`.
The baseline is fixed by the benchmark version; a submission earns credit for
raising that lower bound or producing a shorter replayable solution. Walking
is free, and proved lower bounds round upward to the board's solution parity.

Proof method and proof format do not restrict eligibility. A state potential,
SAT refutation, theorem-prover development, new abstraction, exhaustive search
argument, or mathematical proof can count after independent verification.
The automatic adapters are convenient ways to verify evidence within published
resources. Their size limits do not define which theorems count.

## Submitting evidence

Each instance may supply one `lower_certificate` or a list `lower_certificates`
using the automatic formats in [the protocol](protocol.md). The judge checks
each and takes the maximum valid bound. An invalid individual certificate is
logged as rejected and adds no credit. An unfamiliar proof language or a
certificate exceeding deterministic checking resources is pending review.

Arbitrary proof artifacts can instead be included as files alongside the
submission. A proof bundle can be an archive containing documents, source,
data and reproduction instructions. The judge hashes files without executing
them. Paths must be relative and remain inside the submission directory.

```json
{
  "benchmark_sha256": "exact frozen manifest SHA-256",
  "instances": {
    "xsokoban-50": {
      "lower_proofs": [
        {"lower": 180, "artifact": "proof-bundle.zip", "description": "Proof and reproduction instructions"}
      ]
    }
  }
}
```

The claimed number is a request for verification. It receives no credit on its
own. Include the precise board identity and push rules, the theorem established,
the argument or certificate, dependencies, and enough detail for someone else
to check the proof. Review should check the reduction as well as any external
proof checker; solver logs and elapsed search time alone do not prove a bound.

## Independent review

The benchmark operator arranges independent review for evidence without a
completed automatic check. Reviewers establish the exact valid bound, describe
how they checked it, and provide an identifiable review record with supporting
evidence or reproduction details. Review may establish a stronger or weaker
bound than the participant requested. Unresolved validity remains pending.
Reviewers must apply the same Sokoban rules and board snapshot as the benchmark.

Completed decisions are stored in a **trusted operator registry**. This file
comes from the benchmark maintainer through a trusted channel, separate from
the participant submission. Participant-uploaded review files and reviewer
names are never authorities. The CLI's `--reviews` option is an operator input;
a hosted evaluator must never populate it from a participant-selected path.

```json
{
  "format": "sokogap-proof-reviews-v1",
  "benchmark_sha256": "exact frozen manifest SHA-256",
  "submission_sha256": "exact submission.json SHA-256",
  "rules_version": "orthogonal-sokoban-pushes-v1",
  "decisions": [
    {
      "instance": "xsokoban-50",
      "board_sha256": "canonical board SHA-256",
      "proof_sha256": "proof artifact SHA-256",
      "status": "accepted",
      "verified_lower": 180,
      "reviewer": "reviewer identity",
      "verification": "review record URL or detailed verification method and evidence reference"
    }
  ]
}
```

A rejection uses `status: rejected` and omits `verified_lower`. Every decision
is bound to the rules, benchmark, exact submission bytes, board, and proof.
An artifact digest hashes its exact file bytes. For an inline certificate, hash
the ASCII bytes of `json.dumps(certificate, sort_keys=True, separators=(",", ":"),
ensure_ascii=True)` without a newline. The judge reports that digest even for a
pending certificate. Repeated decisions for the same evidence are rejected.

```sh
python3 -m sokogap score benchmark.json submission.json --reviews trusted-reviews.json
```

The score result includes the trusted registry hash and evidence decisions, so
the result is reproducible with the frozen verifier and the same adjudications.
The automatic path trusts the pinned checker implementation; the independent
review path also trusts the recorded review decisions. Any change to the rules,
checker or resource policy requires a new release lock before freezing.

## Scoring outcomes

Accepted evidence combines by maximum lower bound and minimum replayed upper
bound. Weaker proofs, duplicate proofs and rejected proofs add no credit. An
accepted bound beyond a verified solution is a contradiction that must be
resolved before scoring. The CLI does not silently merge earlier submissions;
include the accumulated best evidence for the evaluated run.

While any proof is pending, the submission has no final score. The output may
show provisional progress from evidence already verified, clearly labeled
`provisional_score_percent` and `provisional_score_percent_exact`. Once all
reviews are resolved, `score_percent_exact` gives the final rational percentage.
The method-independent criterion therefore includes an adjudication process;
the built-in deterministic program is one verification route within it.
