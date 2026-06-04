import unicodedata

import pytest

from normalize import Normalizer


def nfd(text: str) -> str:
    return unicodedata.normalize("NFD", text)


def is_nfc(text: str) -> bool:
    return unicodedata.is_normalized("NFC", text)


class TestDefaultNormalizer:
    def setup_method(self):
        self.normalizer = Normalizer()

    @pytest.mark.parametrize(
        "text",
        [
            "Jinûve Zîndîbûna Çanda Lîstikên Retro û Têkelbûna Teknolojîya Modern û Nostaljîyê",
            "Van salên dawîyê vejîneka mezin çêdibe li ser çanda lîstikên retro, ku vedigere lîstikên vîdyoyî yên salên di navbera 1970 û 1990ê de.",
        ],
    )
    def test_nfd_converted_to_nfc(self, text):
        # Kurdish characters like ê, î, û often appear as NFD in raw PDFs
        nfd_text = nfd(text)
        assert not is_nfc(nfd_text)
        result = self.normalizer.normalize(nfd_text)
        assert is_nfc(result)
        assert result == text

    def test_already_nfc_unchanged(self):
        text = "Kurdî û kurmancî"
        assert is_nfc(text)
        assert self.normalizer.normalize(text) == text

    def test_empty_string(self):
        assert self.normalizer.normalize("") == ""

    def test_ascii_unchanged(self):
        text = "Hello world 123"
        assert self.normalizer.normalize(text) == text

    def test_multiline_text_preserved(self):
        text = nfd("Rêz yekem\nRêz duyem\n\nParagrafa nû")
        result = self.normalizer.normalize(text)
        assert result.count("\n") == 3
        assert is_nfc(result)
