# ============================================================================
# VoiceLink — DirectML (AMD GPU) Compatibility Shim
# ============================================================================
#
# WHY THIS EXISTS:
# AMD GPUs cannot use CUDA (NVIDIA-only) and ROCm does not ship for Windows,
# so torch-directml (Microsoft's DirectML backend) is the only way to run
# PyTorch on an AMD GPU on Windows. But DirectML's operator coverage is
# incomplete: nn.LSTM uses the fused `aten::_thnn_fused_lstm_cell` kernel,
# which DirectML does not implement. Its CPU-fallback path then fails with
# "Could not run 'aten::_thnn_fused_lstm_cell' with arguments from the
# 'CPU' backend" because the tensors still live on the DML device.
#
# Kokoro's KModel needs exactly ONE LSTM layer:
#   predictor.lstm: LSTM(640 -> 256, batch_first=True, bidirectional=True)
#   called plainly as:  x, _ = self.predictor.lstm(d)   (model.py:106)
# — no PackedSequence, no multi-layer, no dropout at inference.
#
# THE FIX:
# Replace nn.LSTM.forward with a manual recurrence built ONLY from ops that
# DirectML supports (matmul, sigmoid, tanh, concat, flip). Numerically this
# is the standard LSTM equations — same math as the fused kernel.
#
# The patch is installed ONLY when the model runs on a DirectML device
# (see install_dml_lstm_patch() / KokoroModel.load()); CPU and CUDA paths
# never touch it, so their behavior is byte-identical.
# ============================================================================

import torch
import torch.nn as nn
from loguru import logger

# The original forward, so we only divert DML tensors
_original_lstm_forward = nn.LSTM.forward


def _lstm_cell_step(x_t, hx, cx, w_ih, w_hh, b_ih, b_hh):
    """One LSTM cell step, using only DML-safe primitive ops."""
    gates = x_t @ w_ih.T + b_ih + (hx @ w_hh.T + b_hh)
    i, f, g, o = gates.chunk(4, dim=1)
    i, f, g, o = torch.sigmoid(i), torch.sigmoid(f), torch.tanh(g), torch.sigmoid(o)
    cy = f * cx + i * g
    hy = o * torch.tanh(cy)
    return hy, cy


def _dml_safe_lstm_forward(self, input, hx=None):
    """
    Drop-in nn.LSTM.forward replacement for DirectML devices.

    Supports the exact subset Kokoro uses:
      - input (batch, seq, features) [batch_first=True] or (seq, batch, features)
      - single layer, bidirectional or unidirectional
      - no PackedSequence, no dropout (inference), no initial hx needed
    Returns (output, (h_n, c_n)) shaped like nn.LSTM does.
    """
    is_dml = input.device.type == "privateuseone"
    if not is_dml:
        # Non-DML tensors: defer to the stock implementation (CPU/CUDA fast path)
        return _original_lstm_forward(self, input, hx)

    batch_first = self.batch_first
    bidirectional = self.bidirectional

    if batch_first:
        x = input.transpose(0, 1)  # -> (seq, batch, features)
    else:
        x = input

    seq_len, batch_size, _ = x.shape

    if hx is not None:
        h0, c0 = hx
    else:
        h0 = x.new_zeros((self.num_layers, batch_size, self.hidden_size))
        c0 = x.new_zeros((self.num_layers, batch_size, self.hidden_size))

    def run_direction(w_ih, w_hh, b_ih, b_hh, h_dir, c_dir, direction_input):
        outputs = []
        steps = direction_input if not isinstance(direction_input, bool) else None
        hx_, cx_ = h_dir[0], c_dir[0]
        for t in range(seq_len):
            x_t = direction_input[t]
            hx_, cx_ = _lstm_cell_step(x_t, hx_, cx_, w_ih, w_hh, b_ih, b_hh)
            outputs.append(hx_)
        return torch.stack(outputs, dim=0), hx_, cx_

    # --- forward direction (weights slice [0]) ---
    out_f, h_f, c_f = run_direction(
        self.weight_ih_l0, self.weight_hh_l0,
        self.bias_ih_l0, self.bias_hh_l0,
        h0, c0, x,
    )

    if bidirectional:
        # --- backward direction (weights slice reversed) ---
        x_rev = torch.flip(x, dims=[0])
        out_b_rev, h_b, c_b = run_direction(
            self.weight_ih_l0_reverse, self.weight_hh_l0_reverse,
            self.bias_ih_l0_reverse, self.bias_hh_l0_reverse,
            h0, c0, x_rev,
        )
        out_b = torch.flip(out_b_rev, dims=[0])
        output = torch.cat([out_f, out_b], dim=2)
        h_n = torch.stack([h_f, h_b], dim=0)
        c_n = torch.stack([c_f, c_b], dim=0)
    else:
        output = out_f
        h_n = h_f.unsqueeze(0)
        c_n = c_f.unsqueeze(0)

    if batch_first:
        output = output.transpose(0, 1)

    return output, (h_n, c_n)


def install_dml_lstm_patch() -> None:
    """
    Install the DML-safe LSTM forward on nn.LSTM.

    The replacement itself checks the input device: CPU/CUDA tensors go to
    the stock kernel untouched, only privateuseone (DirectML) tensors take
    the manual recurrence — so installing it globally is safe.
    """
    if getattr(nn.LSTM.forward, "_voicelink_dml_patched", False):
        return
    nn.LSTM.forward = _dml_safe_lstm_forward
    nn.LSTM.forward._voicelink_dml_patched = True  # type: ignore[attr-defined]
    logger.info(
        "Installed DML-safe LSTM forward (manual recurrence) — "
        "DirectML lacks the fused LSTM kernel; CPU/CUDA paths unchanged."
    )
