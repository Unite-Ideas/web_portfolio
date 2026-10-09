"""Portfolio Studio: the local web app.

    python -m portfolio app

Home (start a project, pick Dropbox folders), a live progress page while a job runs,
the review page, and settings. Everything runs on this PC; jobs run in background
threads inside this process.
"""

from __future__ import annotations

import collections
import os
import re
import socket
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path

from flask import Flask, abort, jsonify, redirect, render_template, request, send_from_directory, url_for

from . import dropbox_local, pipeline
from .checks import required_ok, run_checks
from .config import PROJECT_ROOT, Config, load_config
from .pipeline import Job

PORT = 5055
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,120}$")
MODELS = [
    ("claude-sonnet-5-5", "Claude Sonnet 5.5"),
    ("claude-opus-5-5", "Claude Opus 5.5"),
    ("claude-haiku-5-5", "Claude Haiku 5.5"),
]
KIND_PLURALS = {"exterior": "exteriors", "interior": "interiors", "construction": "construction", "rendering": "renders"}
REDO_KEYS = ["dropbox", "place", "research", "research_notes", "research_sources", "candidates", "draft"]
STEPS = [
    ("dropbox", "Dropbox", "Reads the project folders: proposals, contracts and photos. Invoices are skipped."),
    ("place", "Google listing", "Finds the business on Google Maps for its address and photos."),
    ("research", "Research", "Searches the web for news, city approvals, developers and builders."),
    ("collect", "Collect photos", "Downloads every candidate photo and drops tiny ones and duplicates."),
    ("classify", "Photo check", "Sorts building photos from food, logos and marketing shots."),
    ("write", "Write-up", "Writes the post from the documents and research."),
]


# ---------------------------------------------------------------- running jobs


class Runner:
    """One job running in a background thread, plus what the progress page shows."""

    def __init__(self, cfg: Config, job: Job, folders: list[Path] | None):
        self.cfg = cfg
        self.job = job
        self.folders = folders
        self.status = "running"  # running, done, error
        self.error = ""
        self.log: collections.deque[str] = collections.deque(maxlen=200)
        self.photo_total: int | None = None
        self.photo_done = 0
        self.photo_kept = 0
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self._run, name=f"job-{job.data['slug']}", daemon=True)

    def start(self) -> "Runner":
        self.thread.start()
        return self

    def write_log(self, message: str) -> None:
        self.log.append(message)
        print(message, flush=True)

    def on_photo(self, cand) -> None:
        with self.lock:
            self.photo_done += 1
            if cand.score > 0:
                self.photo_kept += 1

    def _run(self) -> None:
        try:
            pipeline.gather(self.cfg, self.job, self.write_log, lambda matches: [], self.folders, self.on_photo)
            self.status = "done"
            self.write_log("Ready for review.")
        except Exception as exc:  # shown on the progress page
            self.status = "error"
            self.error = str(exc).strip() or exc.__class__.__name__
            self.write_log(f"Stopped: {self.error}")
            print(traceback.format_exc(), flush=True)


def step_states(data: dict, runner: Runner | None) -> list[dict]:
    """Each step's state (done, active, waiting, error) and a one-line detail."""
    cands = data.get("candidates")
    done = {
        "dropbox": "dropbox" in data,
        "place": "place" in data,
        "research": "research" in data,
        "collect": cands is not None,
        "classify": bool(cands) and all(c.get("review") for c in cands) or (cands == []),
        "write": "draft" in data,
    }
    running = runner is not None and runner.status == "running"
    failed = runner is not None and runner.status == "error"
    current = next((key for key, _, _ in STEPS if not done[key]), None)
    out = []
    for key, title, about in STEPS:
        if done[key]:
            state, detail = "done", step_detail(key, data)
        elif key == current and running:
            state, detail = "active", about
        elif key == current and failed:
            state, detail = "error", runner.error
        else:
            state, detail = "waiting", about
        out.append({"key": key, "title": title, "state": state, "detail": detail})
    return out


