"""Run the whole gather pipeline with the network and Claude replaced by fakes."""

import io
import random

from PIL import Image

from portfolio import analysis, images, pipeline, places, scrape
from portfolio.config import Config
from portfolio.llm import ResearchResult


def jpeg(color, seed):
    """A distinct picture per seed: random light and dark blocks."""
    rng = random.Random(seed)
    img = Image.new("RGB", (1600, 1000), color)
    for x in range(0, 1600, 200):
        for y in range(0, 1000, 125):
            if rng.random() < 0.5:
                img.paste((0, 0, 0), (x, y, x + 200, y + 125))
    out = io.BytesIO()
    img.save(out, "JPEG")
    return out.getvalue()


def test_gather_end_to_end(tmp_path, monkeypatch):
    root = tmp_path / "dropbox"
    project = root / "__UNITE_2025" / "250907_RNR_Mansfield, TX"
    (project / "Proposals").mkdir(parents=True)
    (project / "FINALS").mkdir()
    (project / "Proposals" / "proposal.txt").write_text("Architecture for a new Rock N Roll Sushi in Mansfield.")
    (project / "FINALS" / "site.jpg").write_bytes(jpeg((90, 90, 90), 40) + b"\0" * 200_000)
    cfg = Config("k", "claude-opus-5-5", "claude-haiku-5-5", "gkey", "https://uniteideas.com", "u", "p", "u", "h", 7178, root, tmp_path / "jobs")

    place = places.Place("pid", "Rock N Roll Sushi", "123 Main St, Mansfield, TX", "", "https://maps.google.com/x")
    place.photos = [places.PlacePhoto("unused", "places/pid/photos/p1", "Jane Doe", place.maps_uri)]
    monkeypatch.setattr(places, "find_place", lambda key, b, c: place)
    research = {"address": "123 Main St", "status": "open", "opened": "2025", "facts": [],
                "organizations": [], "photo_pages": ["https://news.example.com/rnr", "https://facebook.com/x"],
                "uncertain": []}
    monkeypatch.setattr(analysis, "research_project", lambda *a, **k: (research, ResearchResult("notes", [])))
    monkeypatch.setattr(scrape, "page_images", lambda client, page: ["https://news.example.com/a.jpg", "https://news.example.com/food.jpg"])

    downloads = {
        "places.googleapis.com": jpeg((200, 50, 50), 100),
        "a.jpg": jpeg((50, 200, 50), 160),
        "food.jpg": jpeg((50, 50, 200), 220),
    }
    def fake_fetch(client, url, referer=""):
        return next(v for k, v in downloads.items() if k in url)
    monkeypatch.setattr(images, "fetch_bytes", fake_fetch)

    def fake_classify(claude, jpeg_bytes, business, city, context):
        r, g, b = Image.open(io.BytesIO(jpeg_bytes)).resize((1, 1)).getpixel((0, 0))
        kind = "food_or_product" if b > r and b > g else "exterior"  # the blue picture is the "food" shot
        fake_classify.calls += 1
        return {"kind": kind, "shows_building": kind == "exterior", "people": "none", "matches_business": "yes",
                "quality": 4, "description": "d", "alt_text": "a"}
    fake_classify.calls = 0
    monkeypatch.setattr(analysis, "classify_photo", fake_classify)
    seen_docs = {}
    def fake_write(claude, business, city, year, documents, research, notes=""):
        seen_docs["docs"], seen_docs["year"] = documents, year
        return {"title": "Rock N Roll Sushi Mansfield", "project_name": "Rock N Roll Sushi QSR", "location": "Mansfield, TX",
                "year": year, "paragraphs": ["Unite Ideas' design team drew the plans for Unite Ideas."],
                "excerpt": "e", "building_type": "food_service", "review_notes": []}
    monkeypatch.setattr(analysis, "write_post", fake_write)

    job = pipeline.Job.create(cfg, "Rock N Roll Sushi", "Mansfield, TX")
    from portfolio.cli import choose_folder
    pipeline.gather(cfg, job, lambda m: None, choose_folder)

    job = pipeline.Job.load(job.path)
    assert job.data["dropbox"]["folder"].endswith("250907_RNR_Mansfield, TX")
    assert seen_docs["year"] == "2025"
    assert seen_docs["docs"][0][0] == "Proposals/proposal.txt"
    assert "gkey" not in job.path.read_text()  # API key never stored
    assert job.data["draft"]["title"] == "Rock N Roll Sushi - Mansfield"
    assert job.data["draft"]["slug"] == "rock-n-roll-sushi-mansfield"
    assert job.data["draft"]["paragraphs"] == ["Unite's design team drew the plans for Unite."]
    sources = sorted(c.source for c in job.candidates)
    assert sources == ["dropbox", "google", "web", "web"]
    google = next(c for c in job.candidates if c.source == "google")
    assert google.credit == "Jane Doe"
    assert sum(c.keep for c in job.candidates) == 3
    assert job.data["draft"]["categories"] == ["food-service"]

    # Running again skips finished steps (no new Claude calls).
    calls = fake_classify.calls
    pipeline.gather(cfg, job, lambda m: None, choose_folder)
    assert fake_classify.calls == calls
