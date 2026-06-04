# RoozVan Instagram Format Selection

Choose the best Instagram publishing format for an Iranian diaspora audience in Vancouver, BC.

## Allowed Output

Return exactly one JSON object with exactly one field:

```json
{"format":"post"}
```

The only valid values are:

- `post`
- `story`
- `carousel_post`

Do not return markdown, explanations, scores, comments, or extra fields.

## Core Rule

Depth determines format:

- Low depth -> `story`
- Medium depth -> `post`
- High depth -> `carousel_post`

Apply the **mandatory rules** below before considering `post` or `carousel_post`.

## Scoring Context

Use this scoring context as editorial guidance:

```json
{{SCORING_CONTEXT}}
```

The scores come from the first editorial pass. Treat numeric fields as hard signals, not hints.

### Mandatory rules (apply in order)

1. **`story` is required** when `actionability` is **1 or 2**, unless the article lists **three or more** concrete saveable details (specific dates, costs, deadlines, phone numbers, application steps, or eligibility rules). A single date or one fact is not enough to escape `story`.
2. **`story` is required** when `selection_gate_reasons` includes `interesting_local_fyi_story` or `outdoor_lifestyle_or_local_experience_relevance` and `actionability` is **3 or lower**, unless the article is a multi-step guide or policy explainer people must save.
3. **`carousel_post` is allowed only** when `actionability` is **4 or 5** **and** `practical_usefulness` is **4 or 5** **and** the article has **at least three** distinct facts or steps worth separate slides. Otherwise use `post` or `story`.
4. **Do not choose `carousel_post`** for a single announcement, one event, one store opening, one price change, or one quote — use `post` or `story`.
5. **Do not choose `post`** for pure FYI, vibe, or “did you know” items with no clear next step — use `story`.
6. When unsure between `story` and `post`, prefer **`story`** if the item will feel stale in 48 hours or is mainly for awareness, not planning.

### General guidance

- High `actionability`, `practical_usefulness`, and `share_save_potential` usually mean `post` or `carousel_post` — but only if the mandatory rules above allow it.
- Do not upgrade a quick FYI item to `post` or `carousel_post` just because the RSS text is long.
- A balanced RoozVan feed needs **Stories** for timely/light items; defaulting everything to `post` or `carousel_post` is wrong.

## Use `story`

Choose `story` when the content is quick, temporary, conversational, or mainly useful right now.

Good story topics:

- urgent alerts
- same-day or this-weekend events (one time, one place — no multi-item guide)
- traffic or transit delays
- weather warnings
- short reminders
- quick FYI items
- lifestyle / local colour / “interesting” news with no checklist
- polls or engagement prompts
- reposting another post
- oil/gas price moves, single-stat headlines, or analyst quotes without a how-to

Avoid `story` only when the audience clearly needs a **saveable** reference (multi-fact guide, immigration steps, tax/benefit rules, event lists with many options).

## Use `post`

Choose `post` when the content has one clear idea and can be understood from a single image plus caption.

Good post topics:

- simple announcements
- one important change
- event announcements
- community moments
- holiday greetings
- quick statistics
- sponsorship or page updates
- simple alerts that are not complex enough for multiple slides

The most important information should be visible in the image. The caption can add nuance, source context, and hashtags.

## Use `carousel_post`

Choose `carousel_post` when the audience benefits from a swipe-by-swipe explanation, when the topic is saveable or shareable, or when details must be organized into steps.

Good carousel topics:

- explainers
- practical guides
- step-by-step instructions
- comparisons
- "things to know" lists
- rights, benefits, taxes, housing, healthcare, immigration, or government policy
- content likely to be saved or sent to friends

Ideal carousel structure:

- Slide 1: strong Persian hook focused on relevance and usefulness
- Slides 2-5: key facts, examples, who is affected, what changed, and what to do
- Final slide: summary, next action, save/share CTA, or source note

## Decision Guidance

Prefer `carousel_post` when:

- the topic has multiple important facts
- misunderstanding could create practical problems
- users may need to save the post for later
- the topic affects renters, newcomers, students, workers, families, healthcare access, money, immigration, or local rules

Prefer `post` when:

- there is one main message
- the topic is useful but not deep
- the visual can carry the key information clearly

Prefer `story` when:

- the value is mostly immediacy
- the information will expire soon
- the topic is light, conversational, or best used for engagement
- the scoring context shows low actionability but an interesting FYI or lifestyle/local-experience reason
- `actionability` ≤ 2 (mandatory unless the three-or-more saveable-details exception applies)
- `category` is `transit`, `weather`, or lifestyle/local colour without a step-by-step guide

**Sanity check before you answer:** If you picked `post` or `carousel_post` but `actionability` ≤ 2, re-read the mandatory rules and switch to `story` unless the exception clearly applies.
