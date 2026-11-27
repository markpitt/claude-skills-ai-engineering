---
name: project-kickoff
description: Turns a rough idea for a new product, venture or project into a short goal statement and a set of parallel workstreams (market and competitor research, MVP spec, name and design system, go-to-market, plus risks and a validation plan when they apply). Use when the user says "kick off this project", "start a new project from this idea", "here is an idea for a product", "set up the workstreams for this", "run project kickoff on the goal", or pastes a rough idea and asks what to do first. Starts one thread per workstream where the workspace supports parallel threads, and works through them in order in an ordinary chat. Do NOT use for planning a feature inside an existing codebase, for breaking down a single engineering task, or for a project that already has a spec and running workstreams.
license: Apache-2.0
metadata:
  version: "1.0.0"
  tags: "project-kickoff, planning, product, research, workstreams"
---

# Project Kickoff

**Goal:** turn a rough idea into a set of running workstreams in one pass, so the
user leaves with work in progress and one clear thing to do themselves.

## Step 1: Restate the goal

Write a goal statement of five lines at most:

- what is being built
- who it is for
- who is involved
- what the user already knows
- what success looks like

Do not ask questions unless the idea is too vague to name a target user. Choose
sensible defaults, such as the user's home market, and state each one so it can
be corrected.

## Step 2: Choose the workstreams

Consider each of these and drop any that does not fit the idea.

| Workstream | Covers | When |
|---|---|---|
| Market and competitor research | Competitors, pricing, regulation, how the target users work and buy | Always. It runs first and the others read its output |
| MVP spec | Core user workflow, must-have features, what is out of scope, a suggested tech stack, validation questions for real users | Always |
| Name and design system | Name shortlist with domain and trade mark checks, visual identity, UI components | When the product needs a public identity |
| Go-to-market | Segments, channels, positioning, pricing, launch phases | When the product will be sold or promoted |
| Risks and legal | Conflicts of interest, IP, contracts, regulatory exposure, the business structure between founders | When any of those is plausibly live |
| Validation plan | Who to interview, what to ask, how to record the answers | When the user lacks first-hand knowledge of the domain |

Keep to between four and six workstreams. Fewer is better than two that overlap.

## Step 3: Set the shared conventions

State these once, so every workstream follows them:

- Outputs go under one shared folder by topic: `research/`, `mvp/`, `brand/`,
  `marketing/`, `risks/`.
- Dependent workstreams start straight away instead of waiting for research.
  They mark an assumption that rests on research as `[RESEARCH]` and an
  unconfirmed assumption about the domain as `[VALIDATE]`.
- When one workstream produces something another needs, it is passed to that
  workstream. An example is marketing finding that users expect a data import
  feature, which belongs in the MVP spec.

## Step 4: Run them

**Where parallel threads are available** (a Claude Project with threads, or any
workspace that can run several agents at once):

1. Set the project's goal or topic to the goal statement.
2. Post one line saying what is being split out.
3. For each workstream, post a one-line message and start a thread on it with a
   short brief: the goal, the task, the output folder and what it depends on.

Keep each brief short. A brief that lists every deliverable leaves the
workstream no room to follow what it finds.

**In an ordinary chat with no threads:**

1. Give the goal statement and the list of workstreams.
2. Work through research first, then the others in order, each as its own
   document.
3. Say that a workspace with threads would run them in parallel, and offer to
   set that up.

## Step 5: Report

Send one short message covering:

- the workstreams started and what each will deliver
- the first thing the user must do themselves, which is usually to talk to real
  users or to check a contract

Give no time estimates.

## Example

Input: "I want to build a booking tool for independent dog groomers. My sister
is one and hates the app she uses."

Goal statement:

> A booking and reminders tool for independent dog groomers in the UK, built by
> the user with a groomer in the family as first tester. Known so far: the
> incumbent app is disliked. Success is five groomers using it for real bookings.
> Assumed: UK market, sole traders, mobile first.

Workstreams: research, MVP spec, name and design system, go-to-market, and a
validation plan, because the user is not a groomer. Risks and legal is dropped,
because nothing in the idea raises it.

First action for the user: ask the sister which three things she does in the
current app every day.
