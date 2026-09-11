# PromptWars × TechVerse — Battle Cheatsheet

## Event
- Date: 11 September | Venue: Brindavan College of Engineering
- Build time: ~4 hrs total (11:00–1:00, 1:30–3:30)

## Agenda
| Time | Block |
|---|---|
| 10:00–10:45 | Inauguration |
| 11:00–1:00 | Build Sprint 1 |
| 1:00–1:30 | Lunch |
| 1:30–3:30 | Build Sprint 2 |
| 3:30–4:00 | AI Evaluation (automated — nothing to do, just be frozen by 3:30) |
| 4:15–5:00 | Top 10 announced + prep |
| 5:00–6:00 | Pitching Finale |
| 6:00–6:30 | Prizes |

## Mandatory submission (all three or you lose points)
- [ ] GitHub repo (public, complete source)
- [ ] Live deployed link (verified in incognito)
- [ ] Presentation (solution + approach + **prompt strategy**)

## Judging weights — what to actually spend time on
| Criterion | Weight | Where it's won |
|---|---|---|
| Prompt Craft | 30% | Documented, structured, iterated prompts (see PROMPT_STRATEGY_TEMPLATE.md) |
| Output Accuracy | 25% | Edge-case testing block (2:30–3:00) |
| Creativity | 20% | Idea selection in first 15 min — pick the non-obvious angle |
| Relevance | 15% | Every feature maps explicitly back to the brief |
| Presentation | 10% | Confident WHAT/HOW/WHY delivery |

**55% is Prompt Craft + Accuracy. A simple thing that works beats a flashy thing that's flaky.**

## Rules
- Any AI tools/models/APIs allowed. Any deploy platform allowed.
- No templates, pre-built projects, or copied code — must be built live.

## Hour-by-hour
- 11:00–11:15 — Understand the brief: objective, user, output, constraints, what NOT to build
- 11:15–11:30 — Generate 2–4 solution directions, pick by Impact × Creativity × Feasibility × Promptability
- 11:30–11:45 — Design the core prompt architecture (use PROMPT_FRAMEWORK.md)
- 11:45–1:00 — MVP Sprint 1: get input → processing → output working end to end, deployed ugly
- 1:30–2:30 — MVP Sprint 2: finish core functionality
- 2:30–3:00 — Edge cases: normal / weird / empty / invalid / malicious input, API failure handling
- 3:00–3:20 — UI + demo polish (only now)
- 3:20–3:30 — Freeze. Deploy. Push. Verify production. Stop touching it.

## WHAT / HOW / WHY — rehearse this for every major feature
- **What** does it do (one sentence, plain language)
- **How** does it actually work (the real mechanism — frontend→backend→prompt→model→validation→response)
- **Why** did you build it this way (the tradeoff you made and why)

If you can't answer all three without checking the code, you don't own that feature yet — fix that before 3:30.

## Demo survival kit (set up tonight)
1. Live deployed link (primary)
2. Backup deployment (second host, or a second deploy target) in case the primary goes down
3. Local version running on your machine as fallback
4. Screenshots + a 60–90 sec screen recording of the working flow, saved offline, in case wifi dies mid-pitch

## Golden rule
Don't let the AI build something you can't explain. If a feature can't survive a judge asking "why," cut it.
