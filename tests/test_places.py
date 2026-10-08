from portfolio.places import in_city


def test_in_city():
    assert in_city("1300 Central Ave, Hot Springs, AR 71901, USA", "Hot Springs, AR")
    assert not in_city("107 E Markham St, Little Rock, AR 72201, USA", "Hot Springs, AR")
    assert not in_city("100 Main St, Hot Springs, SD 57747, USA", "Hot Springs, AR")
    assert in_city("2301 E Broad St Bldg 100, Mansfield, TX 76063, USA", "Mansfield, TX")

