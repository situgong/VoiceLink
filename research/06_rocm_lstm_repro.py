# Minimal LSTM-on-cuda repro (small, fast iteration)
import sys
import torch
import torch.nn as nn

print("torch", torch.__version__)
torch.backends.cudnn.enabled = False  # bypass MIOpen RNN kernels
lstm = nn.LSTM(640, 256, batch_first=True, bidirectional=True).cuda().eval()
x = torch.randn(1, 82, 640, device="cuda")
with torch.no_grad():
    out, _ = lstm(x)
torch.cuda.synchronize()
print("LSTM OK:", out.shape, float(out.abs().sum()))
