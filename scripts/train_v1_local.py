"""Train v1 on the laptop GPU (Quadro P2000, 4 GB) instead of Colab.

Batch 4 needs 4.2 GB and spills into shared memory (7.7 s per batch), so this
uses batch 2 (2.7 GB peak). Without a cap, PyTorch's cache still grows past
4 GB and Windows spills it to shared memory (3.3 s per batch), so the cache is
capped at 85% of the card. geoai also forces deterministic cuDNN, which
doubles the time (3.2 vs 1.5 s per batch) without making Mask R-CNN repeatable
(RoIAlign's backward pass isn't deterministic on GPU), so that flag is blocked.
Result: about 7.5 h for 50 epochs. Every other setting comes from the config.

geoai keeps only the best weights, so this script also writes a full checkpoint
(model, optimizer, scheduler, epoch, best IoU) to ``models/v1/checkpoint_last.pth``
after every epoch. Run with the CUDA torch on the path:

    PYTHONPATH=D:/torchgpu python scripts/train_v1_local.py            # fresh run
    PYTHONPATH=D:/torchgpu python scripts/train_v1_local.py --resume   # after a crash
"""

from __future__ import annotations

import argparse
import ctypes
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from parcelwatch.config import Config, load_config  # noqa: E402
from parcelwatch.detect import train_v1  # noqa: E402
from parcelwatch.paths import Paths  # noqa: E402

LOCAL_BATCH_SIZE = 2
GPU_MEMORY_FRACTION = 0.85
# geoai.train_MaskRCNN_model hard-codes StepLR(step_size=5, gamma=0.8).
LR_STEP_SIZE = 5
LR_GAMMA = 0.8
CHECKPOINT = "checkpoint_last.pth"
os.environ.setdefault(
    "PYTORCH_CUDA_ALLOC_CONF", "garbage_collection_threshold:0.7,max_split_size_mb:128"
)
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001

log = logging.getLogger("train_v1_local")


def keep_awake() -> None:
    """Stop Windows idle sleep while this process runs (closing the lid still sleeps)."""
    if sys.platform == "win32":
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)


def block_deterministic_cudnn() -> None:
    """Make geoai's ``cudnn.deterministic = True`` a no-op (the flag stays False)."""
    import torch.backends.cudnn as cudnn

    type(cudnn).deterministic = property(lambda m: False, lambda m, v: None)  # type: ignore[assignment]


def scheduler_state(base_lr: float, epochs_done: int) -> dict[str, Any]:
    """StepLR state after ``epochs_done`` epochs, matching geoai's schedule."""
    import torch

    opt = torch.optim.SGD([torch.zeros(1, requires_grad=True)], lr=base_lr)
    sched = torch.optim.lr_scheduler.StepLR(opt, step_size=LR_STEP_SIZE, gamma=LR_GAMMA)
    for _ in range(epochs_done):
        opt.step()
        sched.step()
    state: dict[str, Any] = sched.state_dict()
    return state


def save_checkpoint_every_epoch(path: Path, base_lr: float, best_iou: float) -> None:
    """Patch geoai's loop to write a full checkpoint after each epoch's validation.

    geoai calls ``train_one_epoch``, then ``lr_scheduler.step()``, then ``evaluate``,
    so at evaluation time the optimizer already holds the next epoch's learning rate.
    """
    import geoai.train as gt
    import torch

    state: dict[str, Any] = {"best_iou": best_iou}
    orig_train, orig_eval = gt.train_one_epoch, gt.evaluate

    def train_one_epoch(
        model: Any, optimizer: Any, data_loader: Any, device: Any, epoch: int, *a: Any, **k: Any
    ) -> float:
        state.update(model=model, optimizer=optimizer, epoch=epoch)
        return float(orig_train(model, optimizer, data_loader, device, epoch, *a, **k))

    def evaluate(*a: Any, **k: Any) -> dict[str, float]:
        metrics: dict[str, float] = orig_eval(*a, **k)
        if "epoch" in state:  # skip geoai's final evaluation after the loop
            epoch = state.pop("epoch")
            state["best_iou"] = max(state["best_iou"], metrics["IoU"])
            tmp = path.with_suffix(".tmp")
            torch.save(
                {
                    "model_state_dict": state["model"].state_dict(),
                    "optimizer_state_dict": state["optimizer"].state_dict(),
                    "scheduler_state_dict": scheduler_state(base_lr, epoch + 1),
                    "epoch": epoch,
                    "best_iou": state["best_iou"],
                },
                tmp,
            )
            tmp.replace(path)
            log.info("checkpoint after epoch %d written to %s", epoch + 1, path.name)
        return metrics

    gt.train_one_epoch, gt.evaluate = train_one_epoch, evaluate


