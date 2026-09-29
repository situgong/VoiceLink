# Device Selection for Kokoro TTS (CPU / NVIDIA CUDA / AMD DirectML / Auto)

## Goal

Let the user choose which device Kokoro TTS runs on — CPU, NVIDIA GPU (CUDA), or AMD GPU
(DirectML on Windows) — plus an Auto mode (CUDA → DirectML → CPU). The setting is
configurable via `VOICELINK_MODEL__DEVICE` (values `auto`/`cpu`/`cuda`/`amd`, default
`auto`), selectable in the GUI Settings page, and accurately reported by `/v1/health`
including the device **actually in use** after resolution. Invalid or unavailable
selections fall back to CPU with a logged warning — never a crash. Scope: Windows, this
project. Qwen3 remains CUDA-only (out of scope). Verification level: "works is enough".

## Approach

A substantial part of the server-side groundwork already exists uncommitted in the tree
(`device_utils.py`, `device=` kwarg in `KokoroModel`, `device` config field, health GPU
summary). This design treats that code as existing code to review/fix, not rewrite. The
remaining work is four items:

### 1. server-health-field — expose the actual device in `/v1/health`

**Gap:** `HealthResponse` (server/routers/tts.py:86-94) has `gpu_available`/`gpu_name`
but no field for the device kind actually in use. `current_gpu_summary()` reports what
GPUs exist, not what the model was loaded on.

- Add to `HealthResponse`:
  - `device_kind: str | None` — `"cpu" | "cuda" | "dml"` (the resolved kind), and
  - `device_name: str | None` — human-readable name of the resolved device.
- Capture resolved device at model load time:
  - Preferred: `KokoroModel.load()` already computes `(torch_device, kind, device_name)`
    via `resolve_device` (server/models/kokoro_model.py:183). Store these on the model
    (`self._device_kind`, `self._device_name`) and expose as properties (e.g.
    `resolved_device_kind`, `resolved_device_name`).
  - Alternative if the base `TTSModel` interface shouldn't grow Kokoro-specific fields:
    a small module-level state (e.g. in `device_utils.py`: `set_active_device(kind, name)`
    / `active_device()`), written by `KokoroModel.load()` and read by the health route.
    Either is acceptable; pick one and keep it simple.
- `health_check()` (server/routers/tts.py:242-261) populates the new fields from the
  model/state; `device_kind="cpu"` when the model fell back (never null once loaded;
  null only pre-load).
- Conventions: `====` banner comment explaining WHY the actual-device field exists
  (GPU *availability* ≠ device *in use*), graceful defaults.

### 2. requirements/docs — torch-directml as documented optional dep

- server/requirements.txt: add a commented optional block:
  `# torch-directml>=0.2.5.dev240914  # OPTIONAL: AMD/Intel GPU on Windows; REQUIRES torch<2.9`
  with a `====` banner explaining the constraint (torch currently arrives unpinned via
  kokoro; torch-directml wheels only match torch < 2.9, so users installing it may need
  `pip install "torch<2.9"` first).
- README.md: new "Device selection" section documenting:
  - `VOICELINK_MODEL__DEVICE=auto|cpu|cuda|amd` (default `auto`; auto = CUDA → DirectML → CPU).
  - AMD setup steps: `pip install "torch<2.9"` then `pip install torch-directml`.
  - Fallback behavior (warn + CPU, never crash) and how to see the resolved device in
    `/v1/health` and startup logs.

### 3. GUI selector (gui/index.html + gui/src/main.ts)

- index.html, Server card settings form (~line 264-270): add a `setting-row` with
  `<label>Device</label>` and `<select id="setting-device">` with options
  `auto`/`cpu`/`cuda`/`amd` labeled Auto / CPU / NVIDIA GPU / AMD GPU, following the
  existing `setting-<name>` id convention.
