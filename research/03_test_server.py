# ============================================================================
# VoiceLink Research - Step 03: Test the Inference Server
# ============================================================================
#
# PURPOSE: Send requests to the running VoiceLink server and verify
# that all endpoints work correctly. Saves TTS output as playable WAV files.
#
# WHY CAN'T SWAGGER PLAY THE AUDIO?
# Our /v1/tts endpoint returns raw PCM bytes (no header).
# A browser audio player needs a WAV file, which has a 44-byte header
# describing the format (sample rate, bit depth, channels).
# Raw PCM is just numbers — the player doesn't know how to decode them.
#
# This script adds the WAV header after downloading the PCM stream,
# making it a playable file.
#
# HOW TO RUN:
#   1. Make sure the server is running (python -m server.main)
#   2. Run this script: python research/03_test_server.py
# ============================================================================

import requests
import struct
import wave
import time
import os
import sys

SERVER = "http://127.0.0.1:7860"

def test_health():
    """Test GET /v1/health"""
    print("=" * 60)
    print("  Test 1: Health Check")
    print("=" * 60)
    
    try:
        r = requests.get(f"{SERVER}/v1/health", timeout=5)
        data = r.json()
        print(f"  Status:       {r.status_code}")
        print(f"  Model:        {data.get('model')}")
        print(f"  Model loaded: {data.get('model_loaded')}")
        print(f"  GPU:          {data.get('gpu_available')} ({data.get('gpu_name', 'N/A')})")
        print(f"  Uptime:       {data.get('uptime_seconds', 0):.0f}s")
        print()
        return data.get("model_loaded", False)
    except requests.ConnectionError:
        print("  ERROR: Cannot connect to server. Is it running?")
        print(f"  Expected at: {SERVER}")
        return False


def test_voices():
    """Test GET /v1/voices"""
    print("=" * 60)
    print("  Test 2: List Voices")
    print("=" * 60)
    
    r = requests.get(f"{SERVER}/v1/voices", timeout=5)
    voices = r.json()
    print(f"  Found {len(voices)} voices:\n")
    
    for v in voices:
        gender_icon = "♀" if v["gender"] == "female" else "♂"
        print(f"    {gender_icon} {v['id']:20s}  {v['name']:12s}  {v['language']}  {v['description']}")
    
    print()
    return voices


def test_tts(text: str, voice: str = "af_heart", filename: str = "test_output.wav"):
    """
    Test POST /v1/tts — synthesize text and save as WAV.
    
    This is the critical test: does the full pipeline work?
      Text → HTTP request → Kokoro model → PCM stream → WAV file
    """
    print("=" * 60)
    print(f"  Test 3: Text-to-Speech")
    print("=" * 60)
    print(f"  Voice: {voice}")
    print(f"  Text:  \"{text}\"")
    print()
    
    # --- Send TTS request (streaming) ---
    t0 = time.perf_counter()
    
    r = requests.post(
        f"{SERVER}/v1/tts",
        json={
            "text": text,
            "voice": voice,
            "speed": 1.0,
            "format": "pcm_24k_16bit",
        },
        stream=True,  # Important: read response as it arrives
        timeout=30,
    )
    
    if r.status_code != 200:
        print(f"  ERROR: Server returned {r.status_code}")
        print(f"  {r.text}")
        return
    
    # --- Read the PCM stream chunk by chunk ---
    # This simulates what the COM DLL will do: read chunks and pipe to SAPI.
    pcm_data = bytearray()
    chunk_count = 0
    first_chunk_time = None
    
    for chunk in r.iter_content(chunk_size=8192):
        if chunk:
            if first_chunk_time is None:
                first_chunk_time = time.perf_counter()
            pcm_data.extend(chunk)
            chunk_count += 1
    
    total_time = time.perf_counter() - t0
    ttfb = (first_chunk_time - t0) if first_chunk_time else 0
    
    # --- Audio stats ---
    sample_rate = 24000
    sample_width = 2  # 16-bit = 2 bytes
    channels = 1
    audio_duration = len(pcm_data) / (sample_rate * sample_width * channels)
    
    print(f"  Response headers:")
    print(f"    Content-Type:  {r.headers.get('content-type')}")
    print(f"    Sample Rate:   {r.headers.get('x-audio-sample-rate')} Hz")
    print(f"    Sample Width:  {r.headers.get('x-audio-sample-width')} bit")
    print(f"    Channels:      {r.headers.get('x-audio-channels')}")
    print()
    print(f"  Results:")
    print(f"    PCM bytes:     {len(pcm_data):,}")
    print(f"    Audio duration: {audio_duration:.2f}s")
    print(f"    HTTP chunks:   {chunk_count}")
    print(f"    Time to first byte: {ttfb * 1000:.0f}ms")
    print(f"    Total time:    {total_time:.2f}s")
    print(f"    Realtime factor: {audio_duration / total_time:.1f}x")
    print()
    
    if len(pcm_data) == 0:
        print("  WARNING: No audio data received!")
        return
    
    # --- Save as WAV ---
    # WAV = 44-byte header + raw PCM data
    # The header tells audio players: "this is 24kHz, 16-bit, mono audio"
    output_dir = "research/audio_samples"
    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, filename)
    
    with wave.open(filepath, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(bytes(pcm_data))
    
    print(f"  Saved: {filepath}")
    print(f"  (Open this file to hear the output!)")
    print()
    
    return filepath


def test_tts_multiple_voices(text: str):
    """Test TTS with several voices to compare."""
    print("=" * 60)
    print("  Test 4: Multiple Voices Comparison")
    print("=" * 60)
    print()
    
    voices = ["af_heart", "am_adam", "bf_emma", "bm_george"]
    
    for voice in voices:
        print(f"  Generating with {voice}...")
        t0 = time.perf_counter()
        
        r = requests.post(
            f"{SERVER}/v1/tts",
            json={"text": text, "voice": voice},
            stream=True,
            timeout=30,
        )
        
        pcm_data = bytearray()
        for chunk in r.iter_content(chunk_size=8192):
            if chunk:
                pcm_data.extend(chunk)
        
        elapsed = time.perf_counter() - t0
        duration = len(pcm_data) / (24000 * 2)
        
        filepath = f"research/audio_samples/server_{voice}.wav"
        with wave.open(filepath, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            wf.writeframes(bytes(pcm_data))
        
        print(f"    {duration:.1f}s audio in {elapsed:.1f}s → {filepath}")
    
    print()
    print("  Done! Compare the WAV files in research/audio_samples/")
    print()


if __name__ == "__main__":
    print("\n🔗 VoiceLink Server Test Suite\n")
    
    # Test 1: Health
    healthy = test_health()
    if not healthy:
        print("Server not ready. Exiting.")
        sys.exit(1)
    
    # Test 2: Voices
    voices = test_voices()
    
    # Test 3: Single TTS
    test_tts(
        text=(
            "Once upon a time, in a land far far away, "
            "there lived a young girl named Alice. "
            "She loved to read books more than anything in the world."
        ),
        voice="af_heart",
        filename="server_test.wav",
    )
    
    # Test 4: Multiple voices
    test_tts_multiple_voices(
        "The quick brown fox jumps over the lazy dog. "
        "VoiceLink brings AI powered voices to every Windows application."
    )
    
    print("=" * 60)
    print("  All tests complete!")
    print("=" * 60)
