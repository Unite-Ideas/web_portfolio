from portfolio.analysis import photo_score


def test_renders_count_only_when_picked():
    render = {"kind": "rendering", "shows_building": True, "people": "none", "matches_business": "yes", "quality": 5}
    assert photo_score(render) == 0
    assert photo_score(render, allow_renders=True) > 0
