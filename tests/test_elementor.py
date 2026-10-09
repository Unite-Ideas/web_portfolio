import json
from pathlib import Path

import pytest

from portfolio.elementor import (
    IMAGE_WIDGET,
    LayoutContent,
    LayoutImage,
    TemplateError,
    any_value,
    build_layout,
    image_urls,
    to_json,
    walk,
)

TEMPLATE = json.loads((Path(__file__).parent / "fixtures" / "pancheros_elementor.json").read_text())


def content(n_images):
    return LayoutContent(
        title="Rock N Roll Sushi Mansfield",
        paragraphs=["First paragraph & more.", "Second paragraph."],
        year="2025",
        project_name="Rock N Roll Sushi QSR",
        location="Mansfield, TX",
        images=[LayoutImage(100 + i, f"https://uniteideas.com/img{i}.jpg", f"Alt {i}") for i in range(n_images)],
    )


def image_rows(layout):
    column = layout[0]["elements"][0]
    return [s for s in column["elements"] if any(w.get("widgetType") == IMAGE_WIDGET for w in walk([s]))]


def test_header_text_and_list():
    layout = build_layout(TEMPLATE, content(4))
    assert any_value(layout, "title") == ["Rock N Roll Sushi Mansfield"]
    blocks = any_value(layout, "block-content")
    assert "<p>First paragraph &amp; more.</p><p>Second paragraph.</p>" in blocks
    assert not any("lorem" in b for b in blocks)
    lists = any_value(layout, "bauen_lists")[0]
    assert [i["title"] for i in lists] == [
        "[span] Year : [/span] 2025",
        "[span] Project Name : [/span] Rock N Roll Sushi QSR",
        "[span] Location : [/span] Mansfield, TX",
    ]


def test_images_in_order_two_per_row():
    layout = build_layout(TEMPLATE, content(6))
    assert image_urls(layout) == [f"https://uniteideas.com/img{i}.jpg" for i in range(6)]
    rows = image_rows(layout)
    assert len(rows) == 3
    # Every row, the first one included, uses the template's 1920x1080 crop so the
    # two photos in a row are always the same height.
    for row in rows:
        for w in walk([row]):
            if w.get("widgetType") == IMAGE_WIDGET:
                assert w["settings"]["image_size"] == "custom"
                assert w["settings"]["image_custom_dimension"] == {"width": "1920", "height": "1080"}
    first = [w for w in walk([rows[0]]) if w.get("widgetType") == IMAGE_WIDGET]
    widget = first[0]["settings"]["image"]
    assert widget == {"url": "https://uniteideas.com/img0.jpg", "id": 100, "alt": "Alt 0", "source": "library", "size": ""}


def test_odd_count_last_image_full_width():
    layout = build_layout(TEMPLATE, content(3))
    rows = image_rows(layout)
    assert len(rows) == 2
    last_columns = [e for e in rows[1]["elements"] if e["elType"] == "column"]
    assert len(last_columns) == 1
    assert last_columns[0]["settings"]["_column_size"] == 100
    widget = next(w for w in walk([rows[1]]) if w.get("widgetType") == IMAGE_WIDGET)
    assert widget["settings"]["image_custom_dimension"] == {"width": "1920", "height": "1080"}


def test_ids_unique_and_template_untouched():
    before = json.dumps(TEMPLATE)
    layout = build_layout(TEMPLATE, content(10))
    ids = [n["id"] for n in walk(layout)]
    assert len(ids) == len(set(ids))
    assert json.dumps(TEMPLATE) == before
    # Trailing empty container from the template is kept.
    assert layout[-1]["elType"] == "container"


def test_no_images_rejected():
    with pytest.raises(TemplateError):
        build_layout(TEMPLATE, content(0))


def test_json_round_trip():
    text = to_json(build_layout(TEMPLATE, content(2)))
    assert json.loads(text)[0]["elType"] == "section"


def test_custom_rows_break_the_pairs_rule():
    c = content(5)
    c.rows = [1, 2, 1, 1]
    layout = build_layout(TEMPLATE, c)
    rows = image_rows(layout)
    counts = [len([w for w in walk([r]) if w.get("widgetType") == IMAGE_WIDGET]) for r in rows]
    assert counts == [1, 2, 1, 1]
    assert image_urls(layout) == [f"https://uniteideas.com/img{i}.jpg" for i in range(5)]
    first_cols = [e for e in rows[0]["elements"] if e["elType"] == "column"]
    assert len(first_cols) == 1 and first_cols[0]["settings"]["_column_size"] == 100


def test_rows_that_do_not_fit_fall_back_to_pairs():
    c = content(3)
    c.rows = [2, 2]  # adds up to 4, but only 3 photos
    counts = [len([w for w in walk([r]) if w.get("widgetType") == IMAGE_WIDGET]) for r in image_rows(build_layout(TEMPLATE, c))]
    assert counts == [2, 1]
