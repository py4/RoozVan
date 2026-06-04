Create one polished 4:5 Persian Instagram carousel slide image for RoozVan, a local news page for Iranian diaspora in Vancouver, BC.

Use this carousel slide context:

```json
{{CAROUSEL_CONTEXT}}
```

Goal:
Render exactly one slide from a multi-slide carousel. It must look visually consistent with the other slides but still be readable and useful by itself.

Text rules:
- Render Persian text natively inside the image.
- Use exactly these text elements from `slide`: `category_label_fa`, `headline_fa`, and `body_fa`.
- Render the category label only when `category_label_fa` is non-empty. If it is empty, do not create a category badge, placeholder, pill, blank label, or extra top-right element.
- Do not render slide numbers, slide counters, pagination, progress dots, or `x/y` indicators inside the image. Instagram already shows carousel position in the UI.
- Do not add extra facts, source names, handles, QR codes, watermarks, or RoozVan logo.
- Use clean, modern, bold Persian typography with correct RTL flow.
- Keep text crisp and flat. Do not use heavy shadows, glows, blurry outlines, or tiny text.

Layout:
- Aspect ratio: 4:5.
- Modern editorial carousel style with one clear visual idea.
- Keep composition consistent across slides: same typography system, similar margins, and related color palette.
- The content must start from the right side: put the category label near the upper-right, right-align the headline/body, and keep the visual reading order clearly right-to-left.
- Place the main Persian text in the upper and center-right areas when possible. Do not make the viewer start reading from the left.
- Use local Vancouver/BC visual cues when relevant: transit, streets, water, mountains, parks, shops, homes, or civic spaces.
- Bottom-left logo zone (bottom ~20%, left ~30%): no text or graphics. Use natural low-detail negative space from the scene itself. Preserve normal color and lighting; do NOT brighten, whiten, haze, vignette, wash out, or discolor this corner for the logo.
- Avoid fake app UI, multi-card templates, hard-edged placeholder boxes, obvious faded patches, and local white glows.

Output:
Generate one image only for the requested slide.
