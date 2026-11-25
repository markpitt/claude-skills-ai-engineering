// Harvest workflow for the sandboxed-agent skill. Pass to the Workflow tool as `script`,
// with args = { files: [...absolute paths...], topic: "dokploy", keywords: ["dokploy","traefik"] }.
// Stages per file: extract (Haiku) -> redact (Haiku) -> judge (Sonnet). The judge is the gate:
// it re-checks each note against the source for secrets, accuracy and relevance, and only
// its `keep` list survives. Nothing is written by this script; the caller stages and reviews.
export const meta = {
  name: 'sandboxed-agent-harvest',
  description: 'Mine host Claude transcripts and memory for one topic: extract, redact, judge',
  phases: [
    { title: 'Extract', detail: 'Haiku, one agent per source file' },
    { title: 'Redact', detail: 'Haiku strips secrets and off-topic notes' },
    { title: 'Judge', detail: 'Sonnet verifies each note against its source' },
  ],
}

const TOPIC = args.topic
const WORDS = (args.keywords || [TOPIC]).join(', ')

const NOTES = {
  type: 'object',
  properties: {
    notes: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          topic: { type: 'string' },
          kind: { type: 'string', enum: ['howto', 'gotcha', 'api', 'architecture', 'decision', 'ops-rule', 'path', 'incident'] },
          text: { type: 'string' },
          confidence: { type: 'string', enum: ['high', 'medium', 'low'] },
        },
        required: ['topic', 'kind', 'text', 'confidence'],
      },
    },
  },
  required: ['notes'],
}

const VERDICT = {
  type: 'object',
  properties: {
    keep: { type: 'array', items: { type: 'number' }, description: 'indexes of notes to keep, unchanged' },
    fix: {
      type: 'array',
      items: { type: 'object', properties: { index: { type: 'number' }, text: { type: 'string' }, why: { type: 'string' } }, required: ['index', 'text', 'why'] },
      description: 'notes to keep with corrected text (secret removed, claim narrowed)',
    },
    drop: {
      type: 'array',
      items: { type: 'object', properties: { index: { type: 'number' }, why: { type: 'string' } }, required: ['index', 'why'] },
    },
  },
  required: ['keep', 'fix', 'drop'],
}

const extract = (f) => `Mine ONE Claude Code session/memory file for durable knowledge about "${TOPIC}" (keywords: ${WORDS}), to seed a new agent's instruction manual.
File: ${f}
A .jsonl file is one JSON object per line and can be many MB: do NOT read it whole. Use grep -n -i and jq to find relevant message text and commands, then read small windows. Markdown: read directly.
Keep only facts that stay true and help someone operating this: procedures, API usage, conventions, gotchas with their fix, rules the user stated, paths, decisions with reasons.
Skip chatter, one-moment status, generic knowledge, anything off-topic.
HARD RULE: never write a secret value (keys, tokens, passwords, cookies, private keys, credentialed URLs, .env contents). Say where a secret lives instead.
Prefer 5-25 strong notes. An empty list is fine.`

const redact = (f, r) => `Clean these notes from ${f} before sharing with a sandboxed agent. Remove or rewrite anything containing a secret value or unneeded personal data (keep the lesson, drop the value); drop notes that are off-topic, stale one-moment status, or vague. Add no new facts.
NOTES JSON:
${JSON.stringify(r.notes)}`

const judge = (f, r) => `You are the final gate before notes are given to a sandboxed agent. Verify each note against its source file: ${f}
(Use grep/jq on the source; do not read a large .jsonl whole.)
For every note decide: keep (true, on-topic, no secret), fix (true but needs a narrower claim or a secret removed: give corrected text), or drop (unsupported by the source, off-topic, host-only detail the agent cannot act on, or sensitive). A note that states something the source does not support must be dropped, not softened. When unsure, drop.
Indexes refer to the array below.
NOTES JSON:
${JSON.stringify(r.notes.map((n, i) => ({ index: i, ...n })))}`

const results = await pipeline(
  args.files,
  (f) => agent(extract(f), { model: 'haiku', phase: 'Extract', label: 'extract:' + f.split('/').pop().slice(0, 12), schema: NOTES }),
  (r, f) => (r && r.notes && r.notes.length)
    ? agent(redact(f, r), { model: 'haiku', phase: 'Redact', label: 'redact:' + f.split('/').pop().slice(0, 12), schema: NOTES })
    : { notes: [] },
  async (r, f) => {
    if (!r || !r.notes || !r.notes.length) return { file: f, notes: [], dropped: 0 }
    const v = await agent(judge(f, r), { model: 'sonnet', phase: 'Judge', label: 'judge:' + f.split('/').pop().slice(0, 12), schema: VERDICT })
    if (!v) return { file: f, notes: [], dropped: r.notes.length, judged: false }
    const fixed = new Map(v.fix.map((x) => [x.index, x.text]))
    const keepIdx = new Set([...v.keep, ...v.fix.map((x) => x.index)])
    const out = r.notes.map((n, i) => (keepIdx.has(i) ? { ...n, text: fixed.has(i) ? fixed.get(i) : n.text } : null)).filter(Boolean)
    return { file: f, notes: out, dropped: r.notes.length - out.length, judged: true }
  },
)

const out = results.filter(Boolean)
log('kept ' + out.reduce((a, o) => a + o.notes.length, 0) + ', dropped by judge ' + out.reduce((a, o) => a + (o.dropped || 0), 0))
return out
