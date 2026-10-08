"""Pull candidate photo URLs out of news, developer and city web pages."""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

# Sites that block automated access or only hold marketing/food shots.
SKIP_DOMAINS = {
    "facebook.com",
    "instagram.com",
    "x.com",
    "twitter.com",
    "tiktok.com",
    "linkedin.com",
    "pinterest.com",
    "youtube.com",
    "doordash.com",
    "ubereats.com",
    "grubhub.com",
    "google.com",
}
SKIP_WORDS = re.compile(
    r"logo|icon|sprite|avatar|favicon|badge|banner-ad|placeholder|spacer|pixel|tracking|emoji|gravatar|1x1",
    re.I,
)
IMAGE_EXT = re.compile(r"\.(jpe?g|png|webp)(\?|$)", re.I)


def domain(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def skip_page(url: str) -> bool:
    host = domain(url)
    return any(host == d or host.endswith("." + d) for d in SKIP_DOMAINS)


def _best_from_srcset(srcset: str) -> str | None:
    best, best_w = None, -1
    for part in srcset.split(","):
        bits = part.strip().split()
        if not bits:
            continue
        width = 0
        if len(bits) > 1 and bits[1].endswith("w"):
            try:
                width = int(bits[1][:-1])
            except ValueError:
                width = 0
        if width >= best_w:
            best, best_w = bits[0], width
    return best


def extract_image_urls(html: str, page_url: str, limit: int = 15) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    found: list[tuple[str, bool]] = []  # (url, came from a meta tag)

    for prop in ("og:image", "og:image:url", "twitter:image"):
        for tag in soup.find_all("meta", attrs={"property": prop}) + soup.find_all("meta", attrs={"name": prop}):
            if tag.get("content"):
                found.append((tag["content"], True))

    scope = soup.find("article") or soup.find("main") or soup.body or soup
    for img in scope.find_all(["img", "source"]):
        url = None
        for attr in ("srcset", "data-srcset"):
            if img.get(attr):
                url = _best_from_srcset(img[attr])
                break
        if not url:
            for attr in ("data-src", "data-lazy-src", "data-original", "src"):
                if img.get(attr) and not img[attr].startswith("data:"):
                    url = img[attr]
                    break
        if not url:
            continue
        width = img.get("width")
        if width and width.isdigit() and int(width) < 300:
            continue
        found.append((url, False))

    results: list[str] = []
    seen = set()
    for url, from_meta in found:
        absolute = urljoin(page_url, url.strip())
        if not absolute.startswith("http") or SKIP_WORDS.search(absolute):
            continue
        if not IMAGE_EXT.search(absolute) and not from_meta:
            # Many CDNs omit the extension; keep only obvious image paths then.
            if not re.search(r"/(image|img|photo|media|uploads|wp-content)/", absolute, re.I):
                continue
        if absolute in seen:
            continue
        seen.add(absolute)
        results.append(absolute)
        if len(results) >= limit:
            break
    return results


def page_images(client: httpx.Client, page_url: str, limit: int = 15) -> list[str]:
    if skip_page(page_url):
        return []
    try:
        resp = client.get(page_url, headers={"Accept": "text/html,application/xhtml+xml"})
    except httpx.HTTPError:
        return []
    if resp.status_code != 200 or "html" not in resp.headers.get("content-type", ""):
        return []
    return extract_image_urls(resp.text, str(resp.url), limit=limit)
