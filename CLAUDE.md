# Project context for Claude

This tool was designed and built in an earlier Claude Code session with Sean Walker
(Unite Ideas). These are the decisions and facts from that session. README.md has the
setup steps and usage.

## Owner preferences
- Never use em dashes in code, docs, generated post text or replies.
- Sean runs everything on his Windows PC (PowerShell). Paths use `D:\...`.
- Explain steps plainly; Sean is not a developer.

## What the tool does
Sean gives a business and city (e.g. "Rock N Roll Sushi" "Mansfield, TX"). The tool:
1. Finds the job folder in local Dropbox and reads its documents and photos.
2. Gets photos from the Google listing (Places API New) and web pages found by Claude's web search.
3. Keeps ONLY photos of the building: exterior, interior, construction. People are OK but
   photos without people are preferred. No food, product or marketing shots.
4. Writes a short post (a line or two up to a couple of paragraphs) from Dropbox docs and
   research on developers, builders and local officials.
5. Shows a local review page, then creates a DRAFT portfolio post. Never publish automatically.

First jobs: Rock N Roll Sushi, Pancheros Mexican Grill and Hurts Donut, in various locations.

## Decisions
- Always create a NEW post per location, even for a brand that already has a post.
- Categories (taxonomy `portfolio_category`): always `architecture` (term 116, "ARCHITECTURE").
  Restaurants also get `qsr` ("QSR"), created automatically if missing. Other terms:
  `visualization` (119), `campaign` (117).
- Layout template: post 7178 (Pancheros). Project Name format for restaurants: "<Brand> QSR".
- Facebook and Instagram are skipped (they block automated access).
- Model: claude-opus-5-5 with server-side refusal fallbacks.

## WordPress facts
- Site: https://uniteideas.com, hosted on WP Engine, theme Bauen, built with Elementor.
- Post type `portfolio` is NOT in the REST API. Drafts are created with WP-CLI over the
  WP Engine SSH gateway: `ssh raindesigngrou@raindesigngrou.ssh.wpengine.net "wp ..."`.
  Sean's SSH key is set up and `wp option get siteurl` works.
- Media uploads use the REST API with an Application Password (works for attachments).
- Layout lives in `_elementor_data`. Write-up goes in the `bauen-text` widget; the
  `bauen-title` widget's `block-content` holds theme demo text that is not displayed.
  Year / Project Name / Location are in the `bauen-list` widget as `[span] Year : [/span] 2025`.
- Images use `bauen-single-img-video` widgets, two per row. In the template the first row is
  full size and later rows are cropped to 1920x1080. The featured image is the page banner.
- Windows ssh strips quotes like `'\n'` inside remote commands; avoid them.

## Dropbox
- Local root: `D:\Beyond Creative Dropbox\Sean Walker\_RPP CLIENTS\_SERVICE-CLIENTS`
- Year folders: `__UNITE_2024`, `__UNITE_2025`, `__UNITE_2026` (some contain `_ARCHIVE` subfolders).
- Job folders: `YYMMDD_CODE_City, ST`, e.g. `250907_RNR_Mansfield, TX`.
- New jobs come from `_NewClient_Template` with subfolders Proposals, _REFERENCE, PRESENTATIONS,
  RENDERS, FINALS, WEB, Invoices, POs (money folders are never read).

## Status at handoff
- All code written; 23 tests pass with fakes for Claude, Google, SSH and WordPress.
- Not yet run for real. Next steps: set up on Sean's PC per README.md, have Sean add the
  Anthropic key, Google Places key and WordPress Application Password to `.env` himself,
  run `python -m portfolio check`, then the first real job and fix whatever comes up.
- Unverified on the live server: `wp eval-file -` reading PHP from stdin, REST media upload
  auth, and how the Bauen header picks up the banner. Check these on the first run.
- Not done yet: All in One SEO fields; adding a QSR filter button to the Our Work page grid.
