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
- Post text calls the firm "Unite" or "we", never "Unite Ideas" (enforced in code too).
- Never name the owners, franchisees or operators (or their holding companies) in posts.
- Post title and header: "<Business> - <City>", e.g. "Rock N Roll Sushi - Oxford" (set in code).
- Categories (taxonomy `portfolio_category`) are by BUILDING TYPE, one per post (Sean's change,
  2026-10-09): MINISTRY (churches, camps, Christian schools, nonprofits), FOOD SERVICE (slug
  `food-service`, the old QSR term 639 renamed), HOSPITALITY (hotels), COMMERCIAL (everything
  else). ARCHITECTURE, VISUALIZATION and CAMPAIGN were retired; never recreate them. The script
  and the before-state are in `jobs/recategorize-2026-10/` (not in git).
- Layout template: post 7178 (Pancheros). Project Name format for restaurants: "<Brand> QSR".
- Facebook and Instagram are skipped (they block automated access).
- Models (Sean's choice, 2026-10-08, to cut cost): research and write-up on claude-sonnet-5-5
  with server-side refusal fallbacks (`CLAUDE_MODEL`); the photo check on claude-haiku-5-5
  (`CLAUDE_PHOTO_MODEL`), which has no server-side fallback, so none is sent.

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
  full size and later rows are cropped to 1920x1080. New posts apply that 1920x1080 crop to
  every row (Sean's choice, 2026-10-08) so paired photos match in height. An odd last photo
  spans the full width. The featured image is the page banner.
- Windows ssh strips quotes like `'\n'` inside remote commands; avoid them.

## Dropbox
- Local root: `D:\Beyond Creative Dropbox\Sean Walker\_RPP CLIENTS\_SERVICE-CLIENTS`
- Year folders: `__UNITE_2024`, `__UNITE_2025`, `__UNITE_2026` (some contain `_ARCHIVE` subfolders).
- Job folders: `YYMMDD_CODE_City, ST`, e.g. `250907_RNR_Mansfield, TX`.
- New jobs come from `_NewClient_Template` with subfolders Proposals, _REFERENCE, PRESENTATIONS,
  RENDERS, FINALS, WEB, Invoices, POs (money folders are never read).

## Portfolio Studio (the UI)
- Local Flask app in `portfolio/web.py`, templates in `portfolio/templates/` (base, home,
  progress, review, jobs, settings). Runs only on Sean's PC at 127.0.0.1:5055; Sean chose
  local-only (no cloud host, no WordPress plugin).
- Desktop shortcut "Portfolio Studio" runs `.venv\Scripts\pythonw.exe -m portfolio app`
  (no console; log in `jobs\studio.log`). A second launch just opens the browser.
- Look: "liquid glass, vaporwave dusk" (dark indigo, magenta/cyan glows, striped sun, slow
  neon grid), frosted panels, Oswald + Didact Gothic, Unite gold #C9AE8A.
- Jobs run in background threads; the progress page polls `/api/jobs/<slug>/status`.
- The folder picker only reads inside `DROPBOX_CLIENTS_DIR` (path checks in `Folders.resolve`).
- The WP Engine SSH gateway sometimes says "Failed to create shell" for back-to-back
  connections; `wordpress.ssh` waits and retries only on that message.

## Status
- In real use since 2026-10-08: drafts for Rock N Roll Sushi Mansfield and Oxford, Hurts Donut
  Hot Springs and Cross Pointe Dorms. Publishing, media upload and the banner all work.
- Not done yet: All in One SEO fields; adding a QSR filter button to the Our Work page grid;
  updating an existing post in place (the tool always creates a new draft).
