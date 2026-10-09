"""Gather everything for one job, then publish the reviewed result as a draft.

Each job lives in jobs/<slug>/ with a job.json file. Every step saves its
results there, so re-running a job skips the steps that already finished.
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import fields
from datetime import date
from pathlib import Path
from typing import Callable

from . import analysis, dropbox_local, images, places, scrape, wordpress
from .config import Config
from .elementor import LayoutContent, LayoutImage, build_layout, to_json
from .images import Candidate
from .llm import Claude

MAX_WEB_PAGES = 15
MAX_WEB_IMAGES = 40
MAX_DROPBOX_IMAGES = 40
SUGGESTED_PHOTOS = 8
# What the write-up step returns -> portfolio category slug.
BUILDING_TYPES = {"ministry": "ministry", "food_service": "food-service", "hospitality": "hospitality", "commercial": "commercial"}

Log = Callable[[str], None]


def max_photos(job: "Job") -> int:
    """How many Dropbox photos go to the photo check (--max-photos, default 40)."""
    return int(job.data.get("max_photos") or MAX_DROPBOX_IMAGES)


class Job:
    def __init__(self, path: Path, data: dict):
        self.path = path
        self.data = data

    @property
    def dir(self) -> Path:
        return self.path.parent

    @classmethod
    def create(cls, cfg: Config, business: str, city: str) -> "Job":
        slug = wordpress.slugify(f"{business} {city}")
        path = cfg.jobs_dir / slug / "job.json"
        if path.exists():
            return cls.load(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        job = cls(path, {"slug": slug, "business": business, "city": city, "created": date.today().isoformat()})
        job.save()
        return job

    @classmethod
    def load(cls, path: Path) -> "Job":
        return cls(path, json.loads(path.read_text(encoding="utf-8")))

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    @property
    def candidates(self) -> list[Candidate]:
        names = {f.name for f in fields(Candidate)}
        return [Candidate(**{k: v for k, v in c.items() if k in names}) for c in self.data.get("candidates", [])]

    @candidates.setter
    def candidates(self, value: list[Candidate]) -> None:
        self.data["candidates"] = [c.to_dict() for c in value]


# ---------------------------------------------------------------- gather


def step_dropbox(
    cfg: Config, job: Job, log: Log, choose: Callable[[list], list[Path]], folders: list[Path] | None
) -> None:
    if "dropbox" in job.data:
        return
    if not folders:
        matches = dropbox_local.find_project_folders(cfg.dropbox_clients_dir, job.data["business"], job.data["city"])
        folders = choose(matches)
    if not folders:
        log("No Dropbox project folder selected; continuing without project documents.")
        job.data["dropbox"] = {"folder": "", "folders": [], "year": None, "documents": [], "images": []}
        job.save()
        return
    for folder in folders:
        log(f"Reading Dropbox folder: {folder}")
    docs = dropbox_local.read_project(folders, max_images=max_photos(job))
    # The first folder chosen is the main one; its date gives the project year.
    year = dropbox_local.folder_year(folders[0].name, folders[0].parent.name)
    job.data["dropbox"] = {
        "folder": "; ".join(str(f) for f in folders),
        "folders": [str(f) for f in folders],
        "year": year,
        "documents": [{"name": n, "text": t} for n, t in docs.documents],
        "images": [str(p) for p in docs.images],
        "picked_images": [str(p) for p in docs.picked_images],
    }
    log(f"  {len(docs.documents)} documents, {len(docs.images)} photos")
    job.save()


def step_place(cfg: Config, job: Job, log: Log) -> None:
    if "place" in job.data:
        return
    if not cfg.google_maps_api_key:
        log("GOOGLE_MAPS_API_KEY not set; skipping Google listing photos.")
        job.data["place"] = None
        job.save()
        return
    log("Looking up the Google listing...")
    place = places.find_place(cfg.google_maps_api_key, job.data["business"], job.data["city"])
    if place is None:
        log(f"  No Google listing found in {job.data['city']}; skipping Google listing photos.")
        job.data["place"] = None
    else:
        log(f"  {place.name}, {place.address} ({len(place.photos)} photos)")
        job.data["place"] = {
            "id": place.id,
            "name": place.name,
            "address": place.address,
            "website": place.website,
            "maps_uri": place.maps_uri,
            # Store photo resource names only; the media URL contains the API key.
            "photos": [{"name": p.name, "credit": p.credit} for p in place.photos],
        }
    job.save()


def step_research(claude: Claude, job: Job, log: Log) -> None:
    if "research" in job.data:
        return
    log("Researching the project online (this can take a few minutes)...")
    address = (job.data.get("place") or {}).get("address", "")
    structured, raw = analysis.research_project(
        claude, job.data["business"], job.data["city"], address, notes=job.data.get("notes", "")
    )
    job.data["research"] = structured
    job.data["research_notes"] = raw.text
    job.data["research_sources"] = raw.sources
    log(f"  {len(structured['facts'])} facts, {len(structured['photo_pages'])} photo pages")
    job.save()


def step_collect(cfg: Config, job: Job, log: Log) -> None:
    if "candidates" in job.data:
        return
    log("Downloading candidate photos...")
    found: list[Candidate] = []
    with images.http_client() as client:
        jobs: list[tuple[Candidate, Callable[[], bytes | None]]] = []

        for photo in (job.data.get("place") or {}).get("photos", []):
            url = f"https://places.googleapis.com/v1/{photo['name']}/media?maxWidthPx=4800&key={cfg.google_maps_api_key}"
            cand = Candidate(
                key=images.candidate_key(photo["name"]),
                source="google",
                origin_url=photo["name"],
                page_url=job.data["place"].get("maps_uri", ""),
                credit=photo.get("credit", ""),
            )
            jobs.append((cand, lambda u=url: images.fetch_bytes(client, u)))

        picked = set(job.data.get("dropbox", {}).get("picked_images", []))
        for path in job.data.get("dropbox", {}).get("images", [])[: max_photos(job)]:
            cand = Candidate(key=images.candidate_key(path), source="dropbox", origin_url=path, picked=path in picked)
            jobs.append((cand, lambda p=path: Path(p).read_bytes()))

        research = job.data.get("research", {})
        pages = list(dict.fromkeys(research.get("photo_pages", []) + [s["url"] for s in job.data.get("research_sources", [])]))
        pages = [p for p in pages if not scrape.skip_page(p)][:MAX_WEB_PAGES]
        web_urls: list[tuple[str, str]] = []
        with ThreadPoolExecutor(max_workers=6) as pool:
            for page, urls in zip(pages, pool.map(lambda p: scrape.page_images(client, p), pages)):
                web_urls.extend((u, page) for u in urls)
        seen = set()
        for url, page in web_urls[: MAX_WEB_IMAGES * 2]:
            if url in seen:
                continue
            seen.add(url)
            cand = Candidate(key=images.candidate_key(url), source="web", origin_url=url, page_url=page)
            jobs.append((cand, lambda u=url, r=page: images.fetch_bytes(client, u, referer=r)))

        def load(item):
            cand, getter = item
            try:
                data = getter()
            except OSError:
                return None
            return cand if data and images.save_candidate(cand, data, job.dir) else None

        with ThreadPoolExecutor(max_workers=8) as pool:
            found = [c for c in pool.map(load, jobs) if c is not None]

    unique = images.drop_duplicates(found)
    web = [c for c in unique if c.source == "web"][:MAX_WEB_IMAGES]
    others = [c for c in unique if c.source != "web"]
    job.candidates = others + web
    log(f"  {len(found)} usable photos, {len(job.candidates)} after removing duplicates")
    job.save()


def step_classify(
    claude: Claude, job: Job, log: Log, on_photo: Callable[[Candidate], None] | None = None
) -> None:
    cands = job.candidates
    todo = [c for c in cands if not c.review]
    if not todo:
        return
    log(f"Checking {len(todo)} photos with Claude...")

    def judge(cand: Candidate) -> Candidate:
        context = {"google": "the business's Google listing", "dropbox": "the firm's own project folder"}.get(
            cand.source, f"web page {cand.page_url}"
        )
        if cand.picked:
            context = "a folder of this project's photos and renders that the firm picked by hand"
        try:
            cand.review = analysis.classify_photo(
                claude, images.analysis_jpeg(job.dir, cand), job.data["business"], job.data["city"], context
            )
        except Exception as exc:  # one bad photo should not stop the run
            cand.review = {"error": str(exc)}
        cand.score = analysis.photo_score(cand.review, allow_renders=cand.picked)
        if on_photo:
            on_photo(cand)
        return cand

    with ThreadPoolExecutor(max_workers=4) as pool:
        done = {c.key: c for c in pool.map(judge, todo)}
    cands = [done.get(c.key, c) for c in cands]

    ranked = sorted((c for c in cands if c.score > 0), key=lambda c: c.score, reverse=True)
    keep = {c.key for c in ranked[:SUGGESTED_PHOTOS]}
    for c in cands:
        c.keep = c.key in keep
    cands.sort(key=lambda c: c.score, reverse=True)
    job.candidates = cands
    log(f"  {len(ranked)} building photos found, {len(keep)} suggested")
    job.save()


def firm_name(text: str) -> str:
    """Posts call the firm "Unite", never "Unite Ideas"."""
    for old, new in (("Unite Ideas's", "Unite's"), ("Unite Ideas'", "Unite's"), ("Unite Ideas", "Unite")):
        text = text.replace(old, new)
    return text


def step_write(claude: Claude, job: Job, log: Log) -> None:
    if "draft" in job.data:
        return
    log("Writing the post...")
    dropbox = job.data.get("dropbox", {})
    year = dropbox.get("year")
    post = analysis.write_post(
        claude,
        job.data["business"],
        job.data["city"],
        str(year) if year else "",
        [(d["name"], d["text"]) for d in dropbox.get("documents", [])],
        job.data.get("research", {}),
        notes=job.data.get("notes", ""),
    )
    # One portfolio category per post, by building type.
    categories = [BUILDING_TYPES.get(post.get("building_type", ""), "commercial")]
    # Title format is "Rock N Roll Sushi - Oxford" unless --title gave one.
    title = job.data.get("title") or f"{job.data['business']} - {job.data['city'].split(',')[0].strip()}"
    job.data["draft"] = {
        "title": title,
        "slug": wordpress.slugify(title),
        "project_name": post["project_name"],
        "location": post["location"],
        "year": post["year"],
        "paragraphs": [firm_name(p) for p in post["paragraphs"]],
        "excerpt": firm_name(post["excerpt"]),
        "categories": categories,
        "review_notes": post["review_notes"],
    }
    job.save()


def gather(
    cfg: Config,
    job: Job,
    log: Log,
    choose: Callable[[list], list[Path]],
    folders: list[Path] | None = None,
    on_photo: Callable[[Candidate], None] | None = None,
) -> None:
    """Run every step that has not finished yet. `on_photo` is called as each photo is checked."""
    claude = Claude(cfg.anthropic_api_key, cfg.claude_model)
    photo_claude = Claude(cfg.anthropic_api_key, cfg.photo_model)
    step_dropbox(cfg, job, log, choose, folders)
    step_place(cfg, job, log)
    step_research(claude, job, log)
    step_collect(cfg, job, log)
    step_classify(photo_claude, job, log, on_photo)
    step_write(claude, job, log)


# ---------------------------------------------------------------- publish

# Portfolio categories by building type (Sean's change, 2026-10-09). The old ones (ARCHITECTURE,
# VISUALIZATION, CAMPAIGN, QSR) are gone from the site and must never be recreated.
CATEGORY_NAMES = {"ministry": "MINISTRY", "food-service": "FOOD SERVICE", "hospitality": "HOSPITALITY", "commercial": "COMMERCIAL"}
OLD_CATEGORIES = {"qsr": "food-service"}  # drafts saved before the change


def media_description(cand: Candidate) -> str:
    if cand.source == "dropbox":
        return "Source: Unite Ideas project files"
    parts = [f"Source: {cand.page_url or cand.origin_url}"]
    if cand.source == "google":
        parts = ["Source: Google Maps listing"]
    if cand.credit:
        parts.append(f"Photo: {cand.credit}")
    return " | ".join(parts)


def post_categories(draft: dict) -> list[str]:
    """The draft's categories that still exist on the site, with old ones mapped or dropped."""
    out = []
    for slug in draft.get("categories", []):
        slug = OLD_CATEGORIES.get(slug, slug)
        if slug in CATEGORY_NAMES and slug not in out:
            out.append(slug)
    return out


