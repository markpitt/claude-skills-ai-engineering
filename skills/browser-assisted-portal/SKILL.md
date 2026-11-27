---
name: browser-assisted-portal
description: Helps a person through a government or service portal in a browser-automation session (for example Claude in Chrome). The person signs in and submits. The agent reads and captures pages, explains each question and the check-your-answers page, flags conflicts, and keeps a dated record of what was entered and seen. Use when a browser agent is asked to help with an online form, application, claim or account on a public or service portal and the person will do the sign-in and the final step. Do NOT use to submit, pay, sign, declare or confirm anything, to log in for the person or handle their passwords or codes, to scrape or bulk-download a site, or to test a web application as a developer (use a browser end-to-end testing tool). For a script to hand a person when a guard blocks a write, use remediation-script.
license: Apache-2.0
metadata:
  version: "1.0.1"
  tags: "browser, portal, forms, government, service, claude-in-chrome, record-keeping, human-in-the-loop"
---

# Browser-assisted portal work

Help a person complete an online portal task without taking the step that matters. The person holds
the sign-in, decides every answer and presses the final control. The agent reads, explains, captures
and records. Its output is a clear picture of what is on the page, what was entered and what is left
for the person to do.

## Critical boundaries

- **The person signs in.** Never type or request a password, one-time code, security answer, PIN or
  recovery detail. If the portal asks for any of these, stop and hand over to the person.
- **The agent never submits.** Do not press a control that submits, saves a declaration, signs,
  confirms, pays, withdraws, or moves a record on to the next stage. Leave the page where it is and say
  which control the person should press.
- **Values come from the person.** Enter a value only when the person has given it for a named field
  in this session. Do not guess a figure, a date or an eligibility answer to get past a question.
- **Do not decide for the person.** Explain what a question means and what the guidance says. Lay out
  the options. The choice is theirs.
- **Stay on the named portal.** Open other sites only when the person asks. Do not read their other tabs,
  history or saved sessions beyond the portal they named.
- **No workarounds.** If a CAPTCHA, a rate limit or an access check appears, stop. Do not try to
  defeat it, and do not reload repeatedly to get past it.
- **Personal data stays minimal.** Do not put full identifiers (National Insurance, bank, passport or
  full account numbers) into chat or logs. Where a reference must be recorded, mask it to the last
  four characters and say the rest is withheld.

## Roles

| Person | Agent |
|---|---|
| Signs in, reads sensitive pages, chooses answers, presses submit | Reads and summarises pages, explains guidance, enters values given to it, records every step, compares answers |
| Keeps the confirmation and any reference number | Reminds the person what to keep and where the confirmation appears |

## Procedure

1. **Agree the scope in one exchange.** Confirm the portal (its domain, not any URL that carries a
   token), the goal (understand the questions, prepare answers, check a completed form, or read a
   confirmation), the deadline and who presses the final control. Write these at the top of the record.
2. **Load the browser tools once.** If the browser tools are deferred, load every one you expect to use
   in a single ToolSearch selection. Use only the browser the person connected.
3. **Open a new tab.** Do not reuse a tab unless the person points to it. Note the page heading, the step
   or progress indicator and any on-page guidance before anything else.
4. **Read the page, then capture it.** Record each question with its guidance, its options and any
   error text. Quote short guidance and paraphrase the rest. Do not copy long passages of a portal's text.
5. **Explain each question.** Say in plain English what it asks, what evidence it usually needs, and
   whether an earlier answer bears on it. Flag any conflict with an earlier answer. Do not select an
   option yourself.
6. **Enter only what the person gave.** Fill the named field, read it back, and record the value as
   entered. Then stop and tell the person the page is ready for them to check and continue.
7. **On the check-your-answers page, read every row.** Compare each row with the record. Report matches,
   mismatches, blanks where the guidance says an answer is required, and anything the portal says will
   happen after submission. Give the person a list to check against their own papers. Do not press the
   submit control.
8. **Hand over explicitly.** List what remains for the person: sign-in, declarations, the final control,
   any payment, saving the confirmation page or reference number, and the deadline.
9. **Close what the agent opened.** Close tabs the agent created unless the person wants them kept. Give
   the person the record file path.

## Dialogs and page tools

- Browser dialogs (alert, confirm, prompt) block further browser commands. Avoid controls likely to raise
  one, such as delete or cancel. If one is unavoidable, warn the person first.
- Do not read request or response bodies from the network log. They can hold tokens and personal data.
- Do not record screen captures of pages that show personal data unless the person agrees. Crop captures
  to the guidance text where that is enough.
- Do not run page scripts beyond what the person has authorised, and never to change a form's values.

## Stop and ask

Stop and tell the person what happened, what you tried and what they need to do, when any of these occur:

- a password, one-time code, identity check or CAPTCHA appears
- sign-in is lost more than once in a session
- the page wording contradicts the person's understanding or the record
- a control would submit, sign, pay or move the record on, and the person has not pressed it
- two or three attempts at the same browser action fail; do not keep retrying
- the task grows beyond the named portal or the agreed goal

## The record

Keep one dated Markdown file per session, in the location the person names. Do not write it inside a
repository unless the person chooses that location and the path is ignored by git. The layout is in
`references/record-template.md`. It records the scope, each step's question, guidance summary, value
entered as given, status, errors seen, the check-your-answers comparison and the hand-over list. It
never holds a password, a code or a full identifier.

## Neighbours

- **remediation-script** writes a script for a person to run when a guard blocks the agent's own file
  writes. It does not drive a website.
- **A browser end-to-end testing tool** checks a web application for a developer. It may be used
  against a site the developer owns; it is not for helping a person with a government or service form.
