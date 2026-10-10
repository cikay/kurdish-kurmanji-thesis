"""Run the extract stage on Modal — one thesis per container, many at once.

Not a `Stage`: like `push_to_hub.py`, a standalone command. MinerU reads under a page a
second, so the corpus is 45-70 hours on one machine, one thesis after another. Nothing in
that is shared between theses, so here each thesis is its own call and Modal runs as many
of them side by side as `MAX_CONTAINERS` allows.

It also gives back the two things running MinerU in-process lost. A document that hangs is
ended by `TIMEOUT_SECONDS`, and a worker killed for memory ends one container — retried
once — instead of the whole pass.

    modal volume put kurmanji-thesis data/download /download     # the PDFs, once
    modal run --detach modal_extract.py                          # extract
    modal volume get kurmanji-thesis /extract data/              # bring the blocks back
    python pipeline.py --start-from sections

The knobs are `config.yml`'s, copied into the image, so this run and a local one cannot
tune differently. That includes `only_theses`: a full pass still needs the list emptied.

The volume is mounted at `/root/data` and the code runs in `/root`, so the relative paths
the manifests carry (`data/download/532507.pdf`) mean the same thing here as on the Mac.

**The blocks are not the Mac's blocks.** A different device is a different run of the
models, the way a different window size is. Extract the whole corpus in one place.
"""
import json
import time
from pathlib import Path

import modal

from blocks import load
from extract import ExtractStage, blocks_path, manifest_row
from stage import stage_config

VOLUME_NAME = "kurmanji-thesis"
DATA_DIR = Path("data")
INPUT_DIR = DATA_DIR / "download"
OUTPUT_DIR = DATA_DIR / "extract"

# How many theses are read at the same time. This sets how long the pass takes, not what
# it costs: the bill is the sum of every container's seconds either way.
MAX_CONTAINERS = 40

# The longest one thesis may take before Modal ends the call. `532507`, 94 scanned pages,
# took 323s on the Mac; the longest thesis is several times that.
TIMEOUT_SECONDS = 2 * 60 * 60

CPU_CORES = 8
MEMORY_MB = 32 * 1024
GPU = "T4"

# The versions the Pipfile.lock resolved to on the Mac, so the models and the code that
# runs them are the same ones the rules in `extract.py` were measured against. On Linux
# `mineru` does not pull torch by itself — the `torch` extra does.
image = (
    modal.Image.debian_slim(python_version="3.13")
    .apt_install("libgl1", "libglib2.0-0")
    .pip_install(
        "mineru[torch]==4.0.10",
        "docvortex==0.5.11",
        "torch==2.14.1",
        "torchvision==0.29.1",
        "transformers==5.17.0",
        "accelerate==1.15.0",
        "safetensors==0.8.0",
        "onnxruntime==1.30.0",
        "huggingface-hub==1.17.0",
        "pyyaml==6.0.3",
    )
    # MinerU picks its small models' backend by device: torch when there is a GPU, onnx on
    # a bare CPU. Pinned to torch, which is what the Mac runs, so a CPU container and a GPU
    # one read a page with the same models.
    .env({"MINERU_MODEL_SMALL_BACKEND": "torch"})
    # Into the image, so that no container downloads models before its first page.
    .run_commands("mineru-models-download --tier basic --small-backend torch --source huggingface")
    .add_local_python_source("blocks", "extract", "stage")
    .add_local_file("config.yml", "/root/config.yml")
)

app = modal.App("kurmanji-thesis-extract", image=image)
volume = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)

RESOURCES = {
    "volumes": {f"/root/{DATA_DIR}": volume},
    "cpu": CPU_CORES,
    "memory": MEMORY_MB,
    "timeout": TIMEOUT_SECONDS,
    "retries": 1,
    "max_containers": MAX_CONTAINERS,
}


def _extract_one(record: dict) -> dict:
    """One thesis: its manifest row, or None if it could not be read, and how long it took.

    A thesis whose blocks file is already on the volume is not read again — its row is
    made from the file. That is what lets a pass that stopped be started again. It also
    means a changed knob does nothing to a thesis already there: delete `/extract` from the
    volume before a run that is meant to differ.
    """
    volume.reload()
    blocks_file = blocks_path(record, OUTPUT_DIR)
    if blocks_file.exists():
        row = manifest_row(record, load(blocks_file), blocks_file)
        return {"tez_id": record["tez_id"], "row": row, "seconds": 0.0, "skipped": True}

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    row = ExtractStage(**stage_config("extract")).extract_one(record, OUTPUT_DIR)
    seconds = time.perf_counter() - started
    volume.commit()
    return {"tez_id": record["tez_id"], "row": row, "seconds": seconds, "skipped": False}


@app.function(gpu=GPU, **RESOURCES)
def extract_on_gpu(record: dict) -> dict:
    return _extract_one(record)


@app.function(**RESOURCES)
def extract_on_cpu(record: dict) -> dict:
    return _extract_one(record)


@app.function(volumes={f"/root/{DATA_DIR}": volume}, timeout=24 * 60 * 60)
def run(gpu: bool) -> None:
    """Fan the theses out, then write the manifest in the download manifest's order.

    This runs on Modal and not on the Mac so that a detached run finishes with the laptop
    closed.
    """
    with open(INPUT_DIR / "manifest.jsonl", encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]
    records = ExtractStage(**stage_config("extract")).selected(records)

    extract = extract_on_gpu if gpu else extract_on_cpu
    print(f"Extracting {len(records)} PDFs with MinerU on {GPU if gpu else 'CPU'}")

    rows = []
    # A list, so the map is read to its end before anything else touches the volume.
    results = list(extract.map(records, order_outputs=True, return_exceptions=True))
    for record, result in zip(records, results):
        if isinstance(result, Exception):
            print(f"  {record['tez_id']} failed: {type(result).__name__}: {result}")
        elif result["row"] is None:
            print(f"  {record['tez_id']} not extracted ({result['seconds']:.0f}s)")
        else:
            note = "already there" if result["skipped"] else f"{result['seconds']:.0f}s"
            print(f"  {record['tez_id']} {result['row']['block_count']} blocks ({note})")
            rows.append(result["row"])

    volume.reload()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_DIR / "manifest.jsonl", "w", encoding="utf-8") as manifest_file:
        for row in rows:
            manifest_file.write(json.dumps(row, ensure_ascii=False) + "\n")
    volume.commit()

    print(f"\nDone — {len(rows)}/{len(records)} theses extracted to {OUTPUT_DIR}/")


@app.local_entrypoint()
def main(gpu: bool = True) -> None:
    """`--no-gpu` runs on CPU containers."""
    run.remote(gpu)
