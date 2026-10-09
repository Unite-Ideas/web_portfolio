"""Build a new post's Elementor layout by copying the template post's layout.

The template (Pancheros by default) looks like this:

    top section
      column
        inner section: [title + text] | [Year / Project Name / Location list]
        inner section: image | image      <- first image row
        inner section: image | image      <- later rows (cropped 1920x1080)
        ...
    trailing empty container

We keep every setting from the template and only swap the text, the list values
and the images. The first image row copies the template's first row and every
later row copies the template's second row, so spacing matches. Every image,
first row included, gets the later rows' 1920x1080 crop so paired photos are
always the same height.
"""

from __future__ import annotations

import copy
import html
import json
import secrets
from dataclasses import dataclass
from typing import Any, Iterator

IMAGE_WIDGET = "bauen-single-img-video"
TITLE_WIDGET = "bauen-title"
TEXT_WIDGET = "bauen-text"
LIST_WIDGET = "bauen-list"


@dataclass
class LayoutImage:
    id: int
    url: str
    alt: str


@dataclass
class LayoutContent:
    title: str
    paragraphs: list[str]
    year: str
    project_name: str
    location: str
    images: list[LayoutImage]
    rows: list[int] | None = None  # photos per row (1 or 2), set on the review page


def valid_rows(rows, image_count: int) -> bool:
    """A row layout is usable when every row holds 1 or 2 photos and they add up to the photos picked."""
    return bool(rows) and all(n in (1, 2) for n in rows) and sum(rows) == image_count


