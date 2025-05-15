#!/usr/bin/env python3
"""
gr00t_handler_script.py – Minimal standalone script for Alon's Runpod handler
--------------------------------------------------------------------------
* Logs in to Hugging Face with a user token (taken from CLI arg or HF_TOKEN env).
* Launches GR00T fine‑tuning with sane defaults but overridable CLI flags.
* On success, uploads the produced checkpoint directory to a fixed HF repo and
  commits with a UTC timestamp so runs are traceable.

Assumptions
===========
1. Script runs **inside** the Docker image that already has:
   • CUDA/PyTorch + GR00T source (at ~/Isaac-GR00T) ─ built earlier in the image.
   • `huggingface_hub` installed (pip install huggingface_hub).
2. Conda env `gr00t` is activated (or the Python interpreter already has deps).
3. Only **one** GPU is visible (`--num-gpus 1`).
4. Dataset lives on Hugging Face Hub (e.g. "Ofiroz91/so100_sorting_socks") and
   GR00T's finetune script supports that path natively (current upstream does).

Usage (inside container / Runpod):
==================================
```bash
python gr00t_handler_script.py \
  --hf-token $HF_TOKEN \
  --hf-repo Ofiroz91/gr00t-n1-so100-weights \
  --dataset-path Ofiroz91/so100_sorting_socks
```
Additional flags can be forwarded unchanged to `scripts/gr00t_finetune.py` via
`--extra "--batch-size 8 --learning-rate 5e-5"`.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from huggingface_hub import HfApi, login, upload_folder

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(cmd: List[str], cwd: str | Path | None = None) -> None:
    """Run a subprocess and stream its output; raise on non‑zero exit code."""
    cwd = str(cwd) if cwd else None
    print("[CMD]", " ".join(cmd))
    process = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for line in process.stdout:  # type: ignore[attr-defined]
        print(line, end="")
    process.wait()
    if process.returncode != 0:
        raise RuntimeError(f"Command failed with exit code {process.returncode}: {' '.join(cmd)}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Train GR00T N1 and push weights to HF")
    parser.add_argument("--hf-token", default=os.getenv("HF_TOKEN"), help="Hugging Face token (or HF_TOKEN env)")
    parser.add_argument("--dataset-path", default="Ofiroz91/so100_sorting_socks", help="HF dataset repo or local path")
    parser.add_argument("--hf-repo", default="Ofiroz91/gr00t-n1-so100-weights", help="HF repo to push weights to")
    parser.add_argument("--output-dir", default="/workspace/gr00t_output", help="Local output directory base")
    parser.add_argument("--num-gpus", type=int, default=1, help="GPUs to pass to finetune script (default 1)")
    parser.add_argument("--extra", default="", help="Extra flags to append verbatim to finetune script")

    args = parser.parse_args()

    if not args.hf_token:
        print("❌ --hf-token not provided and HF_TOKEN env not set", file=sys.stderr)
        sys.exit(1)

    # Timestamped run directory under output‑dir
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_dir = Path(args.output_dir).expanduser().joinpath(f"run_{ts}")
    run_dir.mkdir(parents=True, exist_ok=True)

    # ---- 1. Login to Hugging Face ------------------------------------------------
    print("🔑 Logging in to Hugging Face…")
    login(token=args.hf_token, add_to_git_credential=True)

    # Ensure target repo exists (private if user wishes)
    api = HfApi()
    if not api.repo_exists(args.hf_repo):
        user, repo_name = args.hf_repo.split("/")
        print(f"📦 Creating repo {args.hf_repo}…")
        api.create_repo(repo_id=repo_name, token=args.hf_token, repo_type="model", private=True)

    # ---- 2. Launch fine‑tuning ---------------------------------------------------
    print("🚀 Starting GR00T fine‑tuning…")
    base_cmd = [
        "python", "scripts/gr00t_finetune.py",
        "--dataset-path", args.dataset_path,
        "--output-dir", str(run_dir),
        "--num-gpus", str(args.num_gpus),
    ]
    if args.extra:
        base_cmd.extend(args.extra.split())

    run(base_cmd, cwd=str(Path.home() / "Isaac-GR00T"))

    # ---- 3. Upload weights -------------------------------------------------------
    print("📤 Uploading weights to HF…")
    commit_msg = f"run {ts}"
    upload_folder(
        repo_id=args.hf_repo,
        folder_path=str(run_dir),
        commit_message=commit_msg,
        token=args.hf_token,
        path_in_repo=ts  # keep each run in its own sub‑folder
    )

    print("✅ Done! Weights pushed to:")
    print(f"https://huggingface.co/{args.hf_repo}/tree/main/{ts}")


if __name__ == "__main__":
    main()
