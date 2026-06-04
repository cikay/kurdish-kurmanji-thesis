"""Stage — Extract plain text from downloaded PDFs and write to txt files."""
import json
from pathlib import Path

import pymupdf

from stage import Stage


class PdfTextExtractor:
    def extract(self, pdf_path: Path) -> str | None:
        try:
            doc = pymupdf.open(str(pdf_path))
            pages = (page.get_text() for page in doc)
            return "\n".join(filter(None, pages))
        except Exception as e:
            print(f"  PDF parse error ({pdf_path.name}): {e}")
            return None


class ExtractStage(Stage):
    name = "extract"

    def __init__(self):
        self._extractor = PdfTextExtractor()

    def run(self, input_dir: Path | None, output_dir: Path) -> None:
        records = self._load_manifest(input_dir / "manifest.jsonl")
        print(f"Extracting text from {len(records)} PDFs")

        output_dir.mkdir(parents=True, exist_ok=True)
        saved = 0

        with open(output_dir / "manifest.jsonl", "w", encoding="utf-8") as mf:
            for i, record in enumerate(records, 1):
                text = self._extractor.extract(Path(record["pdf_file"]))
                if text:
                    txt_file = output_dir / f"{record['tez_id']}.txt"
                    txt_file.write_text(text, encoding="utf-8")
                    mf.write(json.dumps({
                        "tez_id": record["tez_id"],
                        "title": record["title"],
                        "url": record["url"],
                        "txt_file": str(txt_file),
                    }, ensure_ascii=False) + "\n")
                    saved += 1
                print(f"  [{i}/{len(records)}] extracted: {saved}", end="\r")

        print(f"\nDone — {saved}/{len(records)} txt files saved to {output_dir}/")

    def _load_manifest(self, path: Path) -> list[dict]:
        with open(path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]


if __name__ == "__main__":
    from pathlib import Path
    stage = ExtractStage()
    stage.run(Path("data/download"), Path("data/extract"))