- main.ts:
  - `AppSettings` interface (51-58): add `device: string;`.
  - `setupSettings` (1207-1249): load `settings.device`, set `#setting-device` value
    (default "auto" if absent).
  - Change handler modeled on the Qwen3 tier handler (1375-1386): on change, invoke
    `save_settings` with `{ device: value }` (TS camelCase `device` ↔ Rust param
    `device: Option<String>`).
  - After saving, if the server is running, offer a restart so the new device takes
    effect: `showModal` (pattern ~735) asking "Restart server now to apply the new
    device?" and, on confirm, `invoke("stop_server")` then `invoke("start_server")`
    (pattern at setupServerToggle 432-452), then `checkServerStatus()`.
  - Dashboard: extend `ServerHealth` interface (line 10-18) with
    `device_kind: string | null` and `device_name: string | null`; update
    `#server-device` population at line 471 to prefer the new fields when present,
    e.g. `device_name` with a kind prefix, falling back to the current
    `gpu_name ?? (gpu_available ? "GPU" : "CPU")` logic for older servers.

### 4. Rust config + env injection (gui/src-tauri/src/lib.rs)

- `AppConfig` (87-99): add `#[serde(default = "default_device")] device: String,`
  plus `fn default_device() -> String { "auto".to_string() }` and add
  `device: "auto".to_string()` to the `Default` impl (109-125) — serde default keeps
  existing `config.json` files backward-compatible.
- `get_settings` (1626-1637): add `"device": cfg.device` to the returned JSON.
- `save_settings` (1641-1674): add `device: Option<String>` param; when `Some`, assign
  (optionally validate against `auto|cpu|cuda|amd`, falling back to `"auto"` on invalid).
- Inject the env var in BOTH spawn sites so watchdog restarts keep the setting:
  - `start_server` spawn (~1571-1578): add
    `.env("VOICELINK_MODEL__DEVICE", &cfg.device)`.
  - server watchdog spawn (~1853-1860): same `.env(...)` line.
  - Add a `// WHY` comment: device must survive watchdog-triggered restarts, hence both
    sites.

## Impact

- server/routers/tts.py — `HealthResponse` + `health_check()` new device fields (API change, additive).
- server/models/kokoro_model.py — store/expose resolved kind+name (or notify module state).
- server/models/device_utils.py — (only if module-state option chosen) active-device state; otherwise unchanged.
- server/requirements.txt — commented optional torch-directml line.
- README.md — device config + AMD setup docs.
- gui/index.html — `#setting-device` select.
- gui/src/main.ts — AppSettings, setupSettings, change handler + restart prompt, ServerHealth, dashboard device display.
- gui/src-tauri/src/lib.rs — AppConfig, default_device, Default, get_settings, save_settings, env injection ×2.

DB changes: none (no database in this project).

## Verify-only items (groundwork already satisfied in tree)

Evidence that existing uncommitted code already meets parts of the acceptance criteria —
verify, don't reimplement:

- **Device resolution & fallback policy** — server/models/device_utils.py:64-117
  (`resolve_device`: spec validation with warn→auto at 84-89, cuda→cpu fallback with
  warning at 98-103, amd→cpu fallback with warning + fix hint at 111-117, auto =
  cuda→dml→cpu at 94-110).
- **DEVICE_OPTIONS / valid config values** — server/models/device_utils.py:31
  (`("auto", "cpu", "cuda", "amd")`).
- **Config field `device`** — server/config.py:73-81 (pydantic Field, default "auto",
  full description; env `VOICELINK_MODEL__DEVICE` via pydantic-settings).
- **Model loads with device + KPipeline signature probe + KModel fallback** —
  server/models/kokoro_model.py:155-204 (`device=` kwarg at 155; `resolve_device`
  never-raises note at 180-183; signature probe at 189; KPipeline(device=...) at
  191-194; `KModel().to(torch_device).eval()` fallback at 195-200).
- **Graceful unload / warn, never raise** — server/models/kokoro_model.py:206-220.
- **Server passes device to model** — server/main.py:114-118
  (`load_model(..., device=settings.model.device)`).
