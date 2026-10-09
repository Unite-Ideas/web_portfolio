"""Test the settings, Dropbox folder, SSH and WordPress login.

Used by `python -m portfolio check` and by the Settings page."""

from __future__ import annotations

from . import wordpress
from .config import Config


def run_checks(cfg: Config) -> list[dict]:
    """One entry per check: {"name", "ok", "detail"}. Never shows key values."""
    results = []

    def add(name: str, ok: bool, detail: str) -> None:
        results.append({"name": name, "ok": ok, "detail": detail})

    missing = cfg.missing()
    add("Settings in .env", not missing, f"Missing: {', '.join(missing)}" if missing else "All required settings are filled in")

    if cfg.dropbox_clients_dir and cfg.dropbox_clients_dir.is_dir():
        years = sorted(p.name for p in cfg.dropbox_clients_dir.glob("__UNITE_*"))
        add("Dropbox folder", True, f"{cfg.dropbox_clients_dir} ({', '.join(years) or 'no __UNITE_ year folders'})")
    else:
        add("Dropbox folder", False, f"Not found: {cfg.dropbox_clients_dir}")

    add(
        "Claude",
        bool(cfg.anthropic_api_key),
        f"Research and write-up: {cfg.claude_model}. Photo check: {cfg.photo_model}"
        if cfg.anthropic_api_key
        else "ANTHROPIC_API_KEY is empty",
    )
    add(
        "Google Places",
        bool(cfg.google_maps_api_key),
        "Listing photos and addresses" if cfg.google_maps_api_key else "No key, so Google listing photos are skipped",
    )

    for name, test in [
        ("WP Engine SSH", lambda: f"WP-CLI answers for {wordpress.ssh(cfg, 'wp option get siteurl').strip()}"),
        ("Template layout", lambda: f"{len(wordpress.fetch_template(cfg))} sections in post {cfg.template_post_id}"),
        ("WordPress login", lambda: f"Logged in as {wordpress.check_rest(cfg)}"),
    ]:
        try:
            add(name, True, test())
        except Exception as exc:  # report the problem, keep checking the rest
            add(name, False, str(exc).strip() or exc.__class__.__name__)
    return results


def required_ok(results: list[dict]) -> bool:
    """Google Places is optional; everything else must pass."""
    return all(r["ok"] for r in results if r["name"] != "Google Places")
