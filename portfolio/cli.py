"""Command line entry point.

    python -m portfolio app          (Portfolio Studio in the browser)
    python -m portfolio shortcut     (put a Portfolio Studio shortcut on the desktop)
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


def make_shortcut() -> int:
    """Create "Portfolio Studio" on the desktop. It starts the studio with no console window."""
    import os
    import subprocess

    from .config import PROJECT_ROOT

    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if not pythonw.exists():
        print(f"Could not find {pythonw}. Run this from the project's .venv.")
        return 1
    # Paths go in through environment variables, so quotes and spaces in them cannot break the command.
    env = dict(os.environ, PS_TARGET=str(pythonw), PS_DIR=str(PROJECT_ROOT))
    script = (
        "$desk = [Environment]::GetFolderPath('Desktop');"
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $desk 'Portfolio Studio.lnk'));"
        "$s.TargetPath = $env:PS_TARGET; $s.Arguments = '-m portfolio app'; $s.WorkingDirectory = $env:PS_DIR;"
        "$s.Description = 'Unite Portfolio Studio'; $s.Save(); Write-Output (Join-Path $desk 'Portfolio Studio.lnk')"
    )
    result = subprocess.run(["powershell", "-NoProfile", "-Command", script], env=env, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Could not create the shortcut: {result.stderr.strip()}")
        return 1
    print(f"Shortcut created: {result.stdout.strip()}")
    return 0


def cmd_check(cfg: Config) -> int:
    from .checks import required_ok, run_checks

    results = run_checks(cfg)
    for r in results:
        if r["name"] == "Google Places" and not r["ok"]:
            print(f"Note: {r['detail']}")
        else:
            print(f"{r['name']} {'OK' if r['ok'] else 'FAILED'}: {r['detail']}")
    ok = required_ok(results)
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
    new.add_argument("--notes", help="Background for the research and write-up: other names, what made the project notable")
    new.add_argument("--title", help='Post title, if not "<business> - <city>"')
    new.add_argument("--max-photos", type=int, help="How many Dropbox photos to check (default 40)")
    new.add_argument("--no-browser", action="store_true", help="Do not open the review page automatically")

    review = sub.add_parser("review", help="Reopen the review page for an existing job")
    review.add_argument("job", help="Job folder name (or part of it)")
    review.add_argument("--no-browser", action="store_true")

    app = sub.add_parser("app", help="Open Portfolio Studio in the browser")
    app.add_argument("--no-browser", action="store_true")
    sub.add_parser("shortcut", help="Put a Portfolio Studio shortcut on the desktop")
    sub.add_parser("check", help="Test the settings, Dropbox folder, SSH and WordPress login")
    sub.add_parser("list", help="List jobs")

    args = parser.parse_args(argv)
    cfg = load_config()

    if args.command == "app":
        from .web import serve

        serve(cfg, open_browser=not args.no_browser)
        return

    if args.command == "shortcut":
        sys.exit(make_shortcut())

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
        # Saved with the job, so a later rerun keeps them unless they are given again.
        for key, value in (("notes", args.notes), ("title", args.title), ("max_photos", args.max_photos)):
            if value:
                job.data[key] = value
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
