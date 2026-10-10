"""Stage 1 — Search YÖK Ulusal Tez Merkezi, download PDFs, and write a
manifest.jsonl for downstream stages."""
import json
import re
from dataclasses import dataclass
from pathlib import Path

import requests
import urllib3
from bs4 import BeautifulSoup

from stage import Stage

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://tez.yok.gov.tr/UlusalTezMerkezi"



_DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
    "sec-ch-ua": '"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
}



@dataclass
class Thesis:
    kayit_no: str   # data-kayitno — used for download
    tez_no: str     # data-tezno   — used for download
    tez_id: str     # numeric Tez No — used for file naming
    title: str



class HttpClient:
    def __init__(self, headers: dict):
        self._session = requests.Session()
        self._session.headers.update(headers)

    def get(self, path: str, headers: dict | None = None, params: dict | None = None, stream: bool = False) -> requests.Response:
        return self._session.get(f"{BASE_URL}/{path}", headers=headers or {}, params=params, verify=False, stream=stream)

    def post(self, path: str, headers: dict | None = None, data: dict | None = None) -> requests.Response:
        return self._session.post(f"{BASE_URL}/{path}", headers=headers or {}, data=data or {}, verify=False)


class TezSearcher:
    _SEARCH_HEADERS = {
        "content-type": "application/x-www-form-urlencoded",
        "origin": "https://tez.yok.gov.tr",
        "referer": f"{BASE_URL}/tarama.jsp",
        "upgrade-insecure-requests": "1",
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "same-origin",
        "sec-fetch-user": "?1",
    }
    _RESULTS_HEADERS = {"referer": f"{BASE_URL}/tarama.jsp"}

    def __init__(self, client: HttpClient, language: str):
        self._client = client
        self._language = language

    def search(self) -> str:
        self._client.get("tarama.jsp")
        self._submit_search()
        return self._fetch_results()

    def _submit_search(self) -> None:
        payload = (
            f"uniad=&Universite=&uni_yoksis_id=&source=TR&ensad=&Enstitu=0"
            f"&abdad=&ABD=0&Konu=&Tur=0&yil1=0&yil2=0&izin=0&Durum=3"
            f"&TezAd=&Dil={self._language}&AdSoyad=&DanismanAdSoyad="
            f"&Dizin=&TezNo=&Metin=&islem=2&Bolum=0&-find=++Bul"
        )
        r = self._client.post("SearchTez", headers=self._SEARCH_HEADERS, data=payload)
        print(f"[1] SearchTez: {r.status_code} → {r.url.split('/')[-1]}")

    def _fetch_results(self) -> str:
        r = self._client.get("tezSorguSonucYeni.jsp", headers=self._RESULTS_HEADERS)
        print(f"[2] Results: {r.status_code}")
        return r.text



class ThesisParser:
    _TEZ_ID_RE = re.compile(r"\d+")

    def parse(self, html: str) -> list[Thesis]:
        soup = BeautifulSoup(html, "lxml")
        return [self._parse_card(c) for c in soup.find_all(class_="result-card")]

    def _parse_card(self, card: BeautifulSoup) -> Thesis:
        title_el = card.find(class_="card-title")
        tez_id = ""
        for info in card.find_all(class_="card-info"):
            strong = info.find("strong")
            if strong and "Tez No" in strong.text:
                m = self._TEZ_ID_RE.search(info.get_text())
                if m:
                    tez_id = m.group()
        return Thesis(
            kayit_no=card["data-kayitno"],
            tez_no=card["data-tezno"],
            tez_id=tez_id,
            title=title_el.get_text(strip=True) if title_el else "",
        )



class PdfDownloader:
    _KEY_RE = re.compile(r"TezGoster\?key=([^'\"]+)")

    def __init__(self, client: HttpClient):
        self._client = client

    def pdf_url(self, thesis: Thesis) -> str:
        return f"{BASE_URL}/getTezPdf.jsp?kayitNo={thesis.kayit_no}&tezNo={thesis.tez_no}"

    def download_bytes(self, thesis: Thesis) -> bytes | None:
        key = self._resolve_key(thesis)
        if key is None:
            return None
        return self._fetch_pdf(key, thesis.tez_id)

    def _resolve_key(self, thesis: Thesis) -> str | None:
        r = self._client.get(
            "getTezPdf.jsp",
            params={"kayitNo": thesis.kayit_no, "tezNo": thesis.tez_no},
            headers={
                "Referer": f"{BASE_URL}/tezSorguSonucYeni.jsp",
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        m = self._KEY_RE.search(r.text)
        if not m:
            print(f"  Key not found ({thesis.tez_id}): {r.text[:80]}")
            return None
        return m.group(1)

    def _fetch_pdf(self, key: str, tez_id: str) -> bytes | None:
        r = self._client.get(
            "TezGoster",
            params={"key": key},
            headers={"Referer": f"{BASE_URL}/tezSorguSonucYeni.jsp"},
            stream=True,
        )
        r.raw.decode_content = False
        if r.status_code != 200:
            print(f"  PDF fetch failed ({tez_id}): {r.status_code}")
            return None
        try:
            chunks = []
            while chunk := r.raw.read(1024 * 1024):
                chunks.append(chunk)
            return b"".join(chunks)
        except Exception as e:
            print(f"  Stream error ({tez_id}): {e}")
            return None



class ManifestWriter:
    def __init__(self, path: Path):
        self._path = path
        self._file = None

    def __enter__(self) -> "ManifestWriter":
        self._file = open(self._path, "w", encoding="utf-8")
        return self

    def __exit__(self, *_) -> None:
        if self._file:
            self._file.close()

    def write(self, thesis: Thesis, url: str, pdf_file: str) -> None:
        record = {"tez_id": thesis.tez_id, "title": thesis.title, "url": url, "pdf_file": pdf_file}
        self._file.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._file.flush()



class TezScraper(Stage):
    name = "download"

    def __init__(self, language: str = "11"):
        client = HttpClient(_DEFAULT_HEADERS)
        self._searcher = TezSearcher(client, language)
        self._parser = ThesisParser()
        self._downloader = PdfDownloader(client)

    def run(self, input_dir: Path | None, output_dir: Path) -> None:
        html = self._searcher.search()
        theses = self._parser.parse(html)
        print(f"Found {len(theses)} theses")

        output_dir.mkdir(parents=True, exist_ok=True)
        saved = 0

        with ManifestWriter(output_dir / "manifest.jsonl") as manifest:
            for i, thesis in enumerate(theses, 1):
                if self._process(thesis, manifest, output_dir):
                    saved += 1
                print(f"  [{i}/{len(theses)}] downloaded: {saved}", end="\r")

        print(f"\nDone — {saved}/{len(theses)} PDFs saved to {output_dir}/")

    def _process(self, thesis: Thesis, manifest: ManifestWriter, output_dir: Path) -> bool:
        pdf_bytes = self._downloader.download_bytes(thesis)
        if pdf_bytes is None:
            return False
        pdf_file = output_dir / f"{thesis.tez_id}.pdf"
        pdf_file.write_bytes(pdf_bytes)
        manifest.write(thesis, self._downloader.pdf_url(thesis), str(pdf_file))
        return True


if __name__ == "__main__":
    TezScraper().run(None, Path("data/download"))
