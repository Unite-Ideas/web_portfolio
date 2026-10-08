"""Download, normalize, de-duplicate and resize candidate photos."""

from __future__ import annotations

import hashlib
import io
from dataclasses import asdict, dataclass, field
from pathlib import Path

import httpx
from PIL import Image, ImageOps

try:  # iPhone photos in Dropbox are often HEIC
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:  # pragma: no cover - optional
    pass

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
MIN_WIDTH = 700
MIN_HEIGHT = 450
MAX_BYTES = 25_000_000
UPLOAD_LONG_EDGE = 2560
ANALYZE_LONG_EDGE = 1024
THUMB_LONG_EDGE = 480


@dataclass
class Candidate:
    """One photo the tool found, plus what Claude thinks of it."""

    key: str
    source: str  # "google", "web" or "dropbox"
    origin_url: str  # where the image file came from (or local path)
    page_url: str = ""  # page it appeared on
    credit: str = ""  # photographer / author, when known
    file: str = ""  # path of the full-size local copy, relative to the job folder
    thumb: str = ""
    width: int = 0
    height: int = 0
    dhash: str = ""
    review: dict = field(default_factory=dict)  # Claude's classification
    score: float = 0.0
    keep: bool = False  # suggested for the post

    def to_dict(self) -> dict:
        return asdict(self)


def candidate_key(origin: str) -> str:
    return hashlib.sha1(origin.encode("utf-8")).hexdigest()[:12]


def dhash(img: Image.Image, size: int = 8) -> str:
    """Difference hash: near-identical photos get nearly identical hashes."""
    gray = img.convert("L").resize((size + 1, size), Image.LANCZOS)
    pixels = gray.tobytes()
    bits = 0
    for row in range(size):
        for col in range(size):
            left = pixels[row * (size + 1) + col]
            right = pixels[row * (size + 1) + col + 1]
            bits = (bits << 1) | (left > right)
    return f"{bits:0{size * size // 4}x}"


def hamming(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def open_image(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "L"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGBA")
            background.paste(img, mask=img.split()[-1])
            img = background
        else:
            img = img.convert("RGB")
    return img.convert("RGB")


def jpeg_bytes(img: Image.Image, long_edge: int, quality: int = 85) -> bytes:
    """Resized JPEG with no EXIF/GPS data."""
    copy = img.copy()
    copy.thumbnail((long_edge, long_edge), Image.LANCZOS)
    out = io.BytesIO()
    copy.save(out, "JPEG", quality=quality, optimize=True, progressive=True)
    return out.getvalue()


def http_client() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept": "image/avif,image/webp,image/*,*/*;q=0.8"},
        follow_redirects=True,
        timeout=30,
    )


def fetch_bytes(client: httpx.Client, url: str, referer: str = "") -> bytes | None:
    try:
        headers = {"Referer": referer} if referer else {}
        resp = client.get(url, headers=headers)
        if resp.status_code != 200 or len(resp.content) > MAX_BYTES:
            return None
        if not resp.headers.get("content-type", "image/").startswith("image/"):
            return None
        return resp.content
    except httpx.HTTPError:
        return None


def save_candidate(cand: Candidate, data: bytes, job_dir: Path) -> bool:
    """Store full-size and thumbnail copies. Returns False if the image is unusable."""
    try:
        img = open_image(data)
    except Exception:
        return False
    if img.width < MIN_WIDTH or img.height < MIN_HEIGHT:
        return False
    (job_dir / "images").mkdir(parents=True, exist_ok=True)
    (job_dir / "thumbs").mkdir(parents=True, exist_ok=True)
    full = Path("images") / f"{cand.key}.jpg"
    thumb = Path("thumbs") / f"{cand.key}.jpg"
    (job_dir / full).write_bytes(jpeg_bytes(img, UPLOAD_LONG_EDGE, quality=90))
    (job_dir / thumb).write_bytes(jpeg_bytes(img, THUMB_LONG_EDGE, quality=80))
    cand.file, cand.thumb = full.as_posix(), thumb.as_posix()
    cand.width, cand.height = img.size
    cand.dhash = dhash(img)
    return True


def drop_duplicates(cands: list[Candidate], max_distance: int = 6) -> list[Candidate]:
    """Keep the largest copy of photos that look the same."""
    ordered = sorted(cands, key=lambda c: c.width * c.height, reverse=True)
    kept: list[Candidate] = []
    for cand in ordered:
        if all(hamming(cand.dhash, k.dhash) > max_distance for k in kept):
            kept.append(cand)
    return kept


def analysis_jpeg(job_dir: Path, cand: Candidate) -> bytes:
    img = Image.open(job_dir / cand.file)
    return jpeg_bytes(img, ANALYZE_LONG_EDGE, quality=80)
