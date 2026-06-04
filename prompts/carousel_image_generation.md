Create one polished 4:5 Persian Instagram carousel slide image for a local news page for Iranian diaspora in Vancouver, BC. Do not write the page name or Instagram account on the image.

Use this carousel slide context:

```json
{{CAROUSEL_CONTEXT}}
```

Goal:
Render exactly one slide from a multi-slide carousel. It must look visually consistent with the other slides but still be readable and useful by itself.

Text rules:
- Render Persian text natively inside the image.
- Use ONLY the human-readable strings in the context JSON: `headline`, `body`, and (if present) `upper_right_badge_text`.
- NEVER render JSON keys, field names, or English UI labels such as "category", "Category:", `category_label_fa`, `headline_fa`, or `visual_direction`.
- Upper-right category badge: ONLY when `show_upper_right_badge` is true (first slide only). Then render only `upper_right_badge_text` inside a small upper-right pill (e.g. حمل‌ونقل). Do not prefix it with "category" or any other label word.
- When `show_upper_right_badge` is false or `is_first_slide` is false, do NOT render any category badge, pill, label, or empty placeholder in the upper-right — even for visual consistency with other slides.
- When `upper_right_badge_text` is absent, do not create a category badge, placeholder, pill, blank label, or extra top-right element.
- `scene_notes` are for the illustration only. Do not render `scene_notes` as visible text in the image.
- Do not render slide numbers, slide counters, pagination, progress dots, or `x/y` indicators inside the image. Instagram already shows carousel position in the UI.
- Do NOT render any page name, Instagram handle, @username, URL, QR code, watermark, or RoozVan / روز وَن / roozvan branding anywhere (including top-left). The RoozVan logo is added automatically after generation in the bottom-left corner only.
- Use clean, modern, bold Persian typography with correct RTL flow.
- Keep text crisp and flat. Do not use heavy shadows, glows, blurry outlines, or tiny text.
- Avoid awkward Persian transliteration of English terms. If there is a common, natural Persian equivalent, use it; otherwise keep the original English phrase. For example, use "افزایش ناگهانی قیمت" or "surge pricing", never "سورج پرایسینگ".

Layout:
- Aspect ratio: 4:5.
- Modern editorial carousel style with one clear visual idea.
- Keep composition consistent across slides: same typography system, similar margins, and related color palette. Consistency does NOT mean repeating the slide-1 category badge on later slides.
- The content must start from the right side: put the upper-right badge text (if any) near the upper-right, right-align the headline/body, and keep the visual reading order clearly right-to-left.
- Top-left corner must stay free of all text and branding (no account name, no logo, no handle).
- Place the main Persian text in the upper and center-right areas when possible. Do not make the viewer start reading from the left.
- Use local Vancouver/BC visual cues when relevant: transit, streets, water, mountains, parks, shops, homes, or civic spaces.
- Bottom-left logo zone (bottom ~20%, left ~30%): no text or graphics. Use natural low-detail negative space from the scene itself. Preserve normal color and lighting; do NOT brighten, whiten, haze, vignette, wash out, or discolor this corner for the logo.
- Avoid fake app UI, multi-card templates, hard-edged placeholder boxes, obvious faded patches, and local white glows.

Output:
Generate one image only for the requested slide.
