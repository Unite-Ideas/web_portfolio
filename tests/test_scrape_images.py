import io

from PIL import Image

from portfolio import images
from portfolio.images import Candidate
from portfolio.scrape import extract_image_urls, skip_page

HTML = """
<html><head><meta property="og:image" content="https://news.example.com/cdn/abc123"></head>
<body><header><img src="/logo.png"></header>
<article>
  <img src="/uploads/2025/09/rnr-exterior.jpg" width="1200">
  <img srcset="/img/a-400.jpg 400w, /img/a-1600.jpg 1600w">
  <img data-src="https://cdn.example.com/photos/interior.webp">
  <img src="/uploads/tiny.jpg" width="50">
  <img src="data:image/gif;base64,AAAA">
</article></body></html>
"""


def test_extract_image_urls():
    urls = extract_image_urls(HTML, "https://news.example.com/story")
    assert urls == [
        "https://news.example.com/cdn/abc123",
        "https://news.example.com/uploads/2025/09/rnr-exterior.jpg",
        "https://news.example.com/img/a-1600.jpg",
        "https://cdn.example.com/photos/interior.webp",
    ]


def test_skip_social():
    assert skip_page("https://www.facebook.com/rnrsushi/photos")
    assert not skip_page("https://www.star-telegram.com/news/local/article.html")


def jpeg(color, size=(1600, 1000), pattern=False):
    img = Image.new("RGB", size, color)
    if pattern:
        for x in range(0, size[0], 100):
            img.paste((0, 0, 0), (x, 0, x + 50, size[1]))
    out = io.BytesIO()
    img.save(out, "JPEG")
    return out.getvalue()


def test_save_and_dedupe(tmp_path):
    a = Candidate(key="a", source="web", origin_url="a")
    b = Candidate(key="b", source="web", origin_url="b")
    c = Candidate(key="c", source="web", origin_url="c")
    small = Candidate(key="s", source="web", origin_url="s")
    assert images.save_candidate(a, jpeg((200, 100, 50), pattern=True), tmp_path)
    assert images.save_candidate(b, jpeg((200, 100, 50), (800, 500), pattern=True), tmp_path)
    assert images.save_candidate(c, jpeg((20, 120, 250)), tmp_path)
    assert not images.save_candidate(small, jpeg((1, 2, 3), (300, 200)), tmp_path)
    assert (tmp_path / a.file).exists() and (tmp_path / a.thumb).exists()
    kept = images.drop_duplicates([b, a, c])
    assert [k.key for k in kept] == ["a", "c"]  # larger copy of the duplicate wins


def test_saved_jpeg_has_no_exif(tmp_path):
    img = Image.new("RGB", (1600, 1000), (10, 10, 10))
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"
    out = io.BytesIO()
    img.save(out, "JPEG", exif=exif)
    cand = Candidate(key="e", source="dropbox", origin_url="e")
    assert images.save_candidate(cand, out.getvalue(), tmp_path)
    assert not Image.open(tmp_path / cand.file).getexif()
