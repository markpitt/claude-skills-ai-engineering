# Lens library

Pick 3 to 7 lenses. Two lenses that would find the same defect are one lens: cut one. At least one
pair should hold opposed stances on the same question.

Each lens entry gives the lens, the stance to assign, and the deliverable to demand. The deliverable
is an artefact with a shape, not "thoughts" or "a review".

## Writing a lens

A lens has five parts. If any is missing, the member will return the model's prior.

| Part | Test | Example |
|---|---|---|
| Lens | One sentence. If it needs a paragraph, it is not sharp enough. | "You are the opposing party's counsel, instructed to defeat this claim at lowest cost." |
| Stance | Assigned, and deliberately one-sided where needed. Not "be balanced". | "Stance: this fails on its own terms." |
| Scope | The corpus paths or object parts the member may read. | "Corpus items 01 to 06 only." |
| Question | The single question this member answers. | "Which of the pleaded heads survives a strike-out application?" |
| Deliverable | A named artefact with fields. | "A table: head, strength (high, medium, low), weakest link, source path." |

## Universal lenses

**The adversary.** You are the opposing party's professional, resourced and motivated to defeat
this at lowest cost. Stance: this fails. Deliverable: the three attacks you would run, in order, and
what each costs the other side.

**The advocate.** Assigned the opposite stance to the adversary, on the same object. Stance: this is
stronger than its author thinks and is being undersold. Deliverable: what is being given away for
nothing, and the strongest form of the object.

**The arithmetic auditor.** Numbers only, no narrative. Stance: none; recompute from primary
sources. Deliverable: every figure recomputed from source, a divergence table where documents
disagree, and a statement of which figures reconcile exactly.

**The completeness auditor.** Stance: something material is missing. Deliverable: what the evidence
supports that the object does not claim, and what the object asserts that nothing supports.

**The structural engineer.** Mechanics, not merits: does the thing hold together, is it enforceable,
does it survive contact with the process it must pass through. Deliverable: the failure points, and
the drafting or sequencing that closes each.

**The critical-path engineer.** Stance: this takes longer than it needs to. Deliverable: the real
dependency chain, which gates are genuine and which are ceremony, and the shortest honest route to
done.

**The premise auditor.** Stance: the question is wrong. Deliverable: what the object assumes without
examining, and what changes if the assumption is false. Use sparingly: one per council, and only
where the framing is genuinely contestable.

**The downside modeller.** Stance: model the bad end. Deliverable: the realistic worst case, its
likelihood, its cost, and which decision made now is hardest to reverse if it lands.

## Domain lenses

**Legal or regulatory merits.** Each asserted obligation or claim against the evidence actually
held, with the operative text quoted from the official source. Deliverable: per head, a strength
rating and the single weakest link.

**Financial and tax treatment.** How money is characterised, taxed, sequenced and paid.
Deliverable: the treatment that is settled, the treatment that is contested, and what must be agreed
in writing rather than left to a later process.

**Process and procedure.** Deadlines, gateways, forms, service, jurisdiction. Deliverable: the dated
critical path, with the authority for each date.

**Human factors.** Capacity, sustainability, cognitive load, and what the plan asks of the person
executing it. Stance: the plan assumes a version of this person that will not exist under load.
Deliverable: where it breaks, and what to remove.

**Consistency and propagation.** Does a fact changed in one document agree with itself everywhere
else it appears. Deliverable: the divergence table.

**Code correctness.** Bugs and failure scenarios only, no style. Deliverable: concrete inputs that
produce wrong output.

**Security.** Trust boundaries, authorisation, data exposure. Deliverable: the exploit path, not the
category name.

## Composition patterns

**Decision review (5).** Adversary, advocate, arithmetic auditor, critical-path engineer, downside
modeller.

**Document review (5).** Adversary, completeness auditor, consistency and propagation, arithmetic
auditor, structural engineer. This is the usual shape for corpus mode.

**Strategy review (6).** Adversary, advocate, premise auditor, critical-path engineer, downside
modeller, human factors.

**Technical review (4).** Code correctness, security, structural engineer, adversary.

## Anti-patterns

- Five careful generalists. That is one reviewer with a bigger bill.
- A lens with no stance. It returns the model's prior, which already dominates consensus.
- More than one premise auditor. The council spends itself relitigating the question.
- A lens whose deliverable is "thoughts" or "a review". Name the artefact.
- A lens that can read the whole corpus when its question needs three items. Scope narrows
  duplication; it also makes coverage reportable.
