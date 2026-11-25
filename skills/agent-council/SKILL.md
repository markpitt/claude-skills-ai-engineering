---
name: agent-council
description: Convenes a council of independent expert agents, each blind to the others and fixed to one lens, to review a plan, decision, document set or strategy. Findings are adjudicated against the primary sources, not against each other. A corpus mode freezes and hashes the inputs before review. An optional author rebuttal round tests the contested findings. Use when asked to "convene a council", "agent council", "blind review", "get a panel on this", "review this from several angles", or when a high-stakes decision or document set needs several independent views and a single reviewer would anchor on one reading. Do NOT use for a single hostile reviewer (use red-team), for a quick code review, for search or lookup (use Explore), or for anything one agent can finish in a few tool calls.
license: Apache-2.0
metadata:
  version: "1.0.0"
  tags: "multi-agent, council, blind-review, adjudication, decision-review, corpus-review"
---

# Agent council

A council is several independent experts examining the same object through fixed, deliberately
different lenses. Their findings are then checked against the primary sources. It is not a debate,
and the design is what keeps it from becoming one.

## The evidence this design rests on

Multi-agent debate can destroy facts. The figures below are as reported by the papers cited. They
were carried over from an earlier version of this skill and have not been re-verified for this
edition; re-check before quoting them outside the skill.

