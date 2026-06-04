Write an Instagram caption in Persian for RoozVan, an Instagram page for Iranian diaspora in Vancouver, BC.

Use this post context:

```json
{{POST_CONTEXT}}
```

Rules:
- Write natural Persian for Iranian residents of Metro Vancouver.
- Be useful, concise, and trustworthy.
- Do not mention the source for now.
- Do not copy the article.
- Do not exaggerate urgency or certainty.
- Do not repeat the exact same headline/subline that should appear in the image.
- If the item is mostly FYI, make that clear and keep the tone light.
- If the item is practical, include dates, costs, locations, rules, or what this means for the audience.
- Structure `caption_fa` in short paragraphs. Start each paragraph with a bullet (•) or a simple, Instagram-friendly emoji that renders reliably in RTL text (e.g. 📌 ✅ 🔎 🗓️) and fits the line — do not use a different icon on every line.
- Do not use symbol-style emoji that often misalign in Instagram RTL captions, especially ℹ️, ©️, ®️, ™️, ↗️, or text-symbol icons with variation selectors.
- Put a blank line between paragraphs for readability.
- Include 5-8 hashtags at the end of `caption_fa`.
- Hashtags must match this post's topic only. Mix English and Persian when useful (e.g. #Vancouver, #ونکوور, #BC).
- Do not use hashtags for unrelated topics. Do not stuff generic tags.

Return JSON only:

```json
{
  "caption_fa": "",
  "short_alt_text_fa": "",
  "image_headline_fa": "",
  "image_subline_fa": "",
  "category_label_fa": ""
}
```
