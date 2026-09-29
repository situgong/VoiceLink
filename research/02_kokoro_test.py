# ============================================================================
# VoiceLink Research - Step 02: Kokoro Neural TTS Test
# ============================================================================
#
# PURPOSE: Generate speech with Kokoro neural TTS and compare it to SAPI voices.
# This demonstrates the quality difference that VoiceLink will bring.
#
# WHAT IS KOKORO?
# - A lightweight neural TTS model (~80MB)
# - Uses a transformer-based architecture
# - Supports multiple voices out of the box
# - Apache 2.0 license (free for commercial use)
# - Fast inference — works great on both CPU and GPU
#
# HOW NEURAL TTS WORKS (simplified):
# 1. Text → Phonemes (linguistic analysis)
# 2. Phonemes → Mel Spectrogram (acoustic model / transformer)
# 3. Mel Spectrogram → Waveform (vocoder / decoder)
#
# The result sounds natural because the model learned from thousands of hours
# of real human speech, capturing rhythm, intonation, and emotion.
# ============================================================================

import time
import soundfile as sf
import numpy as np

print("=" * 60)
print("  VoiceLink Research: Kokoro Neural TTS")
print("=" * 60)

# The text we'll use — same as what we tested with SAPI David
test_text = (
    "Once upon a time, in a land far far away, "
    "there lived a young girl named Alice. "
    "She loved to read books more than anything in the world."
)

print(f"\nTest text: \"{test_text}\"\n")

# --- Load Kokoro ---
print("Loading Kokoro model (first time will download ~80MB)...")
t0 = time.time()

from kokoro import KPipeline

# 'a' = American English. Other options: 'b' = British English, 'j' = Japanese
pipeline = KPipeline(lang_code='a')

load_time = time.time() - t0
print(f"Model loaded in {load_time:.1f}s\n")

# --- List available voices ---
print("--- Available Kokoro Voices ---")
print("Kokoro uses voice codes like 'af_heart', 'am_adam', etc.")
print("  a = American English")
print("  f/m = Female/Male")
print("  The name after _ is the voice style\n")

# --- Generate speech with different voices ---
voices_to_test = [
    ("af_heart", "American Female - Heart (warm, expressive)"),
    ("af_bella", "American Female - Bella (clear, professional)"),
    ("am_adam",  "American Male - Adam (natural, conversational)"),
    ("am_michael", "American Male - Michael (deep, authoritative)"),
]

output_dir = "research/audio_samples"
import os
os.makedirs(output_dir, exist_ok=True)

for voice_id, description in voices_to_test:
    print(f"Generating: {description}...")
    t0 = time.time()
    
    try:
        # Generate audio
        # The pipeline returns a generator of (graphemes, phonemes, audio) tuples
        audio_chunks = []
        for _, _, audio in pipeline(test_text, voice=voice_id):
            audio_chunks.append(audio)
        
        if audio_chunks:
            # Concatenate all chunks
            full_audio = np.concatenate(audio_chunks)
            gen_time = time.time() - t0
            duration = len(full_audio) / 24000  # Kokoro outputs at 24kHz
            
            # Save to WAV file
            filename = f"{output_dir}/kokoro_{voice_id}.wav"
            sf.write(filename, full_audio, 24000)
            
            print(f"  Duration: {duration:.1f}s | Generated in: {gen_time:.2f}s | "
                  f"Speed: {duration/gen_time:.1f}x realtime")
            print(f"  Saved: {filename}\n")
        else:
            print(f"  No audio generated for {voice_id}\n")
            
    except Exception as e:
        print(f"  Error with {voice_id}: {e}\n")

print("=" * 60)
print("  Audio samples saved to research/audio_samples/")
print("  Open them to hear the difference from SAPI David!")
print("=" * 60)

# --- Play the first sample automatically ---
print("\nPlaying af_heart sample...")
try:
    import subprocess
    subprocess.Popen(
        ["powershell", "-c", 
         f'(New-Object Media.SoundPlayer "{output_dir}/kokoro_af_heart.wav").PlaySync()'],
    ).wait()
except Exception as e:
    print(f"Could not auto-play: {e}")
    print("Open the WAV files manually in research/audio_samples/")
