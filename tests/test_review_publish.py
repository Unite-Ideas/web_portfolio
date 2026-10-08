import json
import shutil
import subprocess
from pathlib import Path

import pytest

from portfolio import pipeline, wordpress
from portfolio.config import Config
from portfolio.images import Candidate
from portfolio.review import create_app

TEMPLATE = json.loads((Path(__file__).parent / "fixtures" / "pancheros_elementor.json").read_text())


def make_cfg(tmp_path):
    return Config("", "claude-opus-5-5", "claude-haiku-5-5", "", "https://uniteideas.com", "u", "p", "raindesigngrou",
                  "raindesigngrou.ssh.wpengine.net", 7178, tmp_path, tmp_path / "jobs")


def make_job(tmp_path):
    job = pipeline.Job.create(make_cfg(tmp_path), "Rock N Roll Sushi", "Mansfield, TX")
    (job.dir / "images").mkdir()
    (job.dir / "thumbs").mkdir()
    cands = []
    for i, kind in enumerate(["exterior", "interior", "food_or_product"]):
        c = Candidate(key=f"k{i}", source="web", origin_url=f"u{i}", page_url="https://news.example.com/a",
                      file=f"images/k{i}.jpg", thumb=f"thumbs/k{i}.jpg", width=1600, height=1000,
                      review={"kind": kind, "alt_text": f"alt {i}", "people": "none", "quality": 4,
                              "matches_business": "yes", "shows_building": kind != "food_or_product",
                              "description": "d"},
                      score=10 - i if kind != "food_or_product" else 0, keep=kind != "food_or_product")
        (job.dir / c.file).write_bytes(b"jpg")
        (job.dir / c.thumb).write_bytes(b"jpg")
        cands.append(c)
    job.candidates = cands
    job.data["dropbox"] = {"folder": "", "documents": [], "images": []}
    job.data["research"] = {"facts": [{"fact": "Opened 2025", "source_url": "https://x"}], "organizations": []}
    job.data["draft"] = {"title": "Rock N Roll Sushi Mansfield", "slug": "rock-n-roll-sushi-mansfield",
                         "project_name": "Rock N Roll Sushi QSR", "location": "Mansfield, TX", "year": "2025",
                         "paragraphs": ["One.", "Two."], "excerpt": "e", "categories": ["architecture", "qsr"],
                         "review_notes": ["Check the opening date."]}
    job.save()
    return job


def test_review_page_and_save(tmp_path):
    cfg = make_cfg(tmp_path)
    job = make_job(tmp_path)
    client = create_app(cfg, job).test_client()
    page = client.get("/").get_data(as_text=True)
    assert "Rock N Roll Sushi Mansfield" in page and "Check the opening date." in page
    assert client.get("/files/thumbs/k0.jpg").status_code == 200
    assert client.get("/files/job.json").status_code == 404

    resp = client.post("/save", data={
        "action": "save", "title": "RNR Mansfield", "slug": "", "project_name": "RNR QSR",
        "location": "Mansfield, TX", "year": "2025", "excerpt": "x", "writeup": "Para one.\r\n\r\nPara two.",
        "categories": ["architecture", "qsr"], "use_k0": "1", "order_k0": "2", "use_k1": "1", "order_k1": "1",
        "banner": "k0", "alt_k1": "Dining room",
    })
    assert resp.status_code == 302
    saved = pipeline.Job.load(job.path).data["draft"]
    assert saved["slug"] == "rnr-mansfield"
    assert saved["paragraphs"] == ["Para one.", "Para two."]
    assert saved["image_order"] == ["k1", "k0"]
    assert saved["alt"]["k1"] == "Dining room"


def test_publish_builds_payload(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    job = make_job(tmp_path)
    job.data["draft"]["image_order"] = ["k1", "k0"]
    job.data["draft"]["banner"] = "k0"
    job.save()

    uploads = []

    def fake_upload(client, path, filename, title, alt, description):
        uploads.append((filename, alt, description))
        return {"id": 500 + len(uploads), "url": f"https://uniteideas.com/{filename}"}

    captured = {}
    monkeypatch.setattr(wordpress, "fetch_template", lambda cfg: TEMPLATE)
    monkeypatch.setattr(wordpress, "upload_image", fake_upload)
    monkeypatch.setattr(wordpress, "create_draft", lambda cfg, payload: captured.update(payload) or {"post_id": 9001})

    result = pipeline.publish(cfg, job, lambda m: None)
    assert result["post_id"] == 9001
    assert [u[0] for u in uploads] == ["rock-n-roll-sushi-mansfield-interior-1.jpg", "rock-n-roll-sushi-mansfield-exterior-2.jpg"]
    assert uploads[0][2] == "Source: https://news.example.com/a"
    assert captured["banner_id"] == 502  # k0 was uploaded second
    assert captured["attachment_ids"] == [501, 502]
    assert captured["categories"] == [{"slug": "architecture", "name": "ARCHITECTURE"}, {"slug": "qsr", "name": "QSR"}]
    layout = json.loads(captured["elementor_data"])
    assert "rock-n-roll-sushi-mansfield-interior-1.jpg" in captured["elementor_data"]
    assert layout[0]["elType"] == "section"

    # A second publish reuses the uploads instead of uploading again.
    pipeline.publish(cfg, job, lambda m: None)
    assert len(uploads) == 2


@pytest.mark.skipif(shutil.which("php") is None, reason="php not installed")
def test_publish_php_syntax(tmp_path):
    php = wordpress.PHP_SCRIPT.read_text().replace("__PAYLOAD__", "e30=")
    path = tmp_path / "p.php"
    path.write_text(php)
    result = subprocess.run(["php", "-l", str(path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(shutil.which("php") is None, reason="php not installed")
def test_publish_php_runs_against_stub(tmp_path):
    import base64

    layout = '[{"id":"a","settings":{"title":"Quote \\"here\\" and back\\\\slash"}}]'
    payload = {"template_id": 7178, "title": "RNR Mansfield", "slug": "rnr-mansfield", "excerpt": "e",
               "elementor_data": layout, "banner_id": 502, "attachment_ids": [501, 502],
               "categories": [{"slug": "architecture", "name": "ARCHITECTURE"}, {"slug": "qsr", "name": "QSR"}]}
    php = wordpress.PHP_SCRIPT.read_text().replace(
        "__PAYLOAD__", base64.b64encode(json.dumps(payload).encode()).decode()
    )
    script = tmp_path / "run.php"
    script.write_text(php)
    stub = Path(__file__).parent / "wp_stub.php"
    result = subprocess.run(["php", "-d", f"auto_prepend_file={stub}", str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout.strip())
    assert out["post_id"] == 9001 and "action=elementor" in out["edit_url"]

    state = json.loads(result.stderr)
    meta = state["meta"]
    assert meta["_elementor_data"] == [layout]  # stored exactly, slashes intact
    assert meta["_elementor_edit_mode"] == ["builder"]
    assert meta["bauen_page_header_selector_opt"] == ["static"]
    assert meta["bauen_wr_portfoliotype_container"] == [{"a": "b\\c"}]
    assert meta["bauen_page_full_img_header_bg_img"] == ["https://uniteideas.com/new-502.jpg"]
    assert meta["_thumbnail_id"] == [502]
    assert "_aioseo_title" not in meta and "_edit_lock" not in meta
    log = state["log"]
    assert ["new_term", "QSR"] in log
    assert ["terms", [116, 200], "portfolio_category"] in log
    assert sum(1 for entry in log if entry[0] == "update") == 2
