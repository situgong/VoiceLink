# ============================================================================
# VoiceLink — Unit tests for server/models/device_utils.py
# ============================================================================
#
# Torch, torch_directml, and loguru are NOT installed in the test
# environment, so we inject minimal stubs into sys.modules BEFORE importing
# server.models.device_utils (device_utils does `import torch` inside its
# functions, so the stubs must already be in sys.modules at call time).
#
# Run from repo root:
#   python -m unittest server.tests.test_device_utils -v
# ============================================================================

import sys
import types
import unittest


# ---------------------------------------------------------------------------
# Stub construction helpers
# ---------------------------------------------------------------------------

class FakeTorchDevice:
    """Mimics torch.device: torch.device("cpu") -> repr 'cpu'."""

    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return self.name

    def __eq__(self, other):
        return isinstance(other, FakeTorchDevice) and self.name == other.name

    def __hash__(self):
        return hash(self.name)


def make_torch_stub(cuda_available=False, cuda_name="Test CUDA GPU"):
    """Build a minimal torch module stub."""
    torch = types.ModuleType("torch")

    class _Device(FakeTorchDevice):
        pass

    torch.device = _Device

    cuda = types.ModuleType("torch.cuda")
    cuda.is_available = lambda: cuda_available
    cuda.get_device_name = lambda idx=0: cuda_name
    torch.cuda = cuda

    return torch


def make_dml_stub():
    """Build a minimal torch_directml module stub."""
    dml = types.ModuleType("torch_directml")
    dml.test_device = object()  # the private device object
    dml.device_count = lambda: 1
    dml.device = lambda: dml.test_device
    dml.default_device = lambda: 0
    dml.device_name = lambda idx=0: "Test AMD GPU"
    return dml


def make_loguru_stub():
    loguru = types.ModuleType("loguru")
    logger = types.SimpleNamespace(
        warning=lambda *a, **k: None,
        info=lambda *a, **k: None,
        error=lambda *a, **k: None,
        debug=lambda *a, **k: None,
    )
    loguru.logger = logger
    return loguru


# Install a default (no-GPU) torch + loguru before importing device_utils.
sys.modules.setdefault("loguru", make_loguru_stub())
# server/models/__init__.py imports kokoro_model, which needs numpy at
# module level (torch itself is imported lazily inside methods, so the
# torch stub above is enough for it).
sys.modules.setdefault("numpy", types.ModuleType("numpy"))
sys.modules["torch"] = make_torch_stub()
sys.modules.pop("torch_directml", None)

from server.models.device_utils import (  # noqa: E402
    resolve_device,
    current_gpu_summary,
    describe_device,
)


def set_env(torch_stub, dml_stub=None):
    """Point sys.modules at the given stubs (or remove them)."""
    if torch_stub is None:
        sys.modules.pop("torch", None)
    else:
        sys.modules["torch"] = torch_stub
    if dml_stub is None:
        sys.modules.pop("torch_directml", None)
    else:
        sys.modules["torch_directml"] = dml_stub


class ResolveDeviceTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(set_env, make_torch_stub(), None)
        set_env(make_torch_stub(), None)  # default: no cuda, no dml

    # -- cpu ---------------------------------------------------------------

    def test_cpu_spec_returns_cpu(self):
        dev, kind, name = resolve_device("cpu")
        self.assertEqual(kind, "cpu")
        self.assertEqual(dev.name, "cpu")
        self.assertEqual(name, "CPU")

    # -- cuda --------------------------------------------------------------

    def test_cuda_available(self):
        set_env(make_torch_stub(cuda_available=True), None)
        dev, kind, name = resolve_device("cuda")
        self.assertEqual(kind, "cuda")
        self.assertEqual(dev.name, "cuda")
        self.assertEqual(name, "Test CUDA GPU")

    def test_cuda_unavailable_falls_back_to_cpu(self):
        dev, kind, name = resolve_device("cuda")
        self.assertEqual(kind, "cpu")
        self.assertEqual(dev.name, "cpu")

    # -- amd / DirectML ----------------------------------------------------

    def test_amd_with_dml_stub(self):
        torch_stub = make_torch_stub(cuda_available=False)
        dml_stub = make_dml_stub()
        set_env(torch_stub, dml_stub)
        dev, kind, name = resolve_device("amd")
        self.assertEqual(kind, "dml")
        self.assertIs(dev, dml_stub.test_device)
        self.assertIn("Test AMD GPU", name)
        self.assertIn("DirectML", name)

    def test_amd_without_dml_falls_back_to_cpu(self):
        dev, kind, name = resolve_device("amd")
        self.assertEqual(kind, "cpu")
        self.assertEqual(dev.name, "cpu")

    # -- auto --------------------------------------------------------------

    def test_auto_no_gpus_cpu(self):
        dev, kind, name = resolve_device("auto")
        self.assertEqual(kind, "cpu")
        self.assertEqual(dev.name, "cpu")
        self.assertEqual(name, "CPU")

    def test_auto_prefers_cuda_over_dml(self):
        set_env(make_torch_stub(cuda_available=True), make_dml_stub())
        dev, kind, name = resolve_device("auto")
        self.assertEqual(kind, "cuda")

    def test_auto_uses_dml_when_no_cuda(self):
        dml_stub = make_dml_stub()
        set_env(make_torch_stub(cuda_available=False), dml_stub)
        dev, kind, name = resolve_device("auto")
        self.assertEqual(kind, "dml")
        self.assertIs(dev, dml_stub.test_device)

    # -- invalid spec --------------------------------------------------------

    def test_invalid_spec_treated_as_auto(self):
        # "gpu" is not a valid spec -> warned, treated as auto -> cpu here
        dev, kind, name = resolve_device("gpu")
        self.assertEqual(kind, "cpu")
        self.assertEqual(dev.name, "cpu")

    def test_invalid_spec_with_cuda_available(self):
        set_env(make_torch_stub(cuda_available=True), None)
        dev, kind, name = resolve_device("gpu")
        self.assertEqual(kind, "cuda")  # auto behavior


class GpuSummaryTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(set_env, make_torch_stub(), None)
        set_env(make_torch_stub(), None)

    def test_summary_cuda(self):
        set_env(make_torch_stub(cuda_available=True), None)
        avail, name = current_gpu_summary()
        self.assertTrue(avail)
        self.assertEqual(name, "Test CUDA GPU")

    def test_summary_dml(self):
        set_env(make_torch_stub(cuda_available=False), make_dml_stub())
        avail, name = current_gpu_summary()
        self.assertTrue(avail)
        self.assertEqual(name, "Test AMD GPU")

    def test_summary_neither(self):
        avail, name = current_gpu_summary()
        self.assertFalse(avail)
        self.assertIsNone(name)


class DescribeDeviceTests(unittest.TestCase):
    def test_describe(self):
        set_env(make_torch_stub(), None)
        self.assertEqual(describe_device("cpu"), "cpu (CPU)")


if __name__ == "__main__":
    unittest.main()
