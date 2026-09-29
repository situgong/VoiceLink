"""Test faster-qwen3-tts CustomVoice (built-in speakers)."""
import os, sys, io, time, torch, warnings, logging

warnings.filterwarnings("ignore")
os.environ["TRANSFORMERS_NO_ADVISORY_WARNINGS"] = "1"
logging.getLogger("sox").setLevel(logging.CRITICAL)

_fd = os.dup(2); _nul = os.open(os.devnull, os.O_WRONLY); os.dup2(_nul, 2)
try: import sox
except: pass
os.dup2(_fd, 2); os.close(_fd); os.close(_nul)

from faster_qwen3_tts import FasterQwen3TTS

TEST_TEXT = "Hello, how are you doing today? I hope you are having a wonderful time."

print("=" * 60)
print("TEST: FasterQwen3TTS CustomVoice (built-in speakers)")
print("=" * 60)

print("Loading 0.6B-CustomVoice with CUDA graphs...")
t0 = time.perf_counter()
model = FasterQwen3TTS.from_pretrained("Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice")
print(f"Loaded in {time.perf_counter()-t0:.1f}s")

# Warmup (triggers CUDA graph capture)
print("Warmup + CUDA graph capture...")
t0 = time.perf_counter()
wavs, sr = model.generate_custom_voice(text="Hi.", speaker="serena", language="English")
print(f"Warmup done in {time.perf_counter()-t0:.1f}s")

# Second warmup
wavs, sr = model.generate_custom_voice(text="Test.", speaker="serena", language="English")

# Test each speaker
for speaker in ["serena", "aiden", "ryan"]:
    print(f'\n[{speaker}] Generating: "{TEST_TEXT}"')
    t0 = time.perf_counter()
    wavs, sr = model.generate_custom_voice(
        text=TEST_TEXT, speaker=speaker, language="English",
    )
    elapsed = time.perf_counter() - t0
    audio_dur = len(wavs[0]) / sr
    rtf = audio_dur / elapsed
    print(f"  Time:  {elapsed:.2f}s | Audio: {audio_dur:.2f}s | RTF: {rtf:.2f}x")

print(f"\nVRAM: {torch.cuda.max_memory_allocated()/1e9:.2f} GB")
print("DONE")
