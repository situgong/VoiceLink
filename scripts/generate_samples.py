"""Generate audio samples for README voice comparison."""
import struct
import wave
import urllib.request
import json
import os

VOICES = [
    "af_heart",
    "af_bella",
    "af_nicole",
    "am_adam",
    "am_michael",
    "bf_emma",
    "bm_george",
]

SAMPLE_TEXT = (
    "The old bookshop on the corner had a peculiar charm about it. "
    "Dust motes danced in the sunlight that streamed through tall windows, "
    "and the smell of aged paper filled every room. "
    "It was the kind of place where you could lose an entire afternoon "
    "without even noticing."
)

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "audio")
os.makedirs(OUTPUT_DIR, exist_ok=True)

SAMPLE_RATE = 24000
SAMPLE_WIDTH = 2  # 16-bit
CHANNELS = 1

for voice in VOICES:
    print(f"Generating sample for {voice}...")
    payload = json.dumps({
        "text": SAMPLE_TEXT,
        "voice": voice,
        "speed": 1.0,
        "format": "pcm_24k_16bit",
    }).encode()

    req = urllib.request.Request(
        "http://127.0.0.1:7860/v1/tts",
        data=payload,
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            pcm_data = resp.read()

        wav_path = os.path.join(OUTPUT_DIR, f"{voice}.wav")
        with wave.open(wav_path, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(SAMPLE_WIDTH)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(pcm_data)

        size_kb = os.path.getsize(wav_path) / 1024
        duration = len(pcm_data) / (SAMPLE_RATE * SAMPLE_WIDTH * CHANNELS)
        print(f"  -> {wav_path} ({size_kb:.0f} KB, {duration:.1f}s)")
    except Exception as e:
        print(f"  ERROR for {voice}: {e}")

print("\nDone!")
