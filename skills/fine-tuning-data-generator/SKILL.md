---
name: fine-tuning-data-generator
description: Plans, generates and validates synthetic fine-tuning datasets as ChatML JSONL for Unsloth, Axolotl, Hugging Face TRL and similar trainers. Gathers what the model must learn, agrees a generation plan, writes diverse single- and multi-turn examples in batches, checks them with the bundled validator and analyser, and gives trainer configuration. Use when asked to "make a training dataset", "generate fine-tuning examples", "create ChatML data for Unsloth" or "check this JSONL before I train on it". Do NOT use for choosing or serving a model (use local-llm-serving), for evaluation suites or test prompts for an existing model, or for prompt engineering with no training involved.
license: Apache-2.0
allowed-tools: Read, Write, Edit, Bash
metadata:
  version: "3.0.0"
---

# Fine-tuning data generator

This produces synthetic training data in ChatML JSONL, one example per line:

```json
{"messages": [{"role": "system", "content": "You are a helpful assistant."}, {"role": "user", "content": "How do I reverse a string in Python?"}, {"role": "assistant", "content": "Use slicing: `text[::-1]`"}]}
```

A multi-turn example adds further user and assistant pairs. The `system` message is optional, but
if the deployed model will get one, the training data should carry the same kind.

Synthetic data teaches a model whatever patterns it contains, including the ones you did not mean
to put there. Repetitive phrasing, uniform lengths or a template that shows through all get learnt
as faithfully as the content. Most of this skill is about avoiding that.

## How a dataset gets made

**1. Find out what the model must learn.** Ask what the model is for, the domain, the tone and
length of a good answer, the formats it must produce (code, JSON, tables), how hard the inputs get,
and whether it must learn to refuse or push back. Ask how it will be deployed, since the system
prompt and turn structure should match. `resources/dataset-strategy.md` has the full question set.

**2. Agree a plan before generating.** Set out the categories and how many examples each gets, the
spread of difficulty, the edge cases (usually a fifth to a third of the set), the system prompt
approach, and the validation split (10 to 20 per cent), using `templates/generation-plan.md`. Wait
for the user to approve it. A plan is cheap to change, and a thousand generated examples are not.

**3. Generate in batches.** Start with 10 to 20 examples and have the user review them; most
problems show up here. Then generate 50 to 100 at a time, and check the spread after each batch to
see what is over- or under-represented. Vary the phrasing (questions, commands, half-finished
thoughts), the user's expertise, and the length and structure of answers. Write user turns the way
people actually type, not as tidy, formal questions. `resources/generation-techniques.md` covers
the techniques and domain-specific advice, and `resources/examples.md` has samples.

**4. Validate.**

```bash
python3 scripts/validate_chatml.py training_data.jsonl --verbose
python3 scripts/analyze_dataset.py training_data.jsonl --export stats.json
```

The validator checks JSON, required fields, roles, message order and duplicates. The analyser
reports lengths, query and response patterns, a diversity score, balance and a token estimate. A
clean validation is necessary and not sufficient: read a random sample of 20 or so by hand, because
the scripts cannot tell a wrong answer from a right one. `resources/quality-validation.md` covers
fixing what they find.

**5. Hand over.** Deliver `training_data.jsonl`, the optional `validation_data.jsonl`, and a short
`dataset_info.txt` recording the plan, the counts and how the data was generated. Without that
record, nobody can reproduce or extend the set later.

## Trainer notes

- **Unsloth:** load with its chat template helper, set to `chatml`.
- **Axolotl:** `type: chat_template` with `chat_template: chatml`.
- **Hugging Face TRL:** the tokeniser's `apply_chat_template()` turns each `messages` list into
  text.

Setup code, hyperparameters and deployment are in `resources/framework-integration.md`, and format
edge cases in `resources/chatml-format.md`.

## How big

| Task | Examples |
|---|---|
| Narrow and well defined | 100 to 500 |
| Several scenarios, moderate variation | 500 to 2,000 |
| Many edge cases, high variability | 2,000 to 10,000 or more |
| Domain adaptation | 1,000 to 5,000 |

Five hundred varied, correct examples beat five thousand near-copies. If a set has to grow, grow it
where the analyser shows gaps, not evenly.

## What goes wrong

- A visible template: every answer opens the same way, so the model does too.
- Users who all write like the generator: polite, complete, grammatical.
- Coverage that is wide on topics and narrow on phrasing.
- Quality that drifts across batches. Review the last batch as hard as the first.
- Answers that do not quite address the question, which a validator never catches.
- A system prompt in training that differs from the one in production.
