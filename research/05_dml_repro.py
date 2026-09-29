# Minimal repro: kokoro KModel forward on DirectML — find which op breaks.
import torch
import torch_directml

dml = torch_directml.device()
print("DML device:", torch_directml.device_name(0))

from kokoro import KModel, KPipeline

model = KModel()
model.to(dml).eval()
print("model on:", model.device)

pipe = KPipeline(lang_code="a", model=model)

for i, (gs, ps, audio) in enumerate(pipe("Hello world test.", voice="af_heart", speed=1.0)):
    print(f"chunk {i}: gs={gs!r} ps={ps!r} audio={'OK ' + str(type(audio)) if audio is not None else None}")
    if i > 2:
        break
print("PIPELINE OK")
