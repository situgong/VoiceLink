# ============================================================================
# VoiceLink — Qwen3 TTS Model Downloader
# ============================================================================
# Standalone script that handles downloading Qwen3-TTS models from HuggingFace.
# Called by the GUI download button via setup_run_command.
#
# Usage: python server/download_qwen3.py --tier standard|full [--data-dir PATH]
#
# Outputs structured lines to stdout for the GUI to parse:
#   PROGRESS: <pct>% <downloaded_mb>/<total_mb> MB — <filename>
#   DOWNLOAD: [n/total] <model_id>
#   OK: <model_id> -> <path>
#   ERROR: <message>
#   DONE / PARTIAL / FATAL
#
# Exit codes:
#   0: All models downloaded successfully
#   1: Some models failed (partial success)
#   2: Fatal error (no models downloaded)
# ============================================================================

import sys
import os
import argparse
import json
import time


# Model repository IDs on HuggingFace
# These follow the Qwen/Qwen3-TTS namespace from the official release.
MODEL_REGISTRY = {
    "standard": [
        "Qwen/Qwen3-TTS-Tokenizer-12Hz",
        "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
        "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice",
    ],
    "full": [
        "Qwen/Qwen3-TTS-Tokenizer-12Hz",
        "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
        "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
        "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
    ],
}


def install_deps():
    """Ensure huggingface_hub is available for downloading."""
    try:
        import huggingface_hub
        print(f"OK: huggingface_hub {huggingface_hub.__version__} available", flush=True)
        return True
    except ImportError:
        print("huggingface_hub not found, installing...", flush=True)
        import subprocess
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--no-warn-script-location", "huggingface_hub"],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            print(f"ERROR: Failed to install huggingface_hub: {result.stderr.strip()}", flush=True)
            return False
        print("OK: huggingface_hub installed", flush=True)
        return True


def get_repo_file_sizes(model_id: str):
    """Get list of (filename, size_bytes) for all files in a repo."""
    from huggingface_hub import HfApi
    api = HfApi()
    try:
        info = api.repo_info(model_id, files_metadata=True)
        files = []
        for sibling in info.siblings or []:
            size = getattr(sibling, "size", None) or 0
            files.append((sibling.rfilename, size))
        return files
    except Exception:
        return []


def download_model(model_id: str, index: int, total: int,
                   cumulative_bytes: int, grand_total_bytes: int) -> tuple:
    """
    Download a single model file-by-file with live progress.
    Returns (success: bool, bytes_downloaded: int).
    """
    from huggingface_hub import hf_hub_download, HfApi
    from huggingface_hub.utils import (
        RepositoryNotFoundError,
        GatedRepoError,
        EntryNotFoundError,
    )

    short_name = model_id.split("/")[-1]
    print(f"DOWNLOAD: [{index}/{total}] {model_id}", flush=True)

    try:
        api = HfApi()
        info = api.repo_info(model_id, files_metadata=True)
        siblings = info.siblings or []

        model_bytes_done = 0
        last_progress_time = 0

        for file_idx, sibling in enumerate(siblings):
            fname = sibling.rfilename
            fsize = getattr(sibling, "size", None) or 0

            # Download individual file (resumes partial downloads automatically)
            hf_hub_download(model_id, fname)

            model_bytes_done += fsize
            overall_done = cumulative_bytes + model_bytes_done
            overall_pct = min(99, int(overall_done / max(grand_total_bytes, 1) * 100))

            # Throttle progress output to avoid flooding (max every 0.3s)
            now = time.monotonic()
            if now - last_progress_time >= 0.3 or file_idx == len(siblings) - 1:
                overall_mb = overall_done / (1024 * 1024)
                total_mb = grand_total_bytes / (1024 * 1024)
                print(
                    f"PROGRESS: {overall_pct}% {overall_mb:.0f}/{total_mb:.0f} MB -- {short_name}/{fname}",
                    flush=True,
                )
                last_progress_time = now

        # Get the snapshot path for reporting
        from huggingface_hub import snapshot_download
        path = snapshot_download(model_id)  # instant — already cached
        print(f"OK: {model_id} -> {path}", flush=True)
        return True, model_bytes_done

    except RepositoryNotFoundError:
        print(f"ERROR: {model_id} not found on HuggingFace. Check model ID.", flush=True)
        return False, 0

    except GatedRepoError:
        print(f"ERROR: {model_id} is a gated repo. Accept terms at https://huggingface.co/{model_id}", flush=True)
        return False, 0

    except EntryNotFoundError as e:
        print(f"ERROR: {model_id} missing files: {e}", flush=True)
        return False, 0

    except Exception as e:
        error_msg = str(e)
        if len(error_msg) > 300:
            error_msg = error_msg[:300] + "..."
        print(f"ERROR: {model_id} download failed: {error_msg}", flush=True)
        return False, 0