def step_detail(key: str, data: dict) -> str:
    if key == "dropbox":
        d = data.get("dropbox") or {}
        if not d.get("folder"):
            return "No Dropbox folder for this project."
        n = len(d.get("folders") or [d.get("folder")])
        return f"{len(d.get('documents', []))} documents and {len(d.get('images', []))} photos from {n} folder{'s' if n != 1 else ''}."
    if key == "place":
        p = data.get("place")
        if not p:
            return "No Google listing found in this city."
        return f"{p.get('name', '')}, {p.get('address', '')}. {len(p.get('photos', []))} photos."
    if key == "research":
        r = data.get("research") or {}
        return f"{len(r.get('facts', []))} facts, {len(r.get('photo_pages', []))} pages with photos."
    if key == "collect":
        return f"{len(data.get('candidates') or [])} photos to check after removing duplicates."
    if key == "classify":
        cands = data.get("candidates") or []
        kept = sum(1 for c in cands if c.get("score", 0) > 0)
        return f"{kept} building photos kept out of {len(cands)}."
    if key == "write":
        return f"Wrote \"{(data.get('draft') or {}).get('title', '')}\"."
    return ""


# ---------------------------------------------------------------- Dropbox folders


def folder_kind(parts: list[str], is_dir_name: str) -> dict:
    """How a folder shows in the picker. parts is its path below the Dropbox root."""
    name = is_dir_name
    depth = len(parts)
    low = name.lower()
    money = low in dropbox_local.SKIP_DIRS or "invoice" in low
    archive = "archive" in low and depth <= 2
    return {
        "name": name,
        "path": "/".join(parts),
        "openable": not money,
        "pickable": depth >= 2 and not money and not archive,
        "locked": money,
        "archive": archive,
        # At the year level, "_REF - ..." and "_FREQUENTLY SENT" are not jobs; inside a job, _REFERENCE is normal.
        "dim": depth == 2 and name.startswith(("_", "#")) and not archive,
    }


class Folders:
    """Read-only access to the Dropbox clients folder, never outside it."""

    def __init__(self, root: Path):
        self.root = root
        self._jobs: list[dict] | None = None
        self._jobs_at = 0.0

    def resolve(self, rel: str) -> Path | None:
        rel = (rel or "").replace("\\", "/").strip("/")
        if any(part in ("..", "") for part in rel.split("/")) and rel:
            return None
        path = (self.root / rel).resolve() if rel else self.root.resolve()
        root = self.root.resolve()
        if path != root and root not in path.parents:
            return None
        return path if path.is_dir() else None

    def children(self, rel: str) -> list[dict]:
        base = self.resolve(rel)
        if base is None:
            return []
        parts = [p for p in (rel or "").replace("\\", "/").strip("/").split("/") if p]
        try:
            dirs = [d.name for d in base.iterdir() if d.is_dir()]
        except OSError:
            return []
        if not parts:
            dirs = sorted((d for d in dirs if d.startswith("__UNITE_")), reverse=True)
        else:
            dirs.sort(key=lambda n: (not n.lower().startswith(("_archive", "archive")), n.lower()), reverse=False)
        return [folder_kind(parts + [d], d) for d in dirs]

    def jobs(self) -> list[dict]:
        """Every job folder (one level into each year, and inside archive folders). Cached for a minute."""
        if self._jobs is not None and time.time() - self._jobs_at < 60:
            return self._jobs
        out = []
        for year in sorted(self.root.glob("__UNITE_*"), reverse=True):
            if not year.is_dir():
                continue
            for child in year.iterdir():
                if not child.is_dir():
                    continue
                if "archive" in child.name.lower():
                    for job in child.iterdir():
                        if job.is_dir():
                            out.append({"name": job.name, "path": f"{year.name}/{child.name}/{job.name}", "where": f"{year.name} / {child.name}"})
                else:
                    out.append({"name": child.name, "path": f"{year.name}/{child.name}", "where": year.name})
        self._jobs, self._jobs_at = out, time.time()
        return out

    def search(self, query: str, limit: int = 40) -> list[dict]:
        words = dropbox_local.tokens(query)
        if not words:
            return []
        hits = []
        for j in self.jobs():
            hay = " ".join(dropbox_local.tokens(j["name"] + " " + j["where"]))
            if all(w in hay for w in words):
                hits.append({**folder_kind(j["path"].split("/"), j["name"]), "where": j["where"]})
        return hits[:limit]

    def matches(self, business: str, city: str, limit: int = 3) -> list[dict]:
        if not dropbox_local.tokens(business):
            return []
        root = self.root.resolve()
        out = []
        for m in dropbox_local.find_project_folders(self.root, business, city, limit=limit):
            rel = m.path.resolve().relative_to(root).as_posix()
            parts = rel.split("/")
            out.append({**folder_kind(parts, m.path.name), "where": " / ".join(parts[:-1]), "score": m.score})
        return out


