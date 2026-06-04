from pathlib import Path

import pytest

from clean import CleanConfig, Cleaner

SAMPLE_FILE = Path(__file__).parent / "data" / "375245.txt"


@pytest.fixture
def cleaner():
    return Cleaner(CleanConfig())


@pytest.fixture
def sample_text():
    return SAMPLE_FILE.read_text(encoding="utf-8")


class TestSplitParagraphs:
    def test_no_empty_paragraphs(self, cleaner, sample_text):
        result = cleaner._split_paragraphs(sample_text)
        assert all(p.strip() for p in result)

    def test_no_leading_trailing_newlines(self, cleaner, sample_text):
        result = cleaner._split_paragraphs(sample_text)
        for p in result:
            assert not p.startswith("\n")
            assert not p.endswith("\n")

    def test_splits_on_blank_line(self, cleaner):
        text = "Paragraf yek.\n\nParagraf du."
        result = cleaner._split_paragraphs(text)
        assert result == ["Paragraf yek.", "Paragraf du."]

    def test_splits_on_whitespace_only_line(self, cleaner):
        # Lines with only spaces should also act as paragraph separators
        text = "Paragraf yek.\n   \nParagraf du."
        result = cleaner._split_paragraphs(text)
        assert result == ["Paragraf yek.", "Paragraf du."]

    def test_normalizes_windows_line_endings(self, cleaner):
        text = "Rêz yek.\r\n\r\nRêz du."
        result = cleaner._split_paragraphs(text)
        assert result == ["Rêz yek.", "Rêz du."]

    def test_multiple_blank_lines_treated_as_one(self, cleaner):
        text = "Paragraf yek.\n\n\n\nParagraf du."
        result = cleaner._split_paragraphs(text)
        assert result == ["Paragraf yek.", "Paragraf du."]

    def test_leading_and_trailing_blank_lines_ignored(self, cleaner):
        text = "\n\nParagraf yek.\n\nParagraf du.\n\n"
        result = cleaner._split_paragraphs(text)
        assert result == ["Paragraf yek.", "Paragraf du."]

    def test_single_paragraph_no_blank_lines(self, cleaner):
        text = "Tenê paragrafek heye."
        result = cleaner._split_paragraphs(text)
        assert result == ["Tenê paragrafek heye."]

    def test_empty_string_returns_empty_list(self, cleaner):
        assert cleaner._split_paragraphs("") == []

    def test_real_file_paragraph_count_reasonable(self, cleaner, sample_text):
        result = cleaner._split_paragraphs(sample_text)
        # A thesis file should have many paragraphs
        assert len(result) > 10