def checkpoint_from_best(out_dir: Path, cfg: Config, epochs_done: int, best_iou: float) -> Path:
    """Build a resume checkpoint from ``best_model.pth`` (weights only).

    Used once, for the run interrupted on 2026-11-02 before per-epoch checkpoints
    existed. The weights must be from epoch ``epochs_done``. The learning rate and
    scheduler are set to where they'd be after that many epochs; SGD momentum
    starts from zero, which is the only difference from an unbroken run.
    """
    import torch
    from geoai.train import get_detection_model

    v1 = cfg.model.v1
    model = get_detection_model(
        "maskrcnn_resnet50_fpn", num_classes=2, num_channels=v1.num_channels, pretrained=True
    )
    model.load_state_dict(torch.load(out_dir / "best_model.pth", map_location="cpu"))
    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.SGD(params, lr=v1.learning_rate, momentum=0.9, weight_decay=0.0005)
    sched = torch.optim.lr_scheduler.StepLR(opt, step_size=LR_STEP_SIZE, gamma=LR_GAMMA)
    for g in opt.param_groups:
        g["lr"] = v1.learning_rate * LR_GAMMA ** (epochs_done // LR_STEP_SIZE)
    sched.load_state_dict(scheduler_state(v1.learning_rate, epochs_done))
    path = out_dir / CHECKPOINT
    torch.save(
        {
            "model_state_dict": model.state_dict(),
            "optimizer_state_dict": opt.state_dict(),
            "scheduler_state_dict": sched.state_dict(),
            "epoch": epochs_done - 1,
            "best_iou": best_iou,
        },
        path,
    )
    log.info(
        "resume checkpoint built from best_model.pth (epoch %d, lr %.6f)",
        epochs_done,
        opt.param_groups[0]["lr"],
    )
    return path


def main() -> None:
    """Fine-tune v1 on data/training/v1_tiles and write models/v1."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--resume", action="store_true", help=f"continue from models/v1/{CHECKPOINT}")
    ap.add_argument(
        "--from-best",
        nargs=2,
        metavar=("EPOCH", "BEST_IOU"),
        help="build the resume checkpoint from best_model.pth saved at EPOCH, then resume",
    )
    args = ap.parse_args()

    import torch

    if not torch.cuda.is_available():
        sys.exit("CUDA torch not found: run with PYTHONPATH=D:/torchgpu")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    torch.cuda.set_per_process_memory_fraction(GPU_MEMORY_FRACTION)
    block_deterministic_cudnn()
    cfg = load_config(ROOT / "configs" / "wake_pilot.yaml")
    p = Paths(cfg.root)
    out_dir = p.models / "v1"
    ckpt = out_dir / CHECKPOINT
    resume: Path | None = None
    best_iou = 0.0
    if args.from_best:
        resume = checkpoint_from_best(
            out_dir, cfg, int(args.from_best[0]), float(args.from_best[1])
        )
    elif args.resume:
        if not ckpt.exists():
            sys.exit(f"{ckpt} not found")
        resume = ckpt
    elif ckpt.exists():
        sys.exit(f"{ckpt} exists: pass --resume, or delete it to start over")
    if resume is not None:
        best_iou = float(torch.load(resume, map_location="cpu", weights_only=False)["best_iou"])
    save_checkpoint_every_epoch(ckpt, cfg.model.v1.learning_rate, best_iou)

    log.info("GPU %s, torch %s", torch.cuda.get_device_name(0), torch.__version__)
    keep_awake()
    t0 = time.time()
    best = train_v1(
        p.training / "v1_tiles", out_dir, cfg, batch_size=LOCAL_BATCH_SIZE, resume_checkpoint=resume
    )
    hours = (time.time() - t0) / 3600
    resumed_from = None
    if args.from_best:
        resumed_from = f"best_model.pth after epoch {args.from_best[0]} (SGD momentum reset)"
    elif resume is not None:
        resumed_from = resume.name
    settings = best.parent / "train_settings.json"
    record = json.loads(settings.read_text())
    record["trained_on"] = {
        "gpu": torch.cuda.get_device_name(0),
        "torch": torch.__version__,
        "memory_fraction": GPU_MEMORY_FRACTION,
        "cudnn_deterministic": False,
        "hours_this_run": round(hours, 2),
        "resumed_from": resumed_from,
    }
    settings.write_text(json.dumps(record, indent=2))
    log.info("done in %.1f h, best weights %s", hours, best)


if __name__ == "__main__":
    main()