def default_rows(image_count: int) -> list[int]:
    """Pairs side by side; an odd last photo gets a full-width row."""
    return [2] * (image_count // 2) + [1] * (image_count % 2)


class TemplateError(ValueError):
    pass


def walk(elements: list[dict]) -> Iterator[dict]:
    for el in elements:
        yield el
        yield from walk(el.get("elements", []))


def _widgets(el: dict, widget_type: str) -> list[dict]:
    return [e for e in walk([el]) if e.get("widgetType") == widget_type]


def _new_id(used: set[str]) -> str:
    while True:
        candidate = secrets.token_hex(4)[:7]
        if candidate not in used:
            used.add(candidate)
            return candidate


def _reassign_ids(el: dict, used: set[str]) -> None:
    """Give an element tree fresh Elementor ids so copies never collide."""
    for node in walk([el]):
        node["id"] = _new_id(used)
        for item in node.get("settings", {}).get("bauen_lists", []) or []:
            if isinstance(item, dict) and "_id" in item:
                item["_id"] = _new_id(used)


def _find_rows(top_section: dict) -> tuple[dict, dict, list[dict]]:
    """Return (container column, header inner section, image row sections)."""
    columns = [e for e in top_section.get("elements", []) if e.get("elType") == "column"]
    for column in columns:
        inner = [e for e in column.get("elements", []) if e.get("elType") == "section"]
        header = next((s for s in inner if _widgets(s, TITLE_WIDGET)), None)
        rows = [s for s in inner if _widgets(s, IMAGE_WIDGET)]
        if header is not None and rows:
            return column, header, rows
    raise TemplateError("Template layout has no title section followed by image rows.")


DEFAULT_CROP = {"image_size": "custom", "image_custom_dimension": {"width": "1920", "height": "1080"}}


def _crop_settings(template_rows: list[dict]) -> dict:
    """The crop the template uses on its later rows (1920x1080 in Pancheros)."""
    for row in template_rows:
        for widget in _widgets(row, IMAGE_WIDGET):
            settings = widget.get("settings", {})
            if settings.get("image_size") == "custom" and settings.get("image_custom_dimension"):
                return {k: copy.deepcopy(settings[k]) for k in ("image_size", "image_custom_dimension")}
    return copy.deepcopy(DEFAULT_CROP)


def _set_image(widget: dict, image: LayoutImage, index: int, crop: dict) -> None:
    settings = widget.setdefault("settings", {})
    # Every photo gets the same crop so the two photos in a row are the same height.
    settings.update(copy.deepcopy(crop))
    settings["image"] = {
        "url": image.url,
        "id": image.id,
        "alt": image.alt,
        "source": "library",
        "size": "",
    }
    settings["alt"] = f"gallery-{index}"


def _list_line(label: str, value: str) -> str:
    return f"[span] {label} : [/span] {value}"


def paragraphs_to_html(paragraphs: list[str]) -> str:
    return "".join(f"<p>{html.escape(p.strip())}</p>" for p in paragraphs if p.strip())


def build_layout(template: list[dict], content: LayoutContent) -> list[dict]:
    if not content.images:
        raise TemplateError("At least one image is required.")

    layout = copy.deepcopy(template)
    used = {node["id"] for node in walk(layout) if "id" in node}

    top = next((el for el in layout if _widgets(el, IMAGE_WIDGET)), None)
    if top is None:
        raise TemplateError("Template layout has no image widgets.")
    column, header, template_rows = _find_rows(top)

    # Header: title, write-up and the Year / Project Name / Location list.
    for widget in _widgets(header, TITLE_WIDGET):
        widget["settings"]["title"] = content.title
        # The template still carries theme demo text here; it is not shown
        # with this title style, but clear it so it never leaks.
        widget["settings"]["block-content"] = ""
    text_widgets = _widgets(header, TEXT_WIDGET)
    if text_widgets:
        text_widgets[0]["settings"]["block-content"] = paragraphs_to_html(content.paragraphs)
    for widget in _widgets(header, LIST_WIDGET):
        items = widget["settings"].get("bauen_lists", [])
        values = [
            ("Year", content.year),
            ("Project Name", content.project_name),
            ("Location", content.location),
        ]
        new_items = []
        for i, (label, value) in enumerate(values):
            item = copy.deepcopy(items[i]) if i < len(items) else {"_id": ""}
            item["title"] = _list_line(label, value)
            new_items.append(item)
        widget["settings"]["bauen_lists"] = new_items

    # Image rows: two images per row, or the rows chosen on the review page. A one-image row is full width.
    first_row_template = template_rows[0]
    later_row_template = template_rows[1] if len(template_rows) > 1 else template_rows[0]
    crop = _crop_settings(template_rows)
    new_rows = []
    rows = content.rows if valid_rows(content.rows, len(content.images)) else default_rows(len(content.images))
    pairs, start = [], 0
    for n in rows:
        pairs.append(content.images[start : start + n])
        start += n
    image_index = 0
    for row_number, pair in enumerate(pairs):
        row = copy.deepcopy(first_row_template if row_number == 0 else later_row_template)
        row_columns = [e for e in row.get("elements", []) if e.get("elType") == "column"]
        if len(pair) == 1 and len(row_columns) > 1:
            row["elements"] = [row_columns[0]]
            row_columns = [row_columns[0]]
            row_columns[0]["settings"]["_column_size"] = 100
            row["settings"]["structure"] = "10"
        for col, image in zip(row_columns, pair):
            widgets = _widgets(col, IMAGE_WIDGET)
            if not widgets:
                raise TemplateError("Template image row has a column without an image widget.")
            image_index += 1
            _set_image(widgets[0], image, image_index, crop)
        _reassign_ids(row, used)
        new_rows.append(row)

    # Replace the template rows in place, keeping anything that sits after them.
    is_row = lambda e: any(e is r for r in template_rows)  # noqa: E731
    elements = column["elements"]
    first_pos = next(i for i, e in enumerate(elements) if is_row(e))
    before = [e for e in elements[:first_pos] if not is_row(e)]
    after = [e for e in elements[first_pos:] if not is_row(e)]
    column["elements"] = before + new_rows + after
    return layout


def to_json(layout: list[dict]) -> str:
    """Serialize the way Elementor stores it (compact JSON)."""
    return json.dumps(layout, separators=(",", ":"), ensure_ascii=False)


def image_urls(layout: list[dict]) -> list[str]:
    return [
        w["settings"]["image"]["url"]
        for w in walk(layout)
        if w.get("widgetType") == IMAGE_WIDGET and "image" in w.get("settings", {})
    ]


def any_value(layout: list[dict], key: str) -> list[Any]:
    return [n["settings"][key] for n in walk(layout) if key in n.get("settings", {})]
