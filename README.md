# Unite Ideas portfolio drafter

Give it a business and a city. It finds photos of the building and reads the project
folder in Dropbox. Then it writes a short post and creates a **draft** portfolio post on
uniteideas.com that matches the existing layout (the Pancheros post by default).

```
python -m portfolio new "Rock N Roll Sushi" "Mansfield, TX"
```

## What it does

1. **Dropbox.** Finds the project folder under `__UNITE_2024`, `__UNITE_2025` or `__UNITE_2026`.
   Folder names like `250907_RNR_Mansfield, TX` are matched by business name, initials and city.
   If the match is unclear, it asks you to pick. To group several folders as one project, enter
   their numbers separated by commas (for example `1,3`). Folders starting with `_` (such as
   `_REF - Rock N Roll Sushi`) are brand references, not jobs, and are not offered. It reads proposals, references and presentations
   (PDF, Word, PowerPoint, text) and collects the photos. Invoice, PO and registration folders are never read.
2. **Google listing.** Pulls the photos on the business's Google listing (up to 10).
3. **Research.** Claude searches the web for news coverage, city approvals, developers,
   builders and pages that show photos of the building. Social media is skipped.
4. **Photos.** Downloads every candidate, drops tiny images and duplicates, and strips
   EXIF/GPS data. Claude then sorts each photo: exterior, interior and construction photos
   are kept, while food, product, marketing and logo shots are filtered out. Photos without
   people rank higher.
5. **Write-up.** Claude writes one or two short paragraphs from the Dropbox documents and the
   research, plus the Year, Project Name and Location fields. Restaurants get the QSR category.
6. **Review page.** Opens in your browser. Tick photos, set their order, choose the banner,
   edit the text and alt text, then click **Create WordPress draft**.
7. **WordPress.** Uploads the chosen photos, then creates the draft over SSH with WP-CLI. The draft
   copies every theme and Elementor setting from the template post. Nothing is published.
   Open the draft in Elementor, check it and publish it yourself.

Each run is saved in `jobs/<business-city>/`. Running the same command again picks up where it
left off. Use `--redo photos` (or `dropbox`, `place`, `research`, `writeup`) to run a step again.

## One-time setup (Windows)

### 1. Install Python

Install Python 3.12 or newer from python.org and tick **Add python.exe to PATH**.

### 2. Get the code and install it

```powershell
cd $env:USERPROFILE
git clone https://github.com/Unite-Ideas/web_portfolio.git
cd web_portfolio
git checkout claude/determined-mccarthy-ndo1ty
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

If PowerShell refuses to run `Activate.ps1`, run
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once and try again.

### 3. Create your `.env` file

```powershell
copy .env.example .env
notepad .env
```

Fill in:

| Setting | Where to get it |
| --- | --- |
| `ANTHROPIC_API_KEY` | console.anthropic.com > API Keys > Create Key. Add a small credit balance under Billing. |
| `GOOGLE_MAPS_API_KEY` | See step 4. Optional: without it, Google listing photos are skipped. |
| `WP_USER` | Your WordPress username. |
| `WP_APP_PASSWORD` | WP Admin > Users > Profile > Application Passwords. Name it "portfolio tool" and click Add. Paste the password it shows (spaces are fine). |
| `DROPBOX_CLIENTS_DIR` | Already set to `D:\Beyond Creative Dropbox\Sean Walker\_RPP CLIENTS\_SERVICE-CLIENTS`. Change it if the folder moves. |

The SSH settings are already filled in for the `raindesigngrou` environment.

### 4. Google Places API key

1. Go to console.cloud.google.com and create a project (for example "Unite portfolio").
2. Open **APIs & Services > Library**, search for **Places API (New)** and click **Enable**.
   Google asks you to set up billing. The monthly free usage easily covers this tool.
3. Open **APIs & Services > Credentials > Create credentials > API key**.
4. Click the new key, and under **API restrictions** choose **Restrict key** and select **Places API (New)**.
5. Paste the key into `GOOGLE_MAPS_API_KEY`.

### 5. Check everything

```powershell
python -m portfolio check
```

This tests the Dropbox folder, SSH, reading the template layout, and the WordPress login.

## Everyday use

```powershell
cd $env:USERPROFILE\web_portfolio
.\.venv\Scripts\Activate.ps1
python -m portfolio new "Pancheros Mexican Grill" "Springfield, MO"
python -m portfolio new "Hurts Donut" "Frisco, TX" --folder "D:\...\__UNITE_2025\250301_HD_Frisco, TX"
python -m portfolio new "Hurts Donut" "Frisco, TX" --folder "D:\...\250301_HD_Frisco, TX" --folder "D:\...\HD renders"
python -m portfolio list
python -m portfolio review hurts-donut-frisco-tx
```

## About photo rights

Photos from Google listings and news sites belong to the people who took them. The review page
shows each photo's source and author, and the source is saved in each uploaded image's
description in the Media Library. Check that you can use a photo before publishing it.

## Costs

Each job makes one research session and one write-up request on Claude Sonnet (`CLAUDE_MODEL`),
plus one request per photo on Claude Haiku (`CLAUDE_PHOTO_MODEL`), which costs a fraction of a
cent per photo. A typical job costs well under a dollar. Google Places photo requests usually
fall inside Google's free monthly usage.

## Changing the template

New posts copy the layout of post `TEMPLATE_POST_ID` (7178, Pancheros). The first image row
copies that post's first row, and later rows copy its second row. Every photo is cropped to the
template's 1920x1080 shape (from the center), so the two photos in a row are always the same
height. With an odd number of photos, the last photo spans the full width. To use a different post as the model, change
`TEMPLATE_POST_ID` in `.env`.

## Development

```
pip install -e ".[dev]"
pytest
```
