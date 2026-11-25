# Ideas

Uses for a free, fast, probability-only judgement across a set of projects. Built
ones are marked; the rest are candidates, roughly cheapest first within
each group. Every idea assumes the rules in SKILL.md: advisory only,
deterministic checks first, no secrets in the state.

## Development loop

- **Commit checks** (built: `commit-check`). Type, subject accuracy,
  changelog-worthy, public API, plus project questions from a file. Candidate next
  step: an opt-in `commit-msg` hook running `commit-check --strict`.
- **Changelog sweeper.** For each commit since the last tag, ask
  `user_visible`; list the ones with no CHANGELOG line before bumping the
  version. One request per commit, so cap it at the release range.
- **Docs drift.** Given a public API diff and the matching docs page, ask
  whether the page still describes the API. Pairs with a rule that
  signature changes and docs land in the same commit.
- **Test selection hint.** Several yes/no questions in one request, one
  per suite ("Could this diff break the integration tests that need a database?"),
  to order which suites to run first locally. Never to skip a suite in CI.

## CI and pull requests

- **CI triage** (built: `ci-triage`). Separates "Actions credit ran out"
  from real failures, so billing problems are reported rather than debugged.
  Candidate: run it inside the weekly CI health routine so the report
  says why each red run is red.
- **Review comment kinds** (built: `review`). Maps directly onto the PR
  rules: nits are answered and resolved, blocking asks are fixed, design
  asks go to the author.
- **Duplicate issues.** "Do these two issues describe the same bug?" over
  the newest issue against open ones in the same repository.
- **Release readiness.** A score over the Unreleased changelog, open
  `bug` issues and the last CI results, as a prompt for a human, never as
  the release gate.

## Agents and the project

- **Repository routing** (built: `route`). For a coordinating agent when
  an ask does not name a repository.
- **Effort router.** Score a task's difficulty on anchors such as
  "mechanical edit", "single-file change", "cross-repo change", "design
  work" and pick the agent model and effort from it. Calibrate against
  how often the cheaper choice had to be redone.
- **Turn-end check.** Before an agent posts, ask "Does this reply answer
  the question that was asked?" with the question and draft as state. A
  System 1 check on System 2 output; a low score means re-read, not
  rewrite.
- **Thread closure.** "Does anyone still owe a next step in this
  thread?" to suggest resolving quiet threads.
- **Memory hygiene.** For each team memory, with the current repository
  facts as state, ask whether it is still true; list the doubtful ones for
  a person.

## Inside the apps

Opt-in, off by default, never in a library or framework. Each needs a
deterministic fallback and must stay off the UI or render path.

- **Todo manager.** Turn a free-text task into a priority (score with A to
  D anchors) and a project or context (choice over the tags already in
  use).
- **Database tool.** "Is this SQL statement destructive?" as a second
  opinion after a real parser has classified it, to word the confirmation
  prompt.
- **Duplicate finder.** Which copy of a duplicate group to keep: a choice
  over paths with size, dates and folder names as state ("Downloads"
  versus "Photos/2024").
- **File explorer or IDE.** A command palette that accepts plain words: a
  choice over registered command ids and their descriptions, with ordinary
  fuzzy matching as the fallback and for exit 3.
- **Markdown editor.** On paste, "Is this Markdown, source code or plain
  prose?" to decide whether to fence it.
- **Coding agent.** Score a proposed tool call's risk before the approval
  prompt, and ask "Is the conversation about to exceed what context
  compaction can keep?" to time compaction.
- **Knowledge base.** "Do these two notes say the same thing?" for
  deduplication, and a choice over existing topics when filing a new note.
- **Speed test or monitor.** "Is this result unusual compared with these
  previous results?" to decide whether to suggest a re-test.
- **Music player.** A choice over queue strategies (more of the same,
  change of mood, deep cuts) from recent plays and skips.

## Novel patterns

- **Calibration loop** (built: `label`, `calibrate`). Every decision is
  logged; outcomes are recorded later; Brier score per question says
  which questions have earned the right to gate a prompt. This turns a
  black box into something measured.
- **Paraphrase ensembles.** Ask the same decision three ways in one request
  (three question names, three wordings) and treat disagreement as
  "unsure". Cheap, since they share a request.
- **Model-assisted test oracle.** Render a screen at a narrow
  size in a headless test host and ask "Does this frame show
  overlapping, truncated or misaligned text?" with the frame text as
  state. A sniff test that points a person at likely layout bugs; frame
  snapshots stay the real assertion.
- **UX copy lint.** "Does this error message tell the user what to do
  next?" over every user-facing string in a diff, matching the house rule
  that errors are actionable.
- **Snapshot comparison.** The log keeps each state, question and answer,
  so when the `:free` alias moves to a new snapshot the old states can be
  asked again and the answers compared before the new one is trusted.