def publish(cfg: Config, job: Job, log: Log) -> dict:
    draft = job.data["draft"]
    by_key = {c.key: c for c in job.candidates}
    selected = [by_key[k] for k in draft.get("image_order", []) if k in by_key]
    if not selected:
        raise ValueError("No photos selected.")
    banner_key = draft.get("banner") or selected[0].key
    categories = post_categories(draft)
    if not categories:
        raise ValueError("Pick a category: Ministry, Food Service, Hospitality or Commercial.")

    log("Reading the template layout...")
    template = wordpress.fetch_template(cfg)

    uploaded = job.data.setdefault("uploaded", {})
    with wordpress.rest_client(cfg) as client:
        for n, cand in enumerate(selected, start=1):
            if cand.key in uploaded:
                continue
            kind = cand.review.get("kind", "photo")
            filename = f"{draft['slug']}-{kind}-{n}.jpg"
            alt = draft.get("alt", {}).get(cand.key) or cand.review.get("alt_text", "") or draft["title"]
            log(f"Uploading {filename}...")
            uploaded[cand.key] = wordpress.upload_image(
                client, job.dir / cand.file, filename, f"{draft['title']} {kind} {n}", alt, media_description(cand)
            )
            uploaded[cand.key]["alt"] = alt
            job.save()

    layout = build_layout(
        template,
        LayoutContent(
            title=draft["title"],
            paragraphs=draft["paragraphs"],
            year=str(draft["year"]),
            project_name=draft["project_name"],
            location=draft["location"],
            images=[LayoutImage(uploaded[c.key]["id"], uploaded[c.key]["url"], uploaded[c.key]["alt"]) for c in selected],
            rows=draft.get("layout_rows"),
        ),
    )
    payload = {
        "template_id": cfg.template_post_id,
        "title": draft["title"],
        "slug": draft["slug"],
        "excerpt": draft.get("excerpt", ""),
        "elementor_data": to_json(layout),
        "banner_id": uploaded.get(banner_key, uploaded[selected[0].key])["id"],
        "attachment_ids": [uploaded[c.key]["id"] for c in selected],
        "categories": [{"slug": s, "name": CATEGORY_NAMES[s]} for s in categories],
    }
    log("Creating the draft in WordPress...")
    result = wordpress.create_draft(cfg, payload)
    result["published_at"] = time.strftime("%Y-%m-%d %H:%M")
    job.data.setdefault("published", []).append(result)
    job.save()
    return result
