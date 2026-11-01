"""Train v1 on the laptop GPU (Quadro P2000, 4 GB) instead of Colab.

Batch 4 needs 4.2 GB and spills into shared memory (7.7 s per batch), so this
uses batch 2 (2.7 GB peak). Without a cap, PyTorch's cache still grows past
4 GB and Windows spills it to shared memory (3.3 s per batch), so the cache is
capped at 85% of the card. geoai also forces deterministic cuDNN, which
doubles the time (3.2 vs 1.5 s per batch) without making Mask R-CNN repeatable
(RoIAlign's backward pass isn't deterministic on GPU), so that flag is blocked.
Result: about 7 h for 50 epochs. Every other setting comes from the config.
Run with the CUDA torch on the path:

    PYTHONPATH=D:/torchgpu python scripts/train_v1_local.py
"""

from __future__ import annotations

import ctypes
import json
import logging
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from parcelwatch.config import load_config  # noqa: E402
from parcelwatch.detect import train_v1  # noqa: E402
from parcelwatch.paths import Paths  # noqa: E402

LOCAL_BATCH_SIZE = 2
GPU_MEMORY_FRACTION = 0.85
os.environ.setdefault(
    "PYTORCH_CUDA_ALLOC_CONF", "garbage_collection_threshold:0.7,max_split_size_mb:128"
)
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


def keep_awake() -> None:
    """Stop Windows from sleeping while this process runs (no system settings change)."""
    if sys.platform == "win32":
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)


def block_deterministic_cudnn() -> None:
    """Make geoai's ``cudnn.deterministic = True`` a no-op (the flag stays False)."""
    import torch.backends.cudnn as cudnn

    type(cudnn).deterministic = property(lambda m: False, lambda m, v: None)  # type: ignore[assignment]


def main() -> None:
    """Fine-tune v1 on data/training/v1_tiles and write models/v1."""
    import torch

    if not torch.cuda.is_available():
        sys.exit("CUDA torch not found: run with PYTHONPATH=D:/torchgpu")
    torch.cuda.set_per_process_memory_fraction(GPU_MEMORY_FRACTION)
    block_deterministic_cudnn()
    cfg = load_config(ROOT / "configs" / "wake_pilot.yaml")
    p = Paths(cfg.root)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.info("GPU %s, torch %s", torch.cuda.get_device_name(0), torch.__version__)
    keep_awake()
    t0 = time.time()
    best = train_v1(p.training / "v1_tiles", p.models / "v1", cfg, batch_size=LOCAL_BATCH_SIZE)
    hours = (time.time() - t0) / 3600
    settings = best.parent / "train_settings.json"
    record = json.loads(settings.read_text())
    record["trained_on"] = {
        "gpu": torch.cuda.get_device_name(0),
        "torch": torch.__version__,
        "memory_fraction": GPU_MEMORY_FRACTION,
        "cudnn_deterministic": False,
        "hours": round(hours, 2),
    }
    settings.write_text(json.dumps(record, indent=2))
    logging.info("done in %.1f h, best weights %s", hours, best)


if __name__ == "__main__":
    main()