def write_marker(data_dir: str, tier: str, results: dict):
    """Write a marker file indicating download completion."""
    marker_path = os.path.join(data_dir, ".qwen3_ready")
    try:
        os.makedirs(data_dir, exist_ok=True)
        with open(marker_path, "w") as f:
            json.dump({
                "tier": tier,
                "models": results,
            }, f, indent=2)
        print(f"OK: Marker written to {marker_path}", flush=True)
    except Exception as e:
        print(f"WARN: Could not write marker: {e}", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Download Qwen3-TTS models")
    parser.add_argument("--tier", choices=["standard", "full"], default="standard",
                        help="Model tier to download")
    parser.add_argument("--data-dir", default=os.environ.get("VOICELINK_DATA_DIR", r"C:\ProgramData\VoiceLink"),
                        help="VoiceLink data directory")
    args = parser.parse_args()

    print(f"=== Qwen3-TTS Model Downloader ===", flush=True)
    print(f"Tier: {args.tier}", flush=True)
    print(f"Data dir: {args.data_dir}", flush=True)
    print(f"Python: {sys.executable}", flush=True)

    # Step 1: Ensure dependencies
    if not install_deps():
        print("FATAL: Cannot install required dependencies", flush=True)
        sys.exit(2)

    # Step 2: Calculate total download size across all models
    models = MODEL_REGISTRY[args.tier]
    print("PROGRESS: 0% 0/0 MB -- Calculating download size...", flush=True)

    grand_total_bytes = 0
    model_sizes = {}
    for model_id in models:
        files = get_repo_file_sizes(model_id)
        model_size = sum(size for _, size in files)
        model_sizes[model_id] = model_size
        grand_total_bytes += model_size

    total_mb = grand_total_bytes / (1024 * 1024)
    print(f"SIZE: {total_mb:.0f} MB total across {len(models)} models", flush=True)

    # Step 3: Download models with cumulative progress tracking
    results = {}
    success_count = 0
    cumulative_bytes = 0

    for i, model_id in enumerate(models, 1):
        ok, bytes_done = download_model(
            model_id, i, len(models),
            cumulative_bytes, grand_total_bytes,
        )
        results[model_id] = "ok" if ok else "failed"
        if ok:
            success_count += 1
            cumulative_bytes += model_sizes.get(model_id, bytes_done)

    # Step 4: Report results
    print(f"\n=== Results: {success_count}/{len(models)} models downloaded ===", flush=True)
    for model_id, status in results.items():
        marker = "[OK]" if status == "ok" else "[FAIL]"
        print(f"  {marker} {model_id}: {status}", flush=True)

    if success_count == len(models):
        write_marker(args.data_dir, args.tier, results)
        print("PROGRESS: 100% Done!", flush=True)
        print("DONE", flush=True)
        sys.exit(0)
    elif success_count > 0:
        write_marker(args.data_dir, args.tier, results)
        print(f"PARTIAL: {len(models) - success_count} model(s) failed", flush=True)
        sys.exit(1)
    else:
        print("FATAL: No models could be downloaded", flush=True)
        sys.exit(2)


if __name__ == "__main__":
    main()