def clear_winner(matches) -> bool:
    """Same rule as the command line: a strong match well ahead of the next one."""
    if not matches:
        return False
    best = matches[0]
    return best.score >= 5 and (len(matches) == 1 or best.score - matches[1].score >= 2)


# ---------------------------------------------------------------- the app


class Studio:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.runners: dict[str, Runner] = {}
        self.checks: dict = {"results": [], "at": None, "running": False}
        self.folders = Folders(cfg.dropbox_clients_dir)

    def reload(self) -> None:
        self.cfg = load_config()
        self.folders = Folders(self.cfg.dropbox_clients_dir)

    def run_checks_async(self) -> None:
        if self.checks["running"]:
            return
        self.checks["running"] = True

        def work():
            try:
                self.checks["results"] = run_checks(self.cfg)
            finally:
                self.checks["at"] = time.strftime("%H:%M")
                self.checks["running"] = False

        threading.Thread(target=work, daemon=True).start()

    def job_path(self, slug: str) -> Path:
        if not SLUG_RE.match(slug or ""):
            abort(404)
        path = self.cfg.jobs_dir / slug / "job.json"
        if not path.exists():
            abort(404)
        return path

    def load_job(self, slug: str) -> Job:
        runner = self.runners.get(slug)
        if runner and runner.status == "running":
            return runner.job
        return Job.load(self.job_path(slug))

    def all_jobs(self) -> list[dict]:
        rows = []
        for path in self.cfg.jobs_dir.glob("*/job.json"):
            slug = path.parent.name
            runner = self.runners.get(slug)
            try:
                data = runner.job.data if runner and runner.status == "running" else Job.load(path).data
            except (OSError, ValueError):
                continue
            rows.append((path.stat().st_mtime, slug, data, runner))
        rows.sort(key=lambda r: r[0], reverse=True)
        out = []
        for _, slug, data, runner in rows:
            cands = data.get("candidates") or []
            kept = [c for c in cands if c.get("keep") and c.get("thumb")] or [c for c in cands if c.get("score", 0) > 0 and c.get("thumb")]
            published = data.get("published") or []
            if runner and runner.status == "running":
                status, tone = "Running", "gold"
            elif runner and runner.status == "error":
                status, tone = "Stopped", "warn"
            elif published:
                status, tone = f"Draft {published[-1]['post_id']}", "ok"
            elif "draft" in data:
                status, tone = "Ready to review", "gold"
            else:
                status, tone = "Not finished", "muted"
            draft = data.get("draft") or {}
            out.append({
                "slug": slug,
                "title": draft.get("title") or f"{data.get('business', '')} - {data.get('city', '').split(',')[0]}",
                "business": data.get("business", ""),
                "city": data.get("city", ""),
                "status": status,
                "tone": tone,
                "thumb": url_for("job_file", slug=slug, name=kept[0]["thumb"]) if kept else "",
                "monogram": "".join(w[0] for w in dropbox_local.tokens(data.get("business", ""))[:3]).upper(),
                "url": url_for("job_page", slug=slug),
                "data": data,
            })
        return out


