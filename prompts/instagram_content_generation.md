Create RoozVan Instagram content in Persian/Farsi from the provided news context.

## News context

```json
{{CONTENT_CONTEXT}}
```

## Editorial scoring context

Use these scores to choose the Instagram format and calibrate depth:

```json
{{SCORING_CONTEXT}}
```

RoozVan is a Farsi-first Instagram page for Iranian diaspora and Persian-speaking immigrants living in Metro Vancouver, BC.

Goal: do not translate the English article word-for-word. Understand the item, simplify it, localize it for Metro Vancouver residents, and write natural Persian that explains why it matters.

Engineer all text — especially image overlay copy — for shares, saves, retention, and non-follower reach. Overlay text should make someone pause, save, or forward even if they do not follow the page.

---

## Step 1 — Choose `format`

Return exactly one of: `story`, `post`, `carousel_post`.

### Mandatory format rules (apply in order)

1. **`story` is required** when `actionability` is **1 or 2**, unless the article lists **three or more** concrete saveable details (specific dates, costs, deadlines, phone numbers, application steps, or eligibility rules). A single date or one fact is not enough to escape `story`.
2. **`story` is required** when `selection_gate_reasons` includes `interesting_local_fyi_story` or `outdoor_lifestyle_or_local_experience_relevance` and `actionability` is **3 or lower**, unless the article is a multi-step guide or policy explainer people must save.
3. **`carousel_post` is allowed only** when `actionability` is **4 or 5** **and** `practical_usefulness` is **4 or 5** **and** the article has **at least three** distinct facts or steps worth separate slides. Otherwise use `post` or `story`.
4. **Do not choose `carousel_post`** for a single announcement, one event, one store opening, one price change, or one quote — use `post` or `story`.
5. **Do not choose `post`** for pure FYI, vibe, or “did you know” items with no clear next step — use `story`.
6. When unsure between `story` and `post`, prefer **`story`** if the item will feel stale in 48 hours or is mainly for awareness, not planning.

### Format guidance

- **`story`**: quick, temporary, conversational, urgent alerts, same-day events, traffic, weather, short FYI, lifestyle/local colour without a checklist.
- **`post`**: one clear idea, single image + caption, simple announcements, one important change, community moments.
- **`carousel_post`**: saveable multi-step explainers, immigration, taxes, housing, healthcare, government policy, comparisons, “things to know” lists.

**Sanity check:** If you picked `post` or `carousel_post` but `actionability` ≤ 2, re-read the mandatory rules and switch to `story` unless the three-or-more saveable-details exception clearly applies.

---

## Step 2 — Generate content for the chosen format

### All formats

- `short_alt_text_fa`: one short accessibility sentence in Persian.
- `image_headline_fa`, `image_subline_fa`, `category_label_fa`: Persian text for the image overlay. Even for `carousel_post`, fill these from slide 1. Write overlay copy for shares, saves, retention, and non-follower reach — concrete, useful, and worth forwarding to someone who does not follow RoozVan.
  - `image_headline_fa`: what happened or what it is.
  - `image_subline_fa`: supporting detail for the image (see format-specific rules below).
  - `category_label_fa`: short topic badge (1–3 words).

### `story`

- Set `caption_fa` to `null`.
- Set `slides` to `[]`.
- For stories, the image overlay **is** the whole message — there is no caption, no link, no swipe-up, no “more below.”
- Story overlay must be **self-contained**: deliver the takeaway and one practical caution or next step in the headline/subline itself. Do not punt with vague CTAs like «اینو بخون», «بیشتر بخون», «جزئیات پایین», or «ادامه در کپشن» — there is nothing else to read.
- The story overlay renderer can show **up to 3 lines** of `image_headline_fa` and **up to 4 lines** of `image_subline_fa` (long text wraps automatically). Use as much of that space as the story needs; one line is fine for simple alerts, but events and FYI items usually need more.
- Pack in concrete facts from the article when available: **when** (dates/times/deadlines), **where** (neighbourhoods, venues, routes), **cost/tickets**, and one useful extra (scale, eligibility, free option). Pull from `description` and `article_content`, not just the title.
- Prefer specific place names (Granville Island, Downtown, Commercial Drive, BC Place, …) over vague «سراسر شهر» when the source names them.
- Do not repeat the same fact in headline and subline. Do not drop dates or locations for mood or a single impressive stat.
- Weak overlay: headline «جشنواره جاز ونکوور بازگشت», subline «۱۷۵ اجرا، ۳۰ کنسرت رایگان» (missing when/where/ticket types).
- Better overlay: headline «جشنواره بین‌المللی جاز ونکوور», subline «۱۹ ژوئن تا ۵ جولای · Granville Island و Downtown · ۳۰ اجرای رایگان و ۴۳ Pay What You Can».
- Weak overlay: headline «هتل‌ها ارزون شدن، اما Airbnb خطرناک‌تر شده», subline «اگه تازه‌وارد یا دانشجویی، اینو بخون» (tells people to read something that does not exist).
- Better overlay: headline «هتل‌ها ارزون شدن، اما Airbnb خطرناک‌تر شده», subline «کلاهبرداری و اجاره غیرقانونی قبل/بعد جام جهانی ۲۰۲۶ · قبل از پرداخت، آگهی و مجوز میزبان را چک کنید».

### `post`

- Set `caption_fa` to a full Instagram caption (3–5 bullet points + hashtags).
- Set `slides` to `[]`.
- Keep `image_headline_fa` and `image_subline_fa` short (about one line each); the caption carries the detail.
- Caption must add context beyond the image text: dates, costs, eligibility, next steps.
- Each caption bullet starts with 📌 ✅ 🗓️ 📍 🔎 or 👥 when appropriate.
- Put blank lines between bullets and hashtags on the final line (5–8 hashtags).

### `carousel_post`

- Set `caption_fa` to a carousel feed caption (3–5 bullets + hashtags). Use carousel language like «اسلایدها رو ورق بزنید» when useful. No down-arrow CTAs.
- Set `slides` to **3–6** slides. Prefer 4 or 5.
- `image_headline_fa` / `image_subline_fa` / `category_label_fa` must match **slide 1 exactly** (`slides[0]` uses the same headline, body, and badge). Slide 1 is what gets rendered on the first carousel image.
- Slide 1: article-level hook — why this matters locally, the overall scope (count, deadline, area). **Not** the first bullet from the article body. Later slides: empty `category_label_fa`.
- For **list / roundup** articles (“11 companies…”, “5 events…”, “things to know”): slide 1 = the full list headline and why to swipe; put the **first listed item on slide 2**, second item on slide 3, etc. Do not mirror the article’s section order on slide 1.
- Middle slides: one concrete fact, employer, event, step, or example each.
- Final slide: practical next step, uncertainty to watch, or save/share reminder.
- Each slide: `headline_fa` under 8 words, `body_fa` under 24 words, `visual_direction` for the scene.

### Language rules (all formats)

- Natural Persian for Iranian residents of Metro Vancouver.
- Gregorian dates with English month names (June, July, …). Persian numerals OK for day numbers.
- Keep official English names for brands, venues, stations (TransLink, BC Ferries, Commercial Drive, BC Place, …).
- No source attribution for now. No exaggerated urgency. No invented facts.
- For share-worthy utility (rebates, MSP, CRA, immigration, deadlines): invite save/forward in caption or final slide when appropriate.
- For events/festivals: warm invite to tag/share with friends when appropriate.
- Never use share/tag CTAs for crime, tragedy, or hardship with no helpful action.

Return JSON only matching the enforced schema.
