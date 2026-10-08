from pathlib import Path

from portfolio.cli import parse_folder_choice
from portfolio.dropbox_local import FolderMatch


def test_parse_folder_choice(tmp_path):
    matches = [FolderMatch(Path(f"folder{i}"), 7, 2025) for i in range(1, 5)]
    assert parse_folder_choice("2", matches) == [Path("folder2")]
    assert parse_folder_choice("1,3", matches) == [Path("folder1"), Path("folder3")]
    assert parse_folder_choice(" 3 1, 3 ", matches) == [Path("folder3"), Path("folder1")]
    assert parse_folder_choice("0", matches) == []
    assert parse_folder_choice("5", matches) is None
    assert parse_folder_choice("1,0", matches) is None
    assert parse_folder_choice("hello", matches) is None
    assert parse_folder_choice(f'"{tmp_path}"', matches) == [tmp_path]