def update_env(env_path: Path, values: dict[str, str]) -> None:
    """Change only the named lines in .env; every other line (keys included) is left as it was."""
    text = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    for key, value in values.items():
        pattern = re.compile(rf"(?m)^{re.escape(key)}=.*$")
        if pattern.search(text):
            text = pattern.sub(f"{key}={value}", text)
        else:
            text = text.rstrip("\n") + f"\n{key}={value}\n"
    env_path.write_text(text, encoding="utf-8")


def create_app(cfg: Config, check_on_start: bool = True) -> Flask:
    app = Flask(__name__)
    studio = Studio(cfg)
    app.config["studio"] = studio

    @app.context_processor
    def globals_for_templates():
        results = studio.checks["results"]
        if studio.checks["running"] and not results:
            pill = ("Checking connections", "gold")
        elif not results:
            pill = ("Connections not checked", "muted")
        elif required_ok(results):
            pill = ("All systems go", "ok")
        else:
            pill = ("Needs attention", "warn")
        return {"pill": pill, "running_jobs": [s for s, r in studio.runners.items() if r.status == "running"]}

    # ---- home

    @app.get("/")
    def home():
        jobs = studio.all_jobs()
        last = next((j for j in jobs if j["data"].get("candidates")), None)
        last_info = None
        if last:
            cands = last["data"]["candidates"]
            building = [c for c in cands if c.get("score", 0) > 0]
            kinds = collections.Counter(c["review"].get("kind", "") for c in building)
            shown = [c for c in cands if c.get("keep") and c.get("thumb")][:4] or building[:4]
            last_info = {
                "title": last["title"],
                "url": last["url"],
                "checked": len(cands),
                "kept": len(building),
                "kinds": ", ".join(f"{n} {KIND_PLURALS.get(k, k)}" for k, n in kinds.most_common()),
                "thumbs": [url_for("job_file", slug=last["slug"], name=c["thumb"]) for c in shown],
            }
        return render_template(
            "home.html",
            nav="home",
            jobs=jobs[:6],
            drafts=sum(1 for j in jobs if j["data"].get("published")),
            last=last_info,
            checks=studio.checks,
            form=request.args,
            error=request.args.get("error", ""),
            open_picker=request.args.get("pick") == "1",
            today=time.strftime("%A, %B %d").replace(" 0", " "),
        )

    @app.post("/start")
    def start():
        f = request.form
        business, city = f.get("business", "").strip(), f.get("city", "").strip()
        keep = {k: f.get(k, "") for k in ("business", "city", "notes", "title", "max_photos")}

        def back(error: str, pick: bool = False):
            return redirect(url_for("home", error=error, pick="1" if pick else "", **keep))

        if not business or not city:
            return back("Type the business and the city first.")
        missing = studio.cfg.missing()
        if missing:
            return back(f"Missing settings in .env: {', '.join(missing)}. See Settings.")

        folders = []
        for rel in f.getlist("folders"):
            path = studio.folders.resolve(rel)
            if path is None:
                return back(f"Could not find the Dropbox folder {rel}. Pick it again.", pick=True)
            folders.append(path)

        job = Job.create(studio.cfg, business, city)
        slug = job.data["slug"]
        runner = studio.runners.get(slug)
        if runner and runner.status == "running":
            return redirect(url_for("job_page", slug=slug))
        start_over = f.get("start_over") == "1"
        if "draft" in job.data and not start_over:
            return redirect(url_for("review_page", slug=slug, message="This project was run before. To run it again, tick Start over under More options."))

        if not folders and ("dropbox" not in job.data or start_over):
            matches = dropbox_local.find_project_folders(studio.folders.root, business, city)
            if clear_winner(matches):
                folders = [matches[0].path]
            elif matches:
                return back("A few Dropbox folders could be this project. Pick the right one.", pick=True)

        if start_over:
            for key in REDO_KEYS:
                job.data.pop(key, None)
        for key in ("notes", "title"):
            value = f.get(key, "").strip()
            if value:
                job.data[key] = value
            elif start_over:
                job.data.pop(key, None)
        try:
            limit = int(f.get("max_photos") or 0)
        except ValueError:
            limit = 0
        if limit:
            job.data["max_photos"] = max(10, min(limit, 300))
        job.save()
        studio.runners[slug] = Runner(studio.cfg, job, folders or None).start()
        return redirect(url_for("job_page", slug=slug))

    # ---- folders

    @app.get("/api/folders")
    def api_folders():
        rel = request.args.get("path", "")
        if studio.folders.resolve(rel) is None:
            return jsonify({"error": "Folder not found", "items": []}), 404
        return jsonify({"items": studio.folders.children(rel)})

    @app.get("/api/folders/search")
    def api_folder_search():
        return jsonify({"items": studio.folders.search(request.args.get("q", ""))})

    @app.get("/api/folders/match")
    def api_folder_match():
        return jsonify({"items": studio.folders.matches(request.args.get("business", ""), request.args.get("city", ""))})

    # ---- a job: progress, then review

    @app.get("/jobs/<slug>")
    def job_page(slug: str):
        job = studio.load_job(slug)
        runner = studio.runners.get(slug)
        if (runner is None or runner.status == "done") and "draft" in job.data:
            return redirect(url_for("review_page", slug=slug))
        return render_template("progress.html", nav="jobs", job=job.data, slug=slug)

    @app.get("/api/jobs/<slug>/status")
    def job_status(slug: str):
        job = studio.load_job(slug)
        runner = studio.runners.get(slug)
        data = job.data
        steps = step_states(data, runner)
        photo = None
        cands = data.get("candidates")
        if runner is not None and cands is not None:
            if runner.photo_total is None:
                runner.photo_total = sum(1 for c in cands if not c.get("review"))
            total = runner.photo_total
            if total:
                photo = {"total": total, "done": min(runner.photo_done, total), "kept": runner.photo_kept,
                         "skipped": max(0, runner.photo_done - runner.photo_kept)}
        status = runner.status if runner else ("done" if "draft" in data else "idle")
        return jsonify({
            "status": status,
            "error": runner.error if runner else "",
            "steps": steps,
            "photo": photo,
            "log": list(runner.log)[-14:] if runner else [],
            "review_url": url_for("review_page", slug=slug) if "draft" in data else "",
        })

    @app.post("/jobs/<slug>/retry")
    def job_retry(slug: str):
        runner = studio.runners.get(slug)
        if runner and runner.status == "running":
            return redirect(url_for("job_page", slug=slug))
        job = Job.load(studio.job_path(slug))
        folders = runner.folders if runner else None
        studio.runners[slug] = Runner(studio.cfg, job, folders).start()
        return redirect(url_for("job_page", slug=slug))

    @app.get("/jobs/<slug>/review")
    def review_page(slug: str):
        job = studio.load_job(slug)
        if "draft" not in job.data:
            return redirect(url_for("job_page", slug=slug))
        draft = job.data["draft"]
        order = {k: i + 1 for i, k in enumerate(draft.get("image_order", []))}
        if not order:
            order = {c.key: i + 1 for i, c in enumerate(c for c in job.candidates if c.keep)}
        return render_template(
            "review.html",
            nav="jobs",
            slug=slug,
            job=job.data,
            draft=draft,
            writeup="\n\n".join(draft["paragraphs"]),
            candidates=job.candidates,
            order=order,
            banner=draft.get("banner") or next(iter(order), ""),
            alts=draft.get("alt", {}),
            message=request.args.get("message", ""),
            published=job.data.get("published", []),
            save_url=url_for("review_save", slug=slug),
            files_base=url_for("job_file", slug=slug, name="x")[:-1],
        )

    @app.post("/jobs/<slug>/save")
    def review_save(slug: str):
        from .review import save_form

        job = Job.load(studio.job_path(slug))
        save_form(job, request.form)
        if request.form.get("action") != "publish":
            return redirect(url_for("review_page", slug=slug, message="Saved."))
        try:
            result = pipeline.publish(studio.cfg, job, print)
        except Exception as exc:  # show the problem on the page instead of a stack trace
            return redirect(url_for("review_page", slug=slug, message=f"Creating the draft failed: {exc}"))
        return redirect(url_for("review_page", slug=slug, message=f"Draft created (post {result['post_id']})."))

    @app.get("/jobs/<slug>/files/<path:name>")
    def job_file(slug: str, name: str):
        if not (name.startswith("thumbs/") or name.startswith("images/")) or ".." in name:
            abort(404)
        return send_from_directory(studio.job_path(slug).parent, name)

    @app.get("/jobs")
    def jobs_page():
        return render_template("jobs.html", nav="jobs", jobs=studio.all_jobs())

    # ---- settings

    @app.get("/settings")
    def settings_page():
        c = studio.cfg
        return render_template(
            "settings.html",
            nav="settings",
            checks=studio.checks,
            cfg=c,
            models=MODELS,
            message=request.args.get("message", ""),
            env_exists=(PROJECT_ROOT / ".env").exists(),
        )

    @app.get("/api/checks")
    def api_checks():
        return jsonify({"running": studio.checks["running"], "at": studio.checks["at"], "results": studio.checks["results"]})

    @app.post("/settings/check")
    def settings_check():
        studio.run_checks_async()
        return redirect(url_for("settings_page"))

    @app.post("/settings/models")
    def settings_models():
        allowed = {m for m, _ in MODELS}
        main, photo = request.form.get("claude_model", ""), request.form.get("photo_model", "")
        if main not in allowed or photo not in allowed:
            return redirect(url_for("settings_page", message="Pick a model from the list."))
        update_env(PROJECT_ROOT / ".env", {"CLAUDE_MODEL": main, "CLAUDE_PHOTO_MODEL": photo})
        studio.reload()
        return redirect(url_for("settings_page", message="Models saved. New jobs use them."))

    @app.post("/settings/open-env")
    def settings_open_env():
        if sys.platform == "win32":
            subprocess.Popen(["notepad.exe", str(PROJECT_ROOT / ".env")])
        return redirect(url_for("settings_page", message="Opened .env in Notepad. Restart the studio after saving changes to keys."))

    @app.post("/quit")
    def quit_studio():
        threading.Timer(0.5, lambda: os._exit(0)).start()
        return render_template("quit.html", nav="")

    if check_on_start:
        studio.run_checks_async()
    return app


# ---------------------------------------------------------------- start it


def already_running(port: int = PORT) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def serve(cfg: Config | None = None, path: str = "/", open_browser: bool = True, port: int = PORT) -> None:
    """Start the studio (or, if it is already running, just open it) and open the browser."""
    url = f"http://127.0.0.1:{port}{path}"
    if already_running(port):
        print(f"Portfolio Studio is already running: {url}")
        if open_browser:
            webbrowser.open(url)
        return
    cfg = cfg or load_config()
    if sys.stdout is None or sys.stderr is None:  # started without a console (desktop shortcut)
        cfg.jobs_dir.mkdir(parents=True, exist_ok=True)
        log_file = open(cfg.jobs_dir / "studio.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = log_file
    app = create_app(cfg)
    print(f"Portfolio Studio: {url}  (close it from Settings, or press Ctrl+C here)", flush=True)
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
