"""Talk to uniteideas.com: media uploads over the REST API, drafts over WP-CLI (SSH)."""

from __future__ import annotations

import base64
import json
import re
import subprocess
from pathlib import Path

import httpx

from .config import Config

PHP_SCRIPT = Path(__file__).with_name("publish.php")


class WordPressError(RuntimeError):
    pass


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


# ---------------------------------------------------------------- SSH / WP-CLI


def ssh(cfg: Config, command: str, stdin: str | None = None, timeout: int = 300) -> str:
    """Run a command on the WP Engine SSH gateway and return stdout."""
    result = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", cfg.ssh_target, command],
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
    )
    if result.returncode != 0:
        raise WordPressError(f"SSH command failed ({command}):\n{result.stderr.strip() or result.stdout.strip()}")
    return result.stdout


def fetch_template(cfg: Config) -> list[dict]:
    raw = ssh(cfg, f"wp post meta get {cfg.template_post_id} _elementor_data")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise WordPressError(f"Template post {cfg.template_post_id} has no readable Elementor layout.") from exc


def create_draft(cfg: Config, payload: dict) -> dict:
    """Create the draft portfolio post. Returns {post_id, edit_url, preview_url}."""
    encoded = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
    php = PHP_SCRIPT.read_text(encoding="utf-8").replace("__PAYLOAD__", encoded)
    out = ssh(cfg, "wp eval-file -", stdin=php)
    for line in reversed(out.strip().splitlines()):
        if line.startswith("{"):
            return json.loads(line)
    raise WordPressError(f"Unexpected WP-CLI output:\n{out}")


# ---------------------------------------------------------------- REST API


def rest_client(cfg: Config) -> httpx.Client:
    return httpx.Client(
        base_url=f"{cfg.wp_url}/wp-json/wp/v2",
        auth=(cfg.wp_user, cfg.wp_app_password.replace(" ", "")),
        timeout=120,
        headers={"User-Agent": "unite-portfolio-tool/0.1"},
    )


def check_rest(cfg: Config) -> str:
    with rest_client(cfg) as client:
        resp = client.get("/users/me", params={"context": "edit"})
        if resp.status_code != 200:
            raise WordPressError(f"REST login failed ({resp.status_code}): {resp.text[:300]}")
        return resp.json().get("name", "")


def upload_image(client: httpx.Client, path: Path, filename: str, title: str, alt: str, description: str) -> dict:
    resp = client.post(
        "/media",
        content=path.read_bytes(),
        headers={
            "Content-Type": "image/jpeg",
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
    if resp.status_code not in (200, 201):
        raise WordPressError(f"Upload of {filename} failed ({resp.status_code}): {resp.text[:300]}")
    media = resp.json()
    resp = client.post(
        f"/media/{media['id']}",
        json={"title": title, "alt_text": alt, "description": description},
    )
    if resp.status_code != 200:
        raise WordPressError(f"Could not set details on media {media['id']}: {resp.text[:300]}")
    media = resp.json()
    return {"id": media["id"], "url": media["source_url"]}
