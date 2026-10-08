"""Command line entry point.

    python -m portfolio new "Rock N Roll Sushi" "Mansfield, TX"
    python -m portfolio review rock-n-roll-sushi-mansfield-tx
    python -m portfolio check
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import pipeline, wordpress
from .config import Config, load_config
from .dropbox_local import FolderMatch


def log(message: str) -> None:
    print(message, flush=True)


def parse_folder_choice(answer: str, matches: list[FolderMatch]) -> list[Path] | None:
    """'2' or '1,3' or '1 3' -> those folders; '0' -> none; a pasted path -> that folder.
    Returns None when the answer is not valid."""
    answer = answer.strip().strip('"')
    numbers = answer.replace(",", " ").split()
    if numbers and all(n.isdigit() for n in numbers):
        picks = [int(n) for n in numbers]
        if picks == [0]:
            return []
        if all(1 <= n <= len(matches) for n in picks):
            return [matches[n - 1].path for n in dict.fromkeys(picks)]
        return None
    if answer and Path(answer).is_dir():
        return [Path(answer)]
    return None


def choose_folder(matches: list[FolderMatch]) -> list[Path]:
    """Ask which Dropbox folder (or folders) belong to the job when the best match is not clear."""
    if not matches:
        print("No matching Dropbox project folder found.")
        answer = input("Paste the folder path, or press Enter to continue without one: ").strip().strip('"')
        return [Path(answer)] if answer else []
    best = matches[0]
    clear_winner = len(matches) == 1 or best.score - matches[1].score >= 2
    if clear_winner and best.score >= 5:
        print(f"Dropbox folder: {best.path}")
        return [best.path]
    print("Which Dropbox folder is this job? To group several, separate the numbers with commas (e.g. 1,3).")
    for i, m in enumerate(matches, start=1):
        print(f"  {i}. {m.path.parent.name}/{m.path.name}")
    print("  0. None of these")
    while True:
        picked = parse_folder_choice(input("Number(s) (or paste a path): "), matches)
        if picked is not None:
            return picked


def find_job(cfg: Config, name: str) -> pipeline.Job:
    path = cfg.jobs_dir / name / "job.json"
    if not path.exists():
        matches = sorted(cfg.jobs_dir.glob(f"*{wordpress.slugify(name)}*/job.json"))
        if len(matches) != 1:
            known = ", ".join(p.parent.name for p in sorted(cfg.jobs_dir.glob("*/job.json"))) or "none"
            sys.exit(f"No single job matches '{name}'. Jobs: {known}")
        path = matches[0]
    return pipeline.Job.load(path)


def cmd_check(cfg: Config) -> int:
    ok = True
    missing = cfg.missing()
    if missing:
        ok = False
        print(f"Missing settings in .env: {', '.join(missing)}")
    if not cfg.google_maps_api_key:
        print("Note: GOOGLE_MAPS_API_KEY is empty, so Google listing photos will be skipped.")
    if cfg.dropbox_clients_dir and cfg.dropbox_clients_dir.is_dir():
        years = [p.name for p in cfg.dropbox_clients_dir.glob("__UNITE_*")]
        print(f"Dropbox folder OK ({', '.join(sorted(years)) or 'no __UNITE_ year folders'})")
    else:
        ok = False
        print(f"Dropbox folder not found: {cfg.dropbox_clients_dir}")
    for name, test in [
        ("SSH / WP-CLI", lambda: wordpress.ssh(cfg, "wp option get siteurl").strip()),
        ("Template layout", lambda: f"{len(wordpress.fetch_template(cfg))} top-level sections in post {cfg.template_post_id}"),
        ("REST API login", lambda: f"logged in as {wordpress.check_rest(cfg)}"),
    ]:
        try:
            print(f"{name} OK: {test()}")
        except Exception as exc:
            ok = False
            print(f"{name} FAILED: {exc}")
    print("All checks passed." if ok else "Fix the items above, then run check again.")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="portfolio", description="Draft Unite Ideas portfolio posts.")
    sub = parser.add_subparsers(dest="command", required=True)

    new = sub.add_parser("new", help="Research a job and open the review page")
    new.add_argument("business", help='Business name, e.g. "Rock N Roll Sushi"')
    new.add_argument("city", help='City and state, e.g. "Mansfield, TX"')
    new.add_argument("--folder", type=Path, action="append", default=[],
                     help="Dropbox project folder, if the automatic match is wrong (repeat to group several)")
    new.add_argument("--redo", action="append", default=[], choices=["dropbox", "place", "research", "photos", "writeup"],
                     help="Run a step again even if it already finished (repeatable)")
    new.add_argument("--no-browser", action="store_true", help="Do not open the review page automatically")

    review = sub.add_parser("review", help="Reopen the review page for an existing job")
    review.add_argument("job", help="Job folder name (or part of it)")
    review.add_argument("--no-browser", action="store_true")

    sub.add_parser("check", help="Test the settings, Dropbox folder, SSH and WordPress login")
    sub.add_parser("list", help="List jobs")

    args = parser.parse_args(argv)
    cfg = load_config()

    if args.command == "check":
        sys.exit(cmd_check(cfg))

    if args.command == "list":
        for path in sorted(cfg.jobs_dir.glob("*/job.json")):
            job = pipeline.Job.load(path)
            drafts = ", ".join(str(p["post_id"]) for p in job.data.get("published", [])) or "no draft yet"
            print(f"{path.parent.name}: {job.data['business']}, {job.data['city']} ({drafts})")
        return

    if args.command == "new":
        missing = cfg.missing()
        if missing:
            sys.exit(f"Missing settings in .env: {', '.join(missing)}. Run 'python -m portfolio check'.")
        job = pipeline.Job.create(cfg, args.business, args.city)
        redo_keys = {
            "dropbox": ["dropbox"],
            "place": ["place"],
            "research": ["research", "research_notes", "research_sources"],
            "photos": ["candidates"],
            "writeup": ["draft"],
        }
        for step in args.redo:
            for key in redo_keys[step]:
                job.data.pop(key, None)
        job.save()
        log(f"Job folder: {job.dir}")
        pipeline.gather(cfg, job, log, choose_folder, args.folder)
        from .review import serve

        serve(cfg, job, open_browser=not args.no_browser)
        return

    if args.command == "review":
        job = find_job(cfg, args.job)
        if "draft" not in job.data:
            sys.exit("This job has not finished gathering yet. Run the 'new' command again to resume it.")
        from .review import serve

        serve(cfg, job, open_browser=not args.no_browser)
