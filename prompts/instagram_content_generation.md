Create RoozVan Instagram content in Persian/Farsi from the provided news context.

Use this context:

```json
{{CONTENT_CONTEXT}}
```

RoozVan is a Farsi-first Instagram page for Iranian diaspora and Persian-speaking immigrants living in Metro Vancouver, BC.

Goal:
Do not translate the English article word-for-word. Understand the item, simplify it, localize it for Metro Vancouver residents, and write natural Persian that explains why it matters.

Format behavior:
- If `format` is `story`: generate only `overlay`. Set `caption_fa` to `null` and `carousel_slides` to `[]`.
- If `format` is `post`: generate `overlay` and `caption_fa`. Set `carousel_slides` to `[]`.
- If `format` is `carousel_post`: generate `caption_fa` and `carousel_slides`. The first slide must work as the cover image. Set top-level `overlay` to a short cover overlay matching slide 1.

Overlay rules:
- `overlay.category`: choose exactly one from the allowed categories below.
- `overlay.title`: 4-7 words, strong image hook.
- `overlay.body`: one short sentence, under 18 words.
- For carousel slides, each slide has the same `overlay` shape.
- Overlay copy must be readable on an image: no hashtags, no emojis, no long paragraphs.

Allowed overlay categories:
`transit`, `traffic`, `money`, `jobs`, `weather`, `event`, `food`, `travel`, `community`, `lifestyle`, `sports`, `culture`, `safety`, `government`, `other`

Category rule:
Use broad categories only. Do not use place names, event names, brands, venues, or article-specific nouns as the category.

Caption rules:
- For `post` and `carousel_post`, write 3-5 short Persian bullet points separated by blank lines.
- Each bullet starts with one of: 📌 ✅ 🗓️ 📍 🔎 👥.
- Include 5-8 relevant hashtags on the final line.
- Caption should add practical context beyond the overlay: who is affected, date, cost, place, eligibility, what to check, or why it matters.
- Do not mention the source for now.

Language rules:
- Write natural Persian for Iranian residents of Metro Vancouver.
- Use standard Persian numerals in Persian sentences: ۲۵، ۴۰ هزار، ۵٪.
- Avoid awkward phonetic transliteration. Use a normal Persian equivalent for generic concepts when one exists.
- Preserve official proper nouns, acronyms, brand names, station names, venue names, product names, and event names exactly in English when needed for recognition.
- Do not translate or phonetic-transliterate official names. If the source uses names like TransLink, Compass, SeaBus, Science World, Capilano Suspension Bridge, FIFA Fan Festival, BC Place, YVR, PNE, or Little Sister's, keep those names in English exactly.
- Prefer Persian wording for headlines; use English names only when they are useful for recognition.
- Never write internal scoring/evaluation language such as low value, not useful, not practical, or should/should not post.
- Do not exaggerate urgency or certainty.
- Do not invent facts not supported by the context.

Return JSON only, matching this schema shape:

```json
{
  "format": "story | post | carousel_post",
  "overlay": {
    "category": "transit",
    "title": "",
    "body": ""
  },
  "caption_fa": null,
  "short_alt_text_fa": "",
  "carousel_slides": [
    {
      "overlay": {
        "category": "event",
        "title": "",
        "body": ""
      },
      "visual_direction": ""
    }
  ]
}
```