- **Health reports GPU info (CUDA + DirectML)** — server/models/device_utils.py:126-140
  (`current_gpu_summary`) wired at server/routers/tts.py:249-252.

## Acceptance criteria mapping

| Criterion | Where |
|---|---|
| `VOICELINK_MODEL__DEVICE` = auto/cpu/cuda/amd, default auto | config.py:73-81 (exists); device_utils.py:31 (exists) |
| `amd` resolves via torch-directml | device_utils.py:34-51, 106-110 (exists) |
| Invalid/unavailable → CPU + logged warning, never crash | device_utils.py:84-89, 98-103, 111-117 (exists) |
| torch-directml documented as optional dep with torch constraints | requirements.txt comment (new) + README section (new) |
| Server starts & synthesizes on each setting | test strategy below |
| `/v1/health` reports GPU info AND actual device in use | current_gpu_summary (exists) + new `device_kind`/`device_name` (work item 1) |
| KPipeline loads on resolved device with KModel fallback | kokoro_model.py:186-200 (exists) |
| GUI selector | work item 3 |
| Rust config persistence + env injection | work item 4 |
| Auto prefers CUDA → DirectML → CPU | device_utils.py:94-110 (exists) |

## Risks & mitigations

- **`KPipeline(device=<dml device object>)` is unverified** — kokoro's device path may
  assume a torch device/string and mishandle the torch-directml private device object.
  Mitigation: prefer always building `KModel().to(torch_device).eval()` explicitly and
  passing `model=` to KPipeline (drop or guard the signature probe for the dml case), or
  keep the probe but add a runtime check: if `kind == "dml"`, force the explicit KModel
  path. Verify on an AMD machine if available; on NVIDIA/CPU machines the probe path is
  exercised as today.
- **torch-directml requires torch<2.9** while kokoro pulls torch unpinned — users may
  hit a wheel-mismatch on `pip install torch-directml`. Mitigation: document the
  `pip install "torch<2.9"` prerequisite prominently (README + requirements comment);
  fallback to CPU with the fix hint already exists (device_utils.py:111-117).
- **Health field addition is an API change** — additive fields; the GUI dashboard and
  COM DLL consumers ignore unknown fields. GUI keeps the old `gpu_name`-based fallback
  for older servers (line 471 logic preserved as fallback).
- **Stale config.json without `device` key** — serde `#[serde(default = "default_device")]`
  handles it; Default impl entry added.
- **Watchdog restart losing the env var** — mitigated by injecting in BOTH spawn sites.
- **Qwen3 remains CUDA-only** — out of scope; no changes to qwen3 gating.

## Test strategy outline

Verification level "works is enough" — manual/smoke, per setting:

1. **CPU:** set `VOICELINK_MODEL__DEVICE=cpu`, start server, `POST /v1/tts` with a short
   text → audio; `GET /v1/health` → `device_kind:"cpu"`.
2. **CUDA (if NVIDIA present):** `=cuda` → health shows `device_kind:"cuda"` and GPU
   name; synthesis works.
3. **AMD (if torch-directml installed):** `=amd` → health `device_kind:"dml"`; synthesis
   works; check the KModel-explicit path is taken (log line).
4. **Fallbacks:** `=cuda` on non-CUDA machine and `=amd` without torch-directml →
   server starts, warning in log, health `device_kind:"cpu"`, synthesis works. Invalid
   value (e.g. `=gpu`) → treated as auto + warning.
5. **Auto:** with/without GPUs → correct precedence CUDA → DML → CPU.
6. **GUI:** Settings → Device select shows persisted value; changing it saves
   (config.json contains `device`), restart prompt appears, server restarts with the
   new env var; Dashboard `#server-device` shows the new field (e.g. "cuda — RTX …").
7. **Backward compat:** old config.json (no `device` key) loads fine, defaults to auto.
8. **Watchdog:** kill server process while managed → watchdog restart carries
   `VOICELINK_MODEL__DEVICE` (check via health `device_kind` after restart).
