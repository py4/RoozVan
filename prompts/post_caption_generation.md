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
- Treat the image text and caption as two different jobs:
  - `image_headline_fa`, `image_subline_fa`, and `category_label_fa` are for the visual hook only.
  - `caption_fa` must add context, specifics, implications, and practical details that are not already stated in the image text.
- `caption_fa` may briefly restate the main point from the image when it makes the caption clearer, but it must quickly add new value: what this means, dates/costs/eligibility, uncertainty, background, or next steps.
- Keep `image_headline_fa` and `image_subline_fa` very short and broad. Do not put all useful details in the image; reserve the concrete details for `caption_fa`.
- If the item is mostly FYI, make that clear and keep the tone light.
- If the item is practical, include dates, costs, locations, rules, or what this means for the audience.
- **Share-worthy utility:** When the story helps people save money, claim a benefit, meet a deadline, or check eligibility — especially `money_tax`, `immigration`, `healthcare`, `housing`, `government_policy`, transit tips, MSP, CRA, rebates, renter rights, newcomer basics — add a **dedicated last bullet before hashtags** (use 👥 or 📤). One short line: save this post, forward/DM to a friend or family member who might qualify, or share with someone who may not follow English news. Examples: «این پست رو برای کسی که تازه اومده کانادا بفرست»، «اگه دوست یا فامیلت واجد شرایطه، حتماً براش بفرست». This is different from event invites — you are helping someone get money or avoid missing a deadline, not asking them to come with you.
- **Events & festivals:** When the story is about a local event, festival, street party, concert, market, parade, or family outing (often `category: community_event`, or titles mentioning festival, event, weekend plans, things to do), add a warm invite in `caption_fa` — usually as the **last bullet before hashtags** (use 👥 or 🔎). Examples: tag friends who would enjoy it, share with someone you might go with, or save/send to plan together. Keep it natural, not spammy (one short sentence).
- **Never use share/tag CTAs** for crime, tragedy, death, assault, political outrage, hygiene/shock stories, or hardship with no helpful action. Do not ask people to tag friends under bad news.
- For benefit/rebate/tax stories, skip event-style “بیا با هم بریم” language — use forward/save/DM language instead.
- For global brand names, keep official English spelling (Uber, Lyft, RiLo, BC Ferries) or `لیفت` for Lyft. Never use `لایفت` or other awkward phonetic transliterations.
- For Metro Vancouver streets, neighbourhoods, stations, parks, and venues, keep the official English name exactly as published (e.g. `Commercial Drive`, `Venables Street`, `Grandview Highway`, `Stanley Park`, `Jericho Beach`). Do not phonetic-transliterate them into Persian (avoid forms like `گرندویو هایوی` or `ونیبلز`). You may add a short Persian label before the name when helpful (e.g. `خیابان Commercial Drive`).
- For dates and deadlines, use the Gregorian calendar with English month names (January, February, March, April, May, June, July, August, September, October, November, December). Do not convert to Persian solar-calendar month names (فروردین، اردیبهشت، خرداد، تیر، ...). Persian month transliterations like ژوئن are also discouraged — prefer `June`, `July`, etc. Day numbers may stay in Persian numerals when natural (e.g. «از ۱۲ June» or «۸ تا ۲۸ July»).
- For `caption_fa`, use **exactly 3-5 short points**, never one long paragraph. Each point is 1-2 short sentences max.
- **Every point must start** with its own bullet emoji (📌 ✅ 🗓️ 📍 🔎). Do not put a single 📌 at the top and continue in prose.
- Put a real blank line between points (two newline characters in JSON, not spaces).
- Example shape:
  - `📌 hook + main news`
  - blank line
  - `✅ who qualifies / key fact`
  - blank line
  - `🗓️ dates / cost / hours`
  - blank line
  - `🔎 what to do next`
  - blank line
  - `👥 save / forward to someone who needs this` (when share-worthy utility or events — see rules above)
- Put hashtags on their own final line after one more blank line.
- Do not write dense paragraph blocks longer than 3 lines on a phone screen. If a point becomes long, split it into two points.
- Do not use symbol-style emoji that often misalign in Instagram RTL captions, especially ℹ️, ©️, ®️, ™️, ↗️, or text-symbol icons with variation selectors.
- Put a blank line between paragraphs for readability.
- Include 5-8 hashtags at the end of `caption_fa`.
- Hashtags must match this post's topic only. Mix English and Persian when useful (e.g. #Vancouver, #ونکوور, #BC).
- Use broad, reusable hashtags for city, province, audience, and category. Avoid overly specific one-off hashtags that describe only this exact story (for example, avoid tags like #پول_نقدنشده, #چک_نقدنشده, or a full event/article phrase).
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
