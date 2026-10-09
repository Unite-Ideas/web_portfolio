import time

from portfolio import pipeline
from portfolio.config import Config
from portfolio.web import create_app


def make_tree(root):
    for rel in [
        "__UNITE_2025/_ARCHIVE 2025/250804_Pancheros_Lebanon, MO/Proposals",
        "__UNITE_2025/_ARCHIVE 2025/250804_Pancheros_Lebanon, MO/Invoices",
        "__UNITE_2025/250907_RNR_Mansfield, TX/RENDERS",
        "__UNITE_2026/_REF - Rock N Roll Sushi",
        "__UNITE_2026/260702_RNR Sushi_Woodbridge VA",
        "__UNITE_2026/260804_RNR Sushi_Farragut TN",
        "Not a year folder",
    ]:
        (root / rel).mkdir(parents=True)


def make_cfg(tmp_path):
    dropbox = tmp_path / "dropbox"
    make_tree(dropbox)
    return Config("key", "claude-sonnet-5-5", "claude-haiku-5-5", "", "https://uniteideas.com", "u", "p", "ssh-user",
                  "ssh.example.com", 7178, dropbox, tmp_path / "jobs")


def client_for(tmp_path):
    cfg = make_cfg(tmp_path)
    return cfg, create_app(cfg, check_on_start=False).test_client()


def test_home_and_pages_render(tmp_path):
    _, client = client_for(tmp_path)
    for url in ("/", "/jobs", "/settings"):
        resp = client.get(url)
        assert resp.status_code == 200, url
    assert "Draft the next project" in client.get("/").get_data(as_text=True)


def test_folder_browsing_stays_inside_dropbox(tmp_path):
    _, client = client_for(tmp_path)
    years = [i["name"] for i in client.get("/api/folders").get_json()["items"]]
    assert years == ["__UNITE_2026", "__UNITE_2025"]  # only year folders, newest first

    items = {i["name"]: i for i in client.get("/api/folders?path=__UNITE_2025").get_json()["items"]}
    assert items["_ARCHIVE 2025"]["archive"] and not items["_ARCHIVE 2025"]["pickable"]
    assert items["250907_RNR_Mansfield, TX"]["pickable"]

    inside = client.get("/api/folders?path=__UNITE_2025/_ARCHIVE 2025/250804_Pancheros_Lebanon, MO").get_json()["items"]
    by_name = {i["name"]: i for i in inside}
    assert by_name["Invoices"]["locked"] and not by_name["Invoices"]["pickable"]
    assert by_name["Proposals"]["pickable"]

    for bad in ("..", "../..", "__UNITE_2025/../..", "C:/Windows", "/etc"):
        assert client.get(f"/api/folders?path={bad}").status_code == 404, bad


def test_folder_search_and_matches(tmp_path):
    _, client = client_for(tmp_path)
    hits = client.get("/api/folders/search?q=pancheros lebanon").get_json()["items"]
    assert [h["name"] for h in hits] == ["250804_Pancheros_Lebanon, MO"]
    assert hits[0]["path"] == "__UNITE_2025/_ARCHIVE 2025/250804_Pancheros_Lebanon, MO"

    matches = client.get("/api/folders/match?business=Rock N Roll Sushi&city=Mansfield, TX").get_json()["items"]
    assert matches[0]["name"] == "250907_RNR_Mansfield, TX"
    assert all(not m["name"].startswith("_") for m in matches)


def test_start_runs_job_then_review(tmp_path, monkeypatch):
    cfg, client = client_for(tmp_path)
    seen = {}

    def fake_gather(cfg, job, log, choose, folders=None, on_photo=None):
        seen["folders"] = folders
        log("Reading Dropbox folder")
        job.data["dropbox"] = {"folder": str(folders[0]), "folders": [str(f) for f in folders], "documents": [], "images": []}
        job.data["place"] = None
        job.data["research"] = {"facts": [], "photo_pages": [], "organizations": []}
        job.data["candidates"] = []
        job.data["draft"] = {"title": "Pancheros - Lebanon", "slug": "pancheros-lebanon", "project_name": "Pancheros QSR",
                             "location": "Lebanon, MO", "year": "2025", "paragraphs": ["We designed it."],
                             "excerpt": "e", "categories": ["architecture", "qsr"], "review_notes": []}
        job.save()

    monkeypatch.setattr(pipeline, "gather", fake_gather)
    resp = client.post("/start", data={
        "business": "Pancheros Mexican Grill", "city": "Lebanon, MO", "notes": "Second Lebanon store",
        "folders": ["__UNITE_2025/_ARCHIVE 2025/250804_Pancheros_Lebanon, MO"],
    })
    assert resp.status_code == 302
    slug = resp.headers["Location"].rstrip("/").split("/")[-1]

    for _ in range(50):
        status = client.get(f"/api/jobs/{slug}/status").get_json()
        if status["status"] != "running":
            break
        time.sleep(0.05)
    assert status["status"] == "done"
    assert all(s["state"] == "done" for s in status["steps"])
    assert status["review_url"].endswith("/review")
    assert seen["folders"][0].name == "250804_Pancheros_Lebanon, MO"

    job = pipeline.Job.load(cfg.jobs_dir / slug / "job.json")
    assert job.data["notes"] == "Second Lebanon store"
    page = client.get(status["review_url"]).get_data(as_text=True)
    assert "Pancheros - Lebanon" in page and "We designed it." in page


def test_start_rejects_folders_outside_dropbox(tmp_path):
    _, client = client_for(tmp_path)
    resp = client.post("/start", data={"business": "X", "city": "Y, MO", "folders": ["../../Windows"]})
    assert resp.status_code == 302 and "error=" in resp.headers["Location"]


def test_start_asks_when_folder_is_unclear(tmp_path, monkeypatch):
    _, client = client_for(tmp_path)
    started = []
    monkeypatch.setattr(pipeline, "gather", lambda *a, **k: started.append(a))
    # Two equally good RNR Sushi folders in other cities: no clear winner, so it asks you to pick one.
    resp = client.post("/start", data={"business": "Rock N Roll Sushi", "city": "Springfield, MO"})
    assert resp.status_code == 302 and "pick=1" in resp.headers["Location"]
    assert not started
