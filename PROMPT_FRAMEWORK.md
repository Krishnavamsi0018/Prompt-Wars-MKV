# The Prompt Warrior Framework

Use this structure for the prompt(s) your actual application sends to the AI model — this is the artifact that gets you the 30% Prompt Craft score, so it should look deliberate, not improvised.

## The 10 parts

1. **ROLE** — Who/what should the model act as?
2. **CONTEXT** — What background does it need to do this well?
3. **OBJECTIVE** — The single, precise thing you want accomplished.
4. **INPUT** — Exactly what data/user input is being handed over, and its shape.
5. **CONSTRAINTS** — What must and must not happen (length, tone, scope, safety).
6. **PROCESS** — How should it reason through the task (steps, order of operations).
7. **OUTPUT CONTRACT** — Exact format expected back (JSON schema, markdown structure, etc.) so your code can reliably parse it.
8. **QUALITY CRITERIA** — What separates a good answer from a mediocre one.
9. **FAILURE CONDITIONS** — What it should refuse or flag rather than guess at.
10. **VERIFICATION** — How the model (or your code) should double-check its own output before it's returned.

## Quick-fire version (when you're short on time mid-build)
`ROLE + OBJECTIVE + INPUT + OUTPUT CONTRACT + one key CONSTRAINT` is your minimum viable structured prompt. Add the rest as you iterate — and log each iteration.

## Example skeleton (fill in once you know the problem)

```
ROLE: You are a [X] that [does Y] for [audience].

CONTEXT: [Relevant background about the task/domain]

OBJECTIVE: Given [input], produce [specific output] that [accomplishes goal].

INPUT: [Describe input shape/type precisely]

CONSTRAINTS:
- Must [X]
- Must not [Y]
- Keep to [length/tone/format]

PROCESS: First [step], then [step], then [step].

OUTPUT CONTRACT: Return only valid JSON matching:
{
  "field1": "...",
  "field2": "..."
}

QUALITY CRITERIA: A good response [specific trait]. Avoid [common failure mode].

FAILURE CONDITIONS: If [input is malformed/out of scope], return {"error": "..."} instead of guessing.

VERIFICATION: Before returning, check that [specific thing] holds. If not, revise.
```

## Why this matters for scoring
Judges (and the AI evaluator) can only see the effectiveness of your prompting if you *show your work*. A one-line prompt that happens to work looks like luck. A structured prompt with a visible iteration trail looks like engineering. That distinction is worth 30% of your score — treat it accordingly.
