# Local AI TTS on Windows — and Making Chrome Actually Use It

> Experience notes from 2026-09-28. Goal: run a **local, offline AI TTS voice** on Windows, have it show up as a
> normal system voice, and use it for reading pages in the browser — including **Google Chrome**, which is the
> stubborn one.
>
> The journey in three lines:
> 1. Install **VoiceLink** → local Kokoro TTS is exposed to Windows as standard **SAPI** voices.
> 2. SAPI-aware apps can now speak it — **Edge sees the voices out of the box**.
> 3. **Chrome does not** — it needs a small registry bridge (`SAPI → OneCore`) plus a full restart. After that,
>    extensions like **Speechify** (or any extension using the browser's local voices) can read with your AI voice.

---

## Background: the three voice worlds on Windows

Before touching anything, it helps to know why this is confusing. Windows has (at least) three voice pipelines:

| Pipeline | Registry hive | Who reads it |
|---|---|---|
| **Legacy SAPI 5** (desktop COM) | `HKLM\SOFTWARE\Microsoft\Speech\Voices\Tokens` | Classic desktop apps (Balabolka, Narrator, older tools) |
| **OneCore / WinRT** (modern) | `HKLM\SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens` | Modern apps; what recent Chromium/Chrome enumerates |
| **Edge cloud catalog** | n/a (online) | Edge only — 250+ "Natural" neural voices streamed from Microsoft's cloud |

- **Edge** is Microsoft's browser on Microsoft's OS: it deliberately queries **both** local pipelines *and* injects
  its online cloud voices. Maximum voice availability by design.
- **Chrome** is plain Chromium: it enumerates the **modern OneCore voice store**, and ignores voices that only
  exist in the legacy SAPI 5 hive. It has no access to Microsoft's cloud voices either.

This asymmetry is exactly why a freshly installed SAPI voice shows up in Edge but is invisible in Chrome.
Chrome's Windows TTS implementation lives in `content/browser/speech/tts_win.cc` in the Chromium tree
(see [chromium.googlesource.com](https://chromium.googlesource.com/chromium/src/+/main/content/browser/speech/tts_win.cc))
if you want to see it yourself.

---

## Step 1 — Install VoiceLink (local AI TTS exposed as SAPI voices)

**VoiceLink** ([github.com/ManveerAnand/VoiceLink](https://github.com/ManveerAnand/VoiceLink), MIT license)
makes local AI voices look like ordinary Windows voices. Architecture:

```
┌──────────────────────┐   HTTP (localhost:7860)   ┌─────────────────────────┐
│ voicelink_sapi.dll   │ ────────────────────────▶ │ FastAPI inference server │
│ (COM DLL, ISpTTSEngine)│   POST /v1/tts          │ Python + Kokoro v1.0 ONNX│
│ loads into any SAPI  │ ◀──────────────────────── │ (CPU-friendly, 82M params)│
│ app in-process       │   24kHz 16-bit PCM        └─────────────────────────┘
└──────────────────────┘                           managed by a Tauri GUI (tray)
        ▲
        │ voice tokens registered in the Windows registry
┌─────────────────────────────────────────────────────────────────────────────┐
│ HKLM\SOFTWARE\Microsoft\Speech\Voices\Tokens\VoiceLink_af_heart  (SAPI 5)    │
│ HKLM\SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens\...        (OneCore)   │
└─────────────────────────────────────────────────────────────────────────────┘
```

The TTS engine is **Kokoro** (Apache 2.0) running fully locally — no API key, no network calls for synthesis.
An optional Qwen3-TTS add-on (NVIDIA GPU required) adds voice cloning; not needed for this guide.

### Installation walkthrough

1. Download `VoiceLink_0.1.0_x64-setup.exe` (~2.8 MB NSIS installer) from the
   [releases page](https://github.com/ManveerAnand/VoiceLink/releases).
   Requirements: Windows 10/11 x64, ~1.5 GB free disk, admin rights.
2. **Run the installer as Administrator.** It copies the GUI + COM DLL + server source to
   `C:\Program Files\VoiceLink\` and runs `regsvr32 /s` on the COM DLL(s) — this is what needs elevation.
3. Launch the GUI. The **first-run setup wizard** does everything else (grab a coffee, it's ~1.3 GB of downloads):
   - Step 1: downloads an **embedded Python 3.11.9** into `C:\ProgramData\VoiceLink\python\` (no system Python touched)
   - Step 2: `pip install` of FastAPI / Kokoro / PyTorch etc. (~900 MB, 5–10 min, live progress in the GUI)
   - Step 3: copies the TTS server to `C:\ProgramData\VoiceLink\server\`
   - Step 4: downloads `kokoro-v1.0.onnx` (310 MB) + `voices-v1.0.bin` (27 MB)
   - Step 5: starts the server and waits for `http://localhost:7860/v1/health` to answer
4. In the **Voice Manager**, toggle on the voices you want. Each enabled voice registers a token
   (e.g. `VoiceLink_af_heart`) in **both** the SAPI 5 and OneCore hives, plus their `WOW6432Node` variants
   for 32-bit apps.

You get **11 English voices** (displayed as `VoiceLink - Heart`, etc.):

| Voice ID | Name | Language / gender |
|---|---|---|
| `af_heart`, `af_bella`, `af_nicole`, `af_sarah`, `af_sky` | Heart, Bella, Nicole, Sarah, Sky | en-US, female |
| `am_adam`, `am_michael` | Adam, Michael | en-US, male |
| `bf_emma`, `bf_isabella` | Emma, Isabella | en-GB, female |
| `bm_george`, `bm_lewis` | George, Lewis | en-GB, male |

### What lives where (cheat sheet)

| Item | Path / value |
|---|---|
| App + COM DLL | `C:\Program Files\VoiceLink\` |
| Data (models, embedded Python, server) | `C:\ProgramData\VoiceLink\` — **survives uninstall/reinstall** |
| Config | `C:\ProgramData\VoiceLink\config.json` (`server_port: 7860`, `auto_start`, …) |
| Health check | `http://localhost:7860/v1/health` |
| Voice list | `http://localhost:7860/v1/voices` |

### Verify at the OS level

- Open the VoiceLink GUI → the dashboard should show the server **running**.
- Click **Test** on a voice card — the GUI previews audio directly through the server.
- Any classic SAPI app (e.g. Windows Narrator, Balabolka) should now list `VoiceLink - Heart` in its voice picker.

---

## Step 2 — SAPI-aware apps: Edge just works

Open a page in **Edge → Read Aloud**. Open the voice dropdown: the VoiceLink voices appear among the
local voices (below Edge's cloud "Natural" voices — pick the VoiceLink one explicitly, Edge defaults to
its online voices). No extra setup needed, because Edge queries both the SAPI and OneCore pipelines.

Documented as working by the VoiceLink project: Edge Read Aloud, Thorium Reader, Narrator, Balabolka.

---

## Step 3 — The Chrome problem

**Symptom:** `speechSynthesis.getVoices()` in Chrome does not list the VoiceLink voices, while Edge
shows them fine. The voice simply does not exist as far as Chrome is concerned.

**Why:** Chrome (plain Chromium) enumerates Windows voices from the **OneCore voice store**
(`Speech_OneCore\Voices\Tokens`), not from the legacy SAPI 5 hive — and unlike Edge it won't check both.
If your voice tokens are missing (or stale) in the OneCore hive, Chrome can't see them.

Two Chrome quirks make this look even flakier than it is:

- Chrome **caches the voice list at startup**. Voices registered while Chrome is running never appear,
  no matter how many times you reload the page. A *full* restart is required.
- `getVoices()` is **asynchronous** — it may return `[]` at first and only fill in after the
  `voiceschanged` event fires. Always test with the snippet below, not with a single call.

---

## Step 4 — The fix: mirror SAPI tokens into OneCore, restart Chrome

Even though VoiceLink registers both hives, in practice Chrome still didn't show the voices until the
tokens were explicitly mirrored and Chrome was fully restarted. Belt and braces:

1. Press the Windows key, type `powershell`, right-click **Windows PowerShell** → **Run as Administrator**.
2. Mirror the 64-bit SAPI tokens into the OneCore hive:

   ```powershell
   reg copy "HKLM\SOFTWARE\Microsoft\Speech\Voices\Tokens" "HKLM\SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens" /s /f
   ```

3. (If your voice was installed as a 32-bit voice on 64-bit Windows) mirror the 32-bit tokens too:

   ```powershell
   reg copy "HKLM\SOFTWARE\WOW6432Node\Microsoft\Speech\Voices\Tokens" "HKLM\SOFTWARE\WOW6432Node\Microsoft\Speech_OneCore\Voices\Tokens" /s /f
   ```

4. Fully restart Chrome: type `chrome://restart` in the address bar (or quit completely and relaunch).
5. Verify — open DevTools (F12) on any page and run:

   ```js
   speechSynthesis.onvoiceschanged = () =>
     console.log(speechSynthesis.getVoices().map(v => `${v.name} [${v.lang}]`));
   console.log(speechSynthesis.getVoices().filter(v => v.name.includes('VoiceLink')));
   ```

   You should see the `VoiceLink - …` entries. Quick speak test:

   ```js
   const u = new SpeechSynthesisUtterance('Hello from my local AI voice.');
   u.voice = speechSynthesis.getVoices().find(v => v.name.includes('VoiceLink'));
   speechSynthesis.speak(u);
   ```

**Caveats:**

- These are `HKLM` writes — admin rights required, same as VoiceLink's own voice toggling.
- The copy is "as of now". If you later enable/disable voices in VoiceLink or change the server port,
  re-check that Chrome still sees them (VoiceLink rewrites both hives on toggle, but re-running the
  mirror + `chrome://restart` is the reliable reset).
- A major Windows update can rebuild the voice store and drop mirrored tokens — just re-run the commands.
- If you uninstall VoiceLink, the mirrored copies in OneCore can outlive the SAPI originals (ghost voices
  that produce silence). Delete the `VoiceLink_*` token keys manually if that happens.

---

## Step 5 — Actually using it in Chrome: extensions

Chrome itself only exposes the voices through the Web Speech API, so for day-to-day "read this page
aloud" you use an extension that speaks via the browser's local voices:

- **Speechify** — my pick. In its voice settings, choose the local/system voice option and select
  `VoiceLink - Heart` (or any of the 11). Note Speechify pushes its own cloud voices by default —
  make sure you pick the *system/device* voice, not a Speechify cloud voice.
- **Read Aloud: A Text to Speech Voice Reader** — free alternative; it lists `speechSynthesis` voices
  directly, so VoiceLink voices appear immediately after Step 4.
- Any other extension whose voice picker is backed by `speechSynthesis.getVoices()` will work.

Extensions with their own cloud TTS (and no system-voice option) will never see your local voices —
that's an extension limitation, not a Chrome one.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Voice listed but **silence** when speaking | Inference server down (DLL degrades to silence, no error) | Check `http://localhost:7860/v1/health`; start server from VoiceLink GUI/tray |
| Voice missing in **Chrome** only | OneCore hive not populated / Chrome cached old list | Step 4 mirror + `chrome://restart` |
| `getVoices()` returns `[]` | Async quirk, not a bug | Wait for `voiceschanged` (snippet in Step 4) |
| Voice missing in **Edge** too | Voice disabled in Voice Manager, or COM DLL not registered | Re-toggle voice in GUI (as admin) / reinstall as admin (`regsvr32` needs elevation) |
| First utterance is slow (a few seconds) | Kokoro model cold-load on CPU | Normal; subsequent utterances are fast |
| Changed `server_port` in config.json, now silence | Registry token `VoiceLinkServerPort` no longer matches | Re-toggle the voices in the GUI so tokens get rewritten |
| Voices disappeared after a Windows update | Voice store rebuilt | Re-run the Step 4 mirror commands |

---

## Lessons learned

1. **"Works in Edge" proves nothing about Chrome.** They share Chromium's rendering but have completely
   different Windows voice integrations. Test both.
2. **Chrome needs a full restart** to pick up registry voice changes — page reloads do nothing, and
   `getVoices()` lies on first call. This combination accounts for most "my voice is invisible" reports.
3. **Bridging the hives is the universal trick.** SAPI 5 vs OneCore is the split; making sure tokens exist
   in *both* hives makes every app happy.
4. **A local AI voice is a service, not a file.** The COM DLL is just a proxy — if the localhost:7860 server
   isn't running, apps get silence instead of an error. Keep the tray app running (`auto_start: true`).
5. Total cost: ~1.3 GB disk, fully offline synthesis, CPU-only is fine, and the uninstaller preserves the
   model cache so re-installing doesn't re-download everything.