| Effect | Reported measurement |
|---|---|
| Critical facts erased by round 3 of debate | 21.7 to 72.4% at system level; 60.5 to 84.8% at agent level ([arXiv 2606.03032](https://arxiv.org/html/2606.03032)) |
| Loss without interaction (control) | 19.2% |
| Final consensus matching the model's own prior, not the evidence | 65 to 76% |
| One agent's wrong claim surviving into the final output | 58.9% |

Specific, concrete facts are dropped first; a singleton finding, held by one member alone, is what a
debate round destroys. Heterogeneity helps: cross-model councils retained more critical facts than
same-model councils, and persona assignment preserved stance diversity ([arXiv 2511.07784](https://arxiv.org/abs/2511.07784)).

Council size is 3 to 7 members; gains plateau beyond 7. A council costs several times a single
review in tokens and time. Convene only where the cost of being wrong is larger than that.

## The rules

1. **Members are blind to each other.** Dispatch all members in one message, in parallel. No member
   sees another member's output, ever. This is what makes a council not a debate.
2. **Every member gets a different lens, and at least two get opposed stances.** Five careful
   generalists are one reviewer with a bigger bill. Assign one member to argue for the object and one
   against it, on the record. Stance diversity is load-bearing.
3. **Silence is not refutation.** Four members not mentioning a finding does not refute the fifth who
   raised it. Only an explicit, source-checked contradiction counts against a finding. Never take a
   vote on a question of fact.
4. **Singleton findings are preserved, not filtered.** They are the council's main product and the
   first casualty of any aggregation step. Carry every one into the verdict with its status shown.
5. **Verification runs against the source, never against another agent.** A verifier receives the
   claim and the source location, never the originating member's reasoning. Inheriting that reasoning
   is how one agent's error becomes the council's.
6. **One generation round, one verification round, one optional rebuttal round. Then stop.** No
   iterating to consensus. Unresolved disagreement is a result, reported with both positions and what
   would settle it.
7. **The adjudicator synthesises; it does not average.** Its job is to classify each claim, verify
   what matters, and rank. It does not look for a middle position.
8. **The corpus is frozen before anyone reads it.** In corpus mode, inputs are copied, hashed and
   de-duplicated, and earlier reports, verdicts and drafts are excluded, until the independent view
   is locked. Nothing is added to the corpus silently.

## Situation to reference

| Situation | Load |
|---|---|
| Choosing lenses, writing a new lens, or picking a composition | `references/lens-library.md` |
| Freezing a corpus: copying, hashing, de-duplicating, excluding, locking | `references/corpus-freeze.md` |
| Writing the member prompt, with the standing clauses subagents do not inherit | `references/dispatch-template.md` |
| Writing the verdict, the classification buckets, or the rebuttal record | `references/verdict-format.md` |

## Procedure

Paths are relative to the repository root. `<slug>` is the review's topic in lower-case hyphens.
Every artefact lives under `docs/council/<slug>/`.

### 1. Frame

1. Write the question the council answers in one sentence. State what a useful answer changes.
   If no decision turns on the answer, do not convene.
2. Name the object under review and its revision: a commit SHA for files, a version or date for
   documents.
3. Choose the mode:
   - **Council mode**: one object, one plan or decision, and no source documents that members must
     weigh against each other.
   - **Corpus mode**: a set of input documents, exhibits or records that members must read and
     reconcile. Use this whenever the object is evidence-heavy. It adds the freeze and the rebuttal.

### 2. Freeze the corpus (corpus mode only)

Follow `references/corpus-freeze.md` exactly. The outputs are `docs/council/<slug>/corpus/`,
`docs/council/<slug>/MANIFEST.sha256` and `docs/council/<slug>/CORPUS.md`. Do not dispatch any
member until the lock check in that reference has passed.

In council mode, record the object's revision in `CORPUS.md` and skip the copy.

### 3. Compose the lenses

1. Pick 3 to 7 lenses from `references/lens-library.md`, or write new ones. Each needs a lens, an
   assigned stance, a scope boundary, and a named deliverable.
2. Two lenses that would find the same defect are one lens. Cut one.
3. Include at least one opposed pair on the same question.
4. Give each lens an identifier, for example `L1-adversary`. The identifier names its file in step 5.

### 4. Dispatch

1. Send every member in one message, in parallel, using `references/dispatch-template.md`.
2. Each member receives only: the question, its lens and stance, its scope (corpus paths, or the
   object), the working rules and the output contract. It does not receive the other lenses, any
   other member's output, the adjudicator's views, the earlier reports, or the prior verdicts.
3. Restate every constraint in every prompt. Subagents inherit none of the dispatching session's
   standing rules.
4. Tell every member that "no material issue on this lens" is a complete and valued answer.

### 5. Collect and classify

1. Store each member's return verbatim at `docs/council/<slug>/members/<lens-id>.md`. Do not edit it.
   Record the coverage each member states.
2. Extract every discrete claim from every return before reading for sense, so that the bucket is
   mechanical rather than a judgement about which findings you liked.
3. Bucket each claim:

| Bucket | Test | Handling |
|---|---|---|
| Consensus | Three or more members reached it independently | Highest confidence. Spot-check any arithmetic. |
| Majority | Exactly two members, independently | Verify before acting. |
| Contested | Members explicitly contradict each other | Verify against source. Unresolved is a permitted outcome. |
| Singleton | One member only | Verify, if it is CRITICAL or HIGH or would change the decision. Never discard for being alone. |

4. Record explicit negatives: each lens's "no material issue", with its scope, in the verdict.

### 6. Verify

1. Fan out fresh read-only verifiers, one per claim, on: every contested claim; every singleton rated
   CRITICAL or HIGH, or that would change the decision; and every load-bearing figure, whatever its
   bucket.
2. Give each verifier the claim, the source path and locator, and the verification brief. Never give
   it the originating member's reasoning.
3. Brief verifiers to refute, and to return REFUTED where the source does not clearly support the
   claim. Where a claim can fail in more than one way, give verifiers different lenses rather than
   identical refuters.
4. Verdicts are CONFIRMED (the source supports it), REFUTED (the source contradicts it) or UNRESOLVED
   (the source is silent, or the question is one of judgement rather than fact).
5. For any claim that turns on external law, a standard or a published figure, the verifier fetches
   the official text and records its version and retrieval date. Recalled citations are UNCONFIRMED
   until fetched.

### 7. Adjudicate

1. Write `docs/council/<slug>/VERDICT.md` using `references/verdict-format.md`. Findings first.
2. Rank by what most changes the decision, not by severity label and not by how many members raised
   the point.
3. Put every contested point that survived verification into the Unresolved table, with both
   positions and what would settle it.
4. Put every REFUTED claim in the Refuted table, with the source that refuted it. A refuted finding
   recorded once is not raised again next time.
5. If you drafted the object under review, you are the worst judge of whether a member is right
   about it. Send the claim to verification and do not settle it from memory.
6. State the coverage: how many corpus items each member opened, out of how many, and what was
   excluded and why.

### 8. Rebuttal (optional, one round)

Use this only when the author of the object is available and disputes a finding.

1. Send the author the findings they contest, not the whole verdict, with the corpus path and the
   relevant locators. Do not re-dispatch the council.
2. The author's contest must cite a corpus location (path and locator) for each point. Evidence
   that is not in the corpus is an amendment, handled under `references/corpus-freeze.md`.
3. Verify each contest against the source, as in step 6.
4. Record each contest in `docs/council/<slug>/REBUTTAL.md` as UPHELD (the finding is withdrawn or
   downgraded, with the citation) or REJECTED (the finding stands, with the source that shows it).
5. Update `VERDICT.md`. Anything still disputed after this round is reported as unresolved. There is
   no sixth round.

### 9. Record

1. Commit the council's folder as one commit, with explicit paths:
   ```bash
   git add docs/council/<slug>/VERDICT.md docs/council/<slug>/CORPUS.md docs/council/<slug>/REBUTTAL.md docs/council/<slug>/members/L1-<name>.md docs/council/<slug>/members/L2-<name>.md
   git commit -m "docs(council): <slug> verdict at <short-sha>"
   ```
   List every member file by name, one path each, and omit `REBUTTAL.md` if no rebuttal ran. In
   corpus mode, the copied corpus is committed as its own commit, before any member is dispatched,
   so the freeze is visible in history.
2. Report the verdict path and the top findings. Do not paste the members' full returns into chat.

## Failure modes

| Failure | Guard |
|---|---|
| Manufactured findings: a member told to find problems will find them | Tell every member that a clean lens is a complete answer, and rate it a success when returned |
| The confident singleton, acted on unverified | Singletons are verified before they are acted on |
| Stale source: a member quotes a file that has since moved | Pin the revision; the manifest hash proves what was read |
| Scope creep upward: members travel out of the corpus for context | Name the boundary in every prompt; coverage is reported |
| Corpus leak: an earlier report reaches a member | Excluded items are not copied into the corpus; the dispatch lists the corpus paths only |
| Duplicate counted as independent support | De-duplicate by hash and by content before counting buckets |
| Late amendment: new evidence changes the corpus silently | Amendments are hashed, recorded in CORPUS.md, and reported in the verdict |
| Adjudicator anchoring on the author's view | Verification against source, not the adjudicator's memory |

## When not to convene

- One lens is enough: use `red-team`.
- The task is lookup or search: use Explore.
- A code change needs a review of its diff: use the code review tooling.
- The answer is checkable in a few tool calls, or the decision is cheap to reverse.
- The object is not yet stable. Findings would not still apply tomorrow.

For pattern selection more broadly, see `agent-patterns`. A council is a specialised parallel
sectioning pattern with a structured adjudication stage.
