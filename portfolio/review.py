"""Saving the review form, and opening a job's review page in Portfolio Studio."""

from __future__ import annotations

from . import wordpress
from .config import Config
from .pipeline import Job


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in text.replace("\r\n", "\n").split("\n\n") if p.strip()]


def save_form(job: Job, form) -> None:
    draft = job.data["draft"]
    for field in ("title", "slug", "project_name", "location", "year", "excerpt"):
        if field in form:
            draft[field] = form[field].strip()
    draft["slug"] = wordpress.slugify(draft["slug"] or draft["title"])
    draft["paragraphs"] = _paragraphs(form.get("writeup", ""))
    draft["categories"] = form.getlist("categories") or ["architecture"]

    order = []
    for cand in job.candidates:
        if form.get(f"use_{cand.key}"):
            try:
                position = float(form.get(f"order_{cand.key}") or 999)
            except ValueError:
                position = 999
            order.append((position, -cand.score, cand.key))
    draft["image_order"] = [key for _, _, key in sorted(order)]
    draft["banner"] = form.get("banner", "")
    draft["alt"] = {c.key: form.get(f"alt_{c.key}", "").strip() for c in job.candidates if form.get(f"use_{c.key}")}

    selected = set(draft["image_order"])
    cands = job.candidates
    for c in cands:
        c.keep = c.key in selected
    job.candidates = cands
    job.save()


def serve(cfg: Config, job: Job, open_browser: bool = True) -> None:
    """Open this job's review page in Portfolio Studio (starting the studio if needed)."""
    from .web import serve as serve_studio

    serve_studio(cfg, path=f"/jobs/{job.data['slug']}/review", open_browser=open_browser)
