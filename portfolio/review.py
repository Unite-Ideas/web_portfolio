"""Local review page: pick photos, edit the text, then create the WordPress draft."""

from __future__ import annotations

import threading
import webbrowser

from flask import Flask, abort, redirect, render_template, request, send_from_directory, url_for

from . import pipeline, wordpress
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


def create_app(cfg: Config, job: Job) -> Flask:
    app = Flask(__name__)

    @app.get("/")
    def index():
        draft = job.data["draft"]
        order = {k: i + 1 for i, k in enumerate(draft.get("image_order", []))}
        if not order:
            order = {c.key: i + 1 for i, c in enumerate(c for c in job.candidates if c.keep)}
        return render_template(
            "review.html",
            job=job.data,
            draft=draft,
            writeup="\n\n".join(draft["paragraphs"]),
            candidates=job.candidates,
            order=order,
            banner=draft.get("banner") or next(iter(order), ""),
            alts=draft.get("alt", {}),
            message=request.args.get("message", ""),
            published=job.data.get("published", []),
        )

    @app.get("/files/<path:name>")
    def files(name: str):
        if not (name.startswith("thumbs/") or name.startswith("images/")):
            abort(404)
        return send_from_directory(job.dir, name)

    @app.post("/save")
    def save():
        save_form(job, request.form)
        if request.form.get("action") != "publish":
            return redirect(url_for("index", message="Saved."))
        try:
            result = pipeline.publish(cfg, job, print)
        except Exception as exc:  # show the problem on the page instead of a stack trace
            return redirect(url_for("index", message=f"Publishing failed: {exc}"))
        return redirect(url_for("index", message=f"Draft created (post {result['post_id']})."))

    return app


def serve(cfg: Config, job: Job, port: int = 5055, open_browser: bool = True) -> None:
    app = create_app(cfg, job)
    url = f"http://127.0.0.1:{port}/"
    print(f"Review page: {url}  (press Ctrl+C here when you are done)")
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=port, debug=False)
