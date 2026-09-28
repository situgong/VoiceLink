# ============================================================================
# VoiceLink — Device Selection Utilities
# ============================================================================
#
# WHY THIS EXISTS:
# The user may want to run inference on:
#   - CPU              (always works, no extra deps)
#   - NVIDIA GPU       (PyTorch CUDA — comes with the standard torch wheel)
#   - AMD GPU          (torch-directml on Windows — Microsoft's DirectML
#                        backend for PyTorch; works with any DX12-capable
#                        GPU, including AMD Radeon and Intel Arc)
#
# On Windows, AMD GPUs cannot use CUDA or ROCm, so torch-directml is the
# only practical PyTorch backend for them. The torch-directml package
# exposes a *private device object* (not a string like "cuda"), so we wrap
# it here so model code never has to care.
#
# USAGE:
#   from server.models.device_utils import resolve_device, describe_device
#
#   device, kind, name = resolve_device("amd")   # or "auto"/"cuda"/"cpu"
#   model.to(device)
#
# The resolved device is passed to KModel/KPipeline. "kind" is one of
# "cpu" | "cuda" | "dml" and is safe to report in /v1/health.
# ============================================================================

from loguru import logger

# Valid values for the VOICELINK_MODEL__DEVICE setting
DEVICE_OPTIONS = ("auto", "cpu", "cuda", "amd")


def _dml_device():
    """
    Import torch-directml and return its device object.

    Returns None if torch-directml is not installed or reports no
    usable adapters.
    """
    try:
        import torch_directml  # pip install torch-directml
    except ImportError:
        return None
    try:
        if torch_directml.device_count() < 1:
            return None
        return torch_directml.device()
    except Exception as e:
        logger.warning(f"torch-directml present but unusable: {e}")
        return None


def _dml_device_name() -> str | None:
    """Best-effort friendly name for the DirectML adapter."""
    try:
        import torch_directml
        idx = torch_directml.default_device()
        return torch_directml.device_name(idx)
    except Exception:
        return "DirectML GPU"


def resolve_device(spec: str = "auto"):
    """
    Resolve a device spec into a concrete torch device.

    Args:
        spec: 'auto' | 'cpu' | 'cuda' | 'amd'

    Returns:
        (device, kind, name) where:
          device — a torch.device or torch_directml device object
          kind   — 'cpu' | 'cuda' | 'dml' (stable label for health/API)
          name   — human-readable description for logs

    Fallback policy (with a warning log, never a crash):
        cuda → cpu if torch has no CUDA build / no NVIDIA GPU
        amd  → cpu if torch-directml is not installed or no adapter
        auto → cuda, else dml, else cpu
    """
    import torch

    spec = (spec or "auto").strip().lower()
    if spec not in DEVICE_OPTIONS:
        logger.warning(
            f"Unknown device spec '{spec}'. Valid: {DEVICE_OPTIONS}. Using 'auto'."
        )
        spec = "auto"

    if spec == "cpu":
        return torch.device("cpu"), "cpu", "CPU"

    if spec in ("cuda", "auto"):
        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            return torch.device("cuda"), "cuda", name
        if spec == "cuda":
            logger.warning(
                "CUDA requested but torch.cuda.is_available() is False "
                "(no NVIDIA GPU or CPU-only torch build). Falling back to CPU."
            )
            return torch.device("cpu"), "cpu", "CPU"
        # spec == 'auto': try DirectML next

    # spec in ('amd', 'auto')
    dml = _dml_device()
    if dml is not None:
        dml_name = _dml_device_name() or "DirectML GPU"
        return dml, "dml", f"{dml_name} (DirectML)"
    if spec == "amd":
        logger.warning(
            "AMD GPU requested but torch-directml is unavailable. "
            "Fix: pip install torch-directml  (requires torch<2.9 on Windows). "
            "Falling back to CPU."
        )
    return torch.device("cpu"), "cpu", "CPU"


def describe_device(spec: str = "auto") -> str:
    """One-line description for startup logs, without changing anything."""
    _, kind, name = resolve_device(spec)
    return f"{kind} ({name})"


def current_gpu_summary() -> tuple[bool, str | None]:
    """
    Report GPU availability for the /v1/health endpoint.

    Returns (gpu_available, gpu_name) covering CUDA and DirectML,
    not just torch.cuda.
    """
    import torch

    if torch.cuda.is_available():
        return True, torch.cuda.get_device_name(0)
    dml = _dml_device()
    if dml is not None:
        return True, (_dml_device_name() or "DirectML GPU")
    return False, None
