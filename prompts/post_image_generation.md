Create one polished 4:5 realistic editorial photo background for a RoozVan Instagram post. RoozVan is a local news page for the Iranian diaspora in Metro Vancouver, BC.

Use this post context:

```json
{{POST_CONTEXT}}
```

Goal:
Create a strong Instagram-ready visual background for the main hook. Persian overlay text (category badge, headline, and subline) will be composited on top in post-production. Caption will explain the concrete details, implications, and next steps later.

Text rules:
- Do not render Persian text natively inside the image.
- Do not render any written content at all: no headlines, captions, category labels, street names, route numbers, bus displays, signs, labels, logos, watermarks, posters, page names, URLs, or UI text.
- Treat `image_headline_fa`, `image_subline_fa`, and `category_label_fa` as context for choosing the scene only. They must not appear visibly in the generated image.
- Do not render JSON keys or values as visible text.

Layout:
- Aspect ratio: 4:5.
- Modern editorial news design with one dominant visual idea.
- Reserve the top 40% as clean, uncluttered negative space for the Persian overlay added later.
- Place the main scene, people, vehicles, objects, or venue details mostly in the lower 60%.
- Bottom-left logo zone (bottom ~20%, left ~30%): no text or graphics. Use natural low-detail negative space from the scene itself, such as plain pavement, water, sky, wall, grass, shadow, or uncluttered foreground. Preserve the scene's normal color and lighting; do NOT brighten, whiten, blur, haze, vignette, wash out, or discolor this corner just to make room for the logo. The RoozVan logo is added automatically after generation.
- Do NOT render any page name, Instagram handle, @username, URL, or RoozVan / روز وَن / roozvan branding anywhere (including top-left). Do not add RoozVan logo, watermark, source name, QR code, or fake UI placeholder rectangles.
- Avoid clutter, text boxes, multi-card layouts, tiny unreadable text, obvious faded patches, or local white glows.

Visual direction:
Use local Vancouver/BC visual cues when relevant: coastal water, ferries, mountains, urban streets, parks, outdoor lifestyle, transit, or neighborhood scenes. Make it look like a premium local Instagram news post.

Output:
Generate one 4:5 portrait photo background only. No typography, no written content, no branding.
