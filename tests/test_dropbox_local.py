from portfolio.dropbox_local import business_codes, find_project_folders, folder_year, read_project, score_folder


def make_tree(root, names):
    for name in names:
        (root / name).mkdir(parents=True)


def test_codes():
    assert {"rnrs", "rnr"} <= business_codes("Rock N Roll Sushi")


def test_folder_year():
    assert folder_year("250907_RNR_Mansfield, TX", "__UNITE_2025") == 2025
    assert folder_year("Blue Springs", "__UNITE_2024") == 2024


def test_finds_abbreviated_folder(tmp_path):
    make_tree(tmp_path, [
        "__UNITE_2025/250907_RNR_Mansfield, TX",
        "__UNITE_2025/251005_MC2_McCordsville_IN",
        "__UNITE_2025/250513_Willamette Christian Center",
        "__UNITE_2026/260101_Pancheros_Springfield_MO",
        "__UNITE_2025/_ARCHIVE 2025/250101_RNR_Frisco, TX",
    ])
    matches = find_project_folders(tmp_path, "Rock N Roll Sushi", "Mansfield, TX")
    assert matches[0].path.name == "250907_RNR_Mansfield, TX"
    assert matches[0].year == 2025
    assert matches[0].score - matches[1].score >= 2  # Frisco is a weaker match

    p = find_project_folders(tmp_path, "Pancheros Mexican Grill", "Springfield, MO")
    assert p[0].path.name == "260101_Pancheros_Springfield_MO"


def test_skips_reference_folders(tmp_path):
    make_tree(tmp_path, [
        "__UNITE_2025/250907_RNR_Mansfield, TX",
        "__UNITE_2026/_REF - Rock N Roll Sushi",
        "__UNITE_2026/_NewClient_Template",
    ])
    matches = find_project_folders(tmp_path, "Rock N Roll Sushi", "Mansfield, TX")
    assert [m.path.name for m in matches] == ["250907_RNR_Mansfield, TX"]


def test_lowercase_underscored_folder():
    assert score_folder("251006_trinitychurch_scottsdale_az", "Trinity Church", "Scottsdale, AZ") >= 7


def test_read_project_skips_invoices(tmp_path):
    folder = tmp_path / "250907_RNR_Mansfield, TX"
    (folder / "Proposals").mkdir(parents=True)
    (folder / "Invoices").mkdir()
    (folder / "Proposals" / "scope.txt").write_text("New 2,400 sq ft restaurant building.")
    (folder / "Invoices" / "inv.txt").write_text("Amount due $9,999")
    (folder / "FINALS").mkdir()
    (folder / "FINALS" / "photo.jpg").write_bytes(b"x" * 200_000)
    docs = read_project(folder)
    assert [name for name, _ in docs.documents] == ["Proposals/scope.txt"]
    assert len(docs.images) == 1


def test_read_project_groups_folders(tmp_path):
    main = tmp_path / "250907_RNR_Mansfield, TX"
    renders = tmp_path / "250907_RNR_Mansfield renders"
    (main / "Proposals").mkdir(parents=True)
    (main / "Proposals" / "scope.txt").write_text("New restaurant building.")
    (main / "FINALS").mkdir()
    (main / "FINALS" / "photo.jpg").write_bytes(b"x" * 200_000)
    (renders / "RENDERS").mkdir(parents=True)
    (renders / "RENDERS" / "front.jpg").write_bytes(b"y" * 300_000)
    (renders / "RENDERS" / "photo.jpg").write_bytes(b"x" * 200_000)  # copy of the main folder's photo
    docs = read_project([main, renders])
    assert [name for name, _ in docs.documents] == ["250907_RNR_Mansfield, TX/Proposals/scope.txt"]
    assert sorted(p.name for p in docs.images) == ["front.jpg", "photo.jpg"]
