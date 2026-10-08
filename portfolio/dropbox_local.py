"""Find a job's project folder in the local Dropbox and read what is in it.

Project folders live in year folders such as __UNITE_2025 and are named like
"250907_RNR_Mansfield, TX" or "251006_trinitychurch_scottsdale_az":
a YYMMDD date, a short client code and usually the city.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

DOC_EXTENSIONS = {".pdf", ".docx", ".pptx", ".txt", ".md"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".tif", ".tiff"}

# Folders that only hold money or admin paperwork. Never read them.
SKIP_DIRS = {
    "invoices",
    "invoice template",
    "manufacturer invoices",
    "pos",
    "po template",
    "registration",
    "sketchup",
    "document fonts",
}
# Folders most likely to describe the project. Read these first.
# Contracts and DOCUMENTS hold the scope of work, which is what the write-up needs most;
# drawing sheets (FINALS) say little in words, so they come late.
PRIORITY_DIRS = ["proposals", "contracts", "documents", "_reference", "presentations", "web", "finals", "renders"]

STOPWORDS = {"the", "and", "of", "a", "an", "inc", "llc", "co"}
STATE_NAMES = {
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga", "hi", "id", "il", "in", "ia",
    "ks", "ky", "la", "me", "md", "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj",
    "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc", "sd", "tn", "tx", "ut", "vt",
    "va", "wa", "wv", "wi", "wy",
}


@dataclass
class FolderMatch:
    path: Path
    score: float
    year: int | None


@dataclass
class ProjectDocs:
    folders: list[Path]
    documents: list[tuple[str, str]] = field(default_factory=list)  # (relative path, text)
    images: list[Path] = field(default_factory=list)
    picked_images: list[Path] = field(default_factory=list)  # from hand-picked folders


def tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", text.lower()) if t]


def split_city(city: str) -> tuple[list[str], str | None]:
    """'Mansfield, TX' -> (['mansfield'], 'tx')."""
    parts = tokens(city)
    state = parts[-1] if len(parts) > 1 and parts[-1] in STATE_NAMES else None
    city_words = parts[:-1] if state else parts
    return city_words, state


def business_codes(business: str) -> set[str]:
    """Short codes a folder might use, e.g. 'Rock N Roll Sushi' -> {'rnrs', 'rnr'}."""
    words = [w for w in tokens(business) if w not in STOPWORDS]
    codes = set()
    if len(words) >= 2:
        codes.add("".join(w[0] for w in words))
        codes.add("".join(w[0] for w in words[:-1]))
    codes.add("".join(words))
    return {c for c in codes if len(c) >= 2}


def folder_year(name: str, parent_name: str) -> int | None:
    m = re.match(r"(\d{2})(\d{2})(\d{2})", name)
    if m and 1 <= int(m.group(2)) <= 12:
        return 2000 + int(m.group(1))
    m = re.search(r"(20\d{2})", parent_name)
    return int(m.group(1)) if m else None


def score_folder(name: str, business: str, city: str) -> float:
    folder_tokens = tokens(name)
    joined = "".join(folder_tokens)
    token_set = set(folder_tokens)
    business_words = [w for w in tokens(business) if w not in STOPWORDS]
    city_words, state = split_city(city)

    score = 0.0
    for word in business_words:
        if word in token_set:
            score += 2
        elif len(word) >= 4 and word in joined:
            score += 1.5
    if token_set & business_codes(business) or "".join(business_words) in joined:
        score += 3
    if city_words and all(w in token_set or w in joined for w in city_words):
        score += 3
    if state and state in token_set:
        score += 1
    return score


def year_dirs(root: Path) -> list[Path]:
    return sorted((p for p in root.glob("__UNITE_*") if p.is_dir()), reverse=True)


def find_project_folders(root: Path, business: str, city: str, limit: int = 5) -> list[FolderMatch]:
    """Rank candidate project folders (including one archive level down)."""
    candidates: list[FolderMatch] = []
    for ydir in year_dirs(root):
        for child in ydir.iterdir():
            if not child.is_dir():
                continue
            children = [child]
            if "archive" in child.name.lower():
                children = [c for c in child.iterdir() if c.is_dir()]
            elif child.name.startswith("_"):
                continue  # brand reference and template folders such as "_REF - Rock N Roll Sushi"
            for folder in children:
                score = score_folder(folder.name, business, city)
                if score > 0:
                    candidates.append(FolderMatch(folder, score, folder_year(folder.name, ydir.name)))
    candidates.sort(key=lambda m: (m.score, m.year or 0), reverse=True)
    return candidates[:limit]


def _skip(path: Path, root: Path) -> bool:
    # Money paperwork is never read, whether it sits in its own folder or not.
    if "invoice" in path.name.lower():
        return True
    return any(part.lower() in SKIP_DIRS for part in path.relative_to(root).parts[:-1])


def _priority(path: Path, root: Path) -> int:
    # Leading underscores are ignored so "_FINALS" counts as "finals".
    parts = [p.lower().lstrip("_") for p in path.relative_to(root).parts[:-1]]
    for i, name in enumerate(PRIORITY_DIRS):
        if name.lstrip("_") in parts:
            return i
    return len(PRIORITY_DIRS)


def _in_renders(path: Path, root: Path) -> bool:
    return any("render" in p.lower() for p in path.relative_to(root).parts[:-1])


def extract_text(path: Path, max_chars: int = 15000) -> str:
    suffix = path.suffix.lower()
    text = ""
    try:
        if suffix == ".pdf":
            from pypdf import PdfReader

            reader = PdfReader(str(path))
            chunks = []
            for page in reader.pages[:40]:
                chunks.append(page.extract_text() or "")
                if sum(len(c) for c in chunks) > max_chars:
                    break
            text = "\n".join(chunks)
        elif suffix == ".docx":
            import docx

            text = "\n".join(p.text for p in docx.Document(str(path)).paragraphs)
        elif suffix == ".pptx":
            from pptx import Presentation

            lines = []
            for slide in Presentation(str(path)).slides:
                for shape in slide.shapes:
                    if getattr(shape, "has_text_frame", False):
                        lines.append(shape.text_frame.text)
            text = "\n".join(lines)
        elif suffix in {".txt", ".md"}:
            text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception as exc:  # unreadable or protected files are skipped, not fatal
        return f"[could not read: {exc.__class__.__name__}]"
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:max_chars]


def read_project(
    folders: Path | list[Path], max_docs: int = 25, max_total_chars: int = 80000, max_images: int = 40
) -> ProjectDocs:
    """Read one project folder, or several folders grouped as one project.

    Limits apply to the group as a whole. A file with the same name and size in two
    folders (a copied folder) is only read once. Folders after the first were picked
    by hand; their photos are listed in `picked_images`."""
    folders = [folders] if isinstance(folders, Path) else list(folders)
    result = ProjectDocs(folders=folders)
    docs, images = [], []  # (path, the folder it came from)
    seen = set()
    # Hand-picked folders are read first so a file they share with the main folder (for
    # example a subfolder of it) counts as hand-picked.
    for root in folders[1:] + folders[:1]:
        for path in root.rglob("*"):
            if not path.is_file() or _skip(path, root):
                continue
            suffix = path.suffix.lower()
            if suffix not in DOC_EXTENSIONS and suffix not in IMAGE_EXTENSIONS:
                continue
            size = path.stat().st_size
            if (path.name.lower(), size) in seen:
                continue
            seen.add((path.name.lower(), size))
            if suffix in DOC_EXTENSIONS:
                docs.append((path, root))
            # Skips icons and thumbnails without opening the file (opening makes Dropbox
            # download it). Low enough for compressed Facebook photos; images.py then drops
            # anything under 700x450.
            elif size > 50_000:
                images.append((path, root))

    def name(path: Path, root: Path) -> str:
        rel = path.relative_to(root).as_posix()
        return f"{root.name}/{rel}" if len(folders) > 1 else rel

    docs.sort(key=lambda d: (_priority(*d), -d[0].stat().st_mtime))
    total = 0
    for path, root in docs[:max_docs]:
        text = extract_text(path)
        if not text or text.startswith("[could not read"):
            continue
        text = text[: max(0, max_total_chars - total)]
        if not text:
            break
        result.documents.append((name(path, root), text))
        total += len(text)

    # Hand-picked photos come first, shared evenly between the picked folders so one big
    # folder of progress shots cannot crowd out a small folder of finished photos.
    by_folder = {root: [] for root in folders[1:]}
    for path, root in images:
        if root in by_folder:
            by_folder[root].append(path)
    queues = [sorted(paths, key=lambda p: -p.stat().st_size) for paths in by_folder.values()]
    picked = []
    while any(queues):
        for queue in queues:
            if queue:
                picked.append(queue.pop(0))
    # Then the main folder. Posts mostly use real photos and the photo check rejects renders
    # that were not picked by hand, so a RENDERS folder goes last; files are not always
    # tidied, so other folder names do not rank photos, and the biggest come first.
    main = sorted(
        ((p, r) for p, r in images if r not in by_folder),
        key=lambda d: (_in_renders(*d), -d[0].stat().st_size),
    )
    result.images = (picked + [p for p, _ in main])[:max_images]
    picked_set = set(picked)
    result.picked_images = [p for p in result.images if p in picked_set]
    return result
