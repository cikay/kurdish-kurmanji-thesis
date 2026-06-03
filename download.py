"""Stage 1 — Search YÖK Ulusal Tez Merkezi, download PDFs, and write a
manifest.jsonl for downstream stages."""
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import requests
import urllib3
from bs4 import BeautifulSoup

from stage import Stage

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://tez.yok.gov.tr/UlusalTezMerkezi"



@dataclass
class Config:
    downloads_dir: Path = field(default_factory=lambda: Path("data/download"))
    language: str = "11"      # 11=Kurdish; leave "" for any language
    headers: dict = field(default_factory=lambda: {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
        "sec-ch-ua": '"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
    })

    @property
    def manifest_file(self) -> Path:
        return self.downloads_dir / "manifest.jsonl"



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

    def __init__(self, client: HttpClient, config: Config):
        self._client = client
        self._config = config

    def search(self) -> str:
        self._client.get("tarama.jsp")
        self._submit_search()
        return self._fetch_results()

    def _submit_search(self) -> None:
        payload = (
            f"uniad=&Universite=&uni_yoksis_id=&source=TR&ensad=&Enstitu=0"
            f"&abdad=&ABD=0&Konu=&Tur=0&yil1=0&yil2=0&izin=0&Durum=3"
            f"&TezAd=&Dil={self._config.language}&AdSoyad=&DanismanAdSoyad="
            f"&Dizin=&TezNo=&islem=2&Bolum=0&-find=++Bul"
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
    def __init__(self, client: HttpClient):
        self._client = client

    def pdf_url(self, thesis: Thesis) -> str:
        return f"{BASE_URL}/getTezPdf.jsp?kayitNo={thesis.kayit_no}&tezNo={thesis.tez_no}"

    def download_bytes(self, thesis: Thesis) -> bytes | None:
        r = self._client.get(
            "getTezPdf.jsp",
            params={"kayitNo": thesis.kayit_no, "tezNo": thesis.tez_no},
            headers={
                "Referer": f"{BASE_URL}/tezSorguSonucYeni.jsp",
                "X-Requested-With": "XMLHttpRequest",
            },
            stream=True,
        )
        r.raw.decode_content = False
        if r.status_code != 200:
            print(f"  PDF fetch failed ({thesis.tez_id}): {r.status_code}")
            return None
        return self._stream_bytes(r, thesis.tez_id)

    def _stream_bytes(self, response: requests.Response, tez_id: str) -> bytes | None:
        try:
            chunks = []
            while chunk := response.raw.read(1024 * 1024):
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

    def __init__(self, config: Config | None = None):
        self._config = config or Config()
        client = HttpClient(self._config.headers)
        self._searcher = TezSearcher(client, self._config)
        self._parser = ThesisParser()
        self._downloader = PdfDownloader(client)

    def run(self) -> None:
        html = self._searcher.search()
        theses = self._parser.parse(html)
        print(f"Found {len(theses)} theses")

        self._config.downloads_dir.mkdir(parents=True, exist_ok=True)
        saved = 0

        with ManifestWriter(self._config.manifest_file) as manifest:
            for i, thesis in enumerate(theses, 1):
                if self._process(thesis, manifest):
                    saved += 1
                print(f"  [{i}/{len(theses)}] downloaded: {saved}", end="\r")

        print(f"\nDone — {saved}/{len(theses)} PDFs saved to {self._config.downloads_dir}/")

    def _process(self, thesis: Thesis, manifest: ManifestWriter) -> bool:
        pdf_bytes = self._downloader.download_bytes(thesis)
        if pdf_bytes is None:
            return False
        pdf_file = self._config.downloads_dir / f"{thesis.tez_id}.pdf"
        pdf_file.write_bytes(pdf_bytes)
        manifest.write(thesis, self._downloader.pdf_url(thesis), str(pdf_file))
        return True


if __name__ == "__main__":
    TezScraper().run()
