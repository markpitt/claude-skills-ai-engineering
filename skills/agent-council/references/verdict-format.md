# Classification, verification, rebuttal and verdict

## Step 1: classify every claim

Extract each discrete claim from every member return and bucket it. Do this before reading for
sense, so that the classification is mechanical.

| Bucket | Test | Handling |
|---|---|---|
| Consensus | Three or more members reached it independently | Highest confidence. Spot-check any arithmetic. |
| Majority | Exactly two members, independently | Verify before acting. |
| Contested | Members explicitly contradict each other | Verify against source. Unresolved is a permitted result. |
| Singleton | One member only | Verify if CRITICAL or HIGH, or if it would change the decision. Never discard for being alone. |

Two rules do most of the work.

- **Silence is not refutation.** Member 2 not mentioning member 4's finding says nothing about it.
  Only an explicit contradiction, made after reading the same source, moves a claim to Contested.
- **Convergence is weaker evidence than it feels.** Members share a base model and so share priors.
  Three members agreeing may be three members reproducing one prior. For a checkable fact, the
  consensus still gets its arithmetic checked against source.

Independence is judged on the source read, not the wording. Two members who both quote the same
clause and reach the same reading are one source's worth of evidence, and say so.

## Step 2: verify

Fan out fresh read-only verifiers, one per claim, on:

- every Contested claim
- every Singleton rated CRITICAL or HIGH, or that would change the decision
- every load-bearing figure, whatever its bucket

Each verifier receives the claim, the source path and locator, and the verification brief. It does
not receive the originating member's reasoning.

Brief verifiers to refute. Where the source does not clearly support the claim, the answer is
REFUTED. Where a claim can fail in more than one way, use verifiers with different lenses rather
than identical refuters: diversity catches what redundancy cannot.

| Verdict | Meaning |
|---|---|
| CONFIRMED | The source supports the claim, and the verifier quotes the passage |
| REFUTED | The source contradicts the claim, or the passage does not say what the claim says |
| UNRESOLVED | The source is silent, or the question is one of judgement rather than fact |

## Step 3: rebuttal (optional)

Used only when the author is available and disputes a finding. One round.

Record each contest in `docs/council/<slug>/REBUTTAL.md`:

```markdown
# Rebuttal: <slug>

| Finding | Contest (author's position) | Citation (corpus path and locator, or amendment ID) | Verified by | Result | Reason |
|---|---|---|---|---|---|
| F-03 | The clause was amended in 2024 | `corpus/014-<basename>`, page 3 | verifier V2 | UPHELD | The amended text is quoted at page 3; finding withdrawn |
| F-07 | The figure is from a later year | `corpus/009-<basename>`, row 12 | verifier V4 | REJECTED | Row 12 gives the figure for the year the claim uses |
```

UPHELD means the contest stands: the finding is withdrawn or downgraded, and the citation is why.
REJECTED means the finding stands, and the source that shows it is named. A contest with no
citation is REJECTED with that as the reason. There is no second rebuttal round. Anything still
disputed is reported as unresolved.

## Step 4: the verdict

Write `docs/council/<slug>/VERDICT.md`. Findings first, reasoning second, no preamble.

````markdown
# Council verdict: <slug>

- Question: <the one-sentence question>
- Object and revision: <name, and commit SHA or version date>
- Mode: council | corpus
- Corpus lock: <manifest SHA-256, and the re-check result before adjudication>, or not applicable
- Lenses: <number>, listed as `L1-<name>` and so on, with stance
- Verifications run: <number>
- Rebuttal: not run | run, see `REBUTTAL.md`
- Amendments since lock: <none | list>

## Verdict

Two or three sentences. The answer to the question, and the single thing that most changes the
decision.

## Act on these

| # | Finding | Bucket | Verified | Severity | Source | What it changes |
|---|---|---|---|---|---|---|
| 1 | <claim> | Singleton | CONFIRMED | HIGH | `corpus/003-<basename>`, p.4 | <decision it changes> |

Ranked by what most changes the decision. Not ranked by severity label, and not by how many
members raised the point.

## Unresolved

| Question | Position A (lens) | Position B (lens) | What would settle it | Who decides |
|---|---|---|---|---|
| <question> | <position> | <position> | <evidence or event> | <role> |

## Refuted, and why it is recorded

| Claim | Raised by | Refuted by | Source that refutes it |
|---|---|---|---|
| <claim> | L3 | V2 | `corpus/011-<basename>`, row 4 |

A refuted claim recorded here is not raised again on the next review of the same object.

## Explicit negatives

What the council checked and found clean. Name the lens and its scope.

| Lens | Scope | Result |
|---|---|---|
| L2 completeness auditor | Corpus 001 to 014 | No material issue |

"No material issue" is a complete answer, and belongs here, not omitted.

## Coverage

| Member | Items opened | Items in scope | Items in corpus | How chosen |
|---|---|---|---|---|
| L1 | 9 | 14 | 14 | Full scope; manifest read first |

Excluded from the corpus, by category, with counts: <list>.
Duplicates and content groups: <count, and the groups>.
Not covered, and why: <bounds, documents nobody read, lenses not convened>.

A silent gap reads as coverage. Name every gap here.

## Cost

Members: <n>. Verifiers: <n>. Rebuttal: <yes or no>. Deliberately not covered: <list>.
````

## Adjudicator discipline

- Do not resolve a contested claim from memory. Send it to verification.
- Do not average two positions into a middle one. Pick one with its evidence, or report unresolved.
- Do not promote a claim because several members raised it, or demote one because a single member
  did. Buckets inform confidence; the source decides the truth.
- If you drafted the object under review, you are the worst judge of whether a member is right
  about it. Verify rather than defend.
- Report a thin result honestly. A council that found little, and says so, is more useful than one
  that padded itself to justify its cost.
- Name the review scope in every finding. A finding without its scope cannot be weighed.
