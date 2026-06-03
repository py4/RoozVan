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

## Scoring Context

Use this scoring context as editorial guidance:

```json
{{SCORING_CONTEXT}}
```

The scores come from the first editorial pass. Use them to decide how much publishing weight the item deserves:

- High `actionability`, `practical_usefulness`, and `share_save_potential` usually mean `post` or `carousel_post`.
- Low `actionability` but strong `local_relevance`, `trustworthiness`, or `selection_gate_reasons` such as `interesting_local_fyi_story` usually means `story`.
- If the item passed mainly because of `outdoor_lifestyle_or_local_experience_relevance`, prefer `story` unless there are concrete steps, dates, costs, rules, or planning details worth saving.
- Avoid `carousel_post` unless the article clearly contains multiple practical details and the scoring context shows strong practical usefulness, actionability, or share/save potential.
- Do not upgrade a quick FYI item to `post` just because the article has enough text.

## Use `story`

Choose `story` when the content is quick, temporary, conversational, or mainly useful right now.

Good story topics:

- urgent alerts
- same-day events
- traffic or transit delays
- weather warnings
- short reminders
- quick FYI items
- polls or engagement prompts
- reposting another post

Avoid `story` when the audience needs explanation, context, or a saveable reference.

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
