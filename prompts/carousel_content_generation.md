Write a Persian Instagram carousel plan for RoozVan, an Instagram page for Iranian diaspora in Vancouver, BC.

Use this post context:

```json
{{POST_CONTEXT}}
```

Goal:
Create a saveable, swipe-by-swipe carousel. The carousel should explain a practical local topic more clearly than a single post.

Rules:
- Write natural Persian for Iranian residents of Metro Vancouver.
- Do not copy the article.
- Do not mention the source for now.
- Do not exaggerate urgency or certainty.
- Use 3-6 slides. Prefer 4 or 5 slides unless the topic is very simple.
- Slide 1 should be a strong hook focused on why this matters locally.
- Middle slides should organize concrete facts, dates, costs, locations, eligibility, examples, or what changed.
- Final slide should give a practical next step, uncertainty to watch, or save/share reminder.
- Only slide 1 should have a category label. For slides 2 and later, set `category_label_fa` to an empty string.
- Each slide must be understandable on its own, but avoid repeating the same sentence across slides.
- Keep each slide short: `headline_fa` under 8 Persian words and `body_fa` under 24 Persian words.
- Use standard Persian numerals where appropriate.
- For global brand names, keep official English spelling (Uber, Lyft, RiLo, BC Ferries) or the accepted short Persian form `لیفت` for Lyft. Never use awkward phonetic transliterations such as `لایفت`, `اوبر` for Uber (prefer `Uber`), or `سورج پرایسینگ` for surge pricing.
- For Metro Vancouver streets, neighbourhoods, stations, parks, and venues, keep the official English name exactly as published. Do not phonetic-transliterate them into Persian.
- Avoid fragile symbol-style emoji such as ℹ️, ©️, ®️, ™️, ↗️.
- The caption may briefly restate the carousel topic, but it must add context beyond the slide text.
- Do not use downward CTAs such as "بیشتر بخونید 👇", "ادامه پایین", or any down-arrow implication. In Instagram carousel, the detail is inside the slides, not below the caption.
- If a CTA is useful, use carousel-specific language such as "اسلایدها رو ورق بزنید", "برای جزئیات ورق بزنید", "ذخیره کنید", or "برای دوست‌تان بفرستید".
- **Events & festivals:** When the carousel is about local events, festivals, weekend plans, things to do, markets, parades, or family outings (`community_event` or similar), the **final slide** and/or the **last `caption_fa` bullet** should invite readers to **tag friends** or **share the post** with someone they might go with (one short, friendly line in Persian). Do not use this social CTA for tax, crime, policy, or hardship stories.
- For `caption_fa`, use 3-5 short bullet points separated by blank lines (`\\n\\n`). Start bullets with 📌, 🗓️, 📍, ✅, or 🔎 when useful.
- Put 5-8 relevant hashtags at the end of `caption_fa` on their own line after a blank line.
- Use broad, reusable hashtags for city, province, audience, and category. Avoid overly specific one-off hashtags that describe only this exact story.

Return JSON only:

```json
{
  "caption_fa": "",
  "short_alt_text_fa": "",
  "slides": [
    {
      "headline_fa": "",
      "body_fa": "",
      "category_label_fa": "",
      "visual_direction": ""
    }
  ]
}
```
