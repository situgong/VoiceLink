# Test Plan — Kokoro Device Selection (CPU / CUDA / AMD DirectML)

Feature: device selection for Kokoro TTS via `VOICELINK_MODEL__DEVICE=auto|cpu|cuda|amd`
(default `auto`), GUI Settings selector, and `/v1/health` `device_kind`/`device_name`
reporting. Design doc: [change-doc.md](change-doc.md). Verification level: "works is
enough" — manual/smoke plus existing stubbed unit tests.

## Scope

In scope:

- `server/models/device_utils.py` — `resolve_device`, `describe_device`,
  `current_gpu_summary`, `DEVICE_OPTIONS` (spec validation, fallback policy,
  auto precedence CUDA → DirectML → CPU).
- `server/models/kokoro_model.py` — `device=` kwarg, resolved kind/name capture,
  KPipeline signature probe + KModel fallback path.
- `server/routers/tts.py` — `HealthResponse.device_kind` / `device_name`
  (additive API change) and `health_check()` population.
- `server/config.py` — `VOICELINK_MODEL__DEVICE` env field, default `auto`.
- `gui/src/main.ts` + `gui/index.html` — Device `<select>`, persistence,
  restart prompt, dashboard `#server-device` display.
- `gui/src-tauri/src/lib.rs` — `AppConfig.device`, `get_settings`/`save_settings`,
  env injection in `start_server` AND watchdog spawn sites.
- Backward compatibility: stale `config.json` without a `device` key.

Out of scope: Qwen3 device handling (remains CUDA-only), non-Windows platforms,
DB (none exists), COM DLL behavior beyond ignoring unknown health fields.

## Environments

1. **Dev machine without deps (this agent's machine)** — Python available but
   torch / kokoro / loguru / numpy NOT installed; no Rust toolchain; no GPU.
   Only the stubbed unit tests in `server/tests/test_device_utils.py` can run.
2. **Deployed embedded Python (target user machine)** — bundled Python with
   torch + kokoro installed; CPU-only or with whatever GPU the user has.
   Exercises real fallback paths and health endpoint.
3. **AMD GPU machine (Windows, DX12-capable, torch<2.9 + torch-directml)** —
   validates the DirectML path end-to-end (resolution, KModel explicit path,
   synthesis, `device_kind:"dml"`).
4. **NVIDIA GPU machine (Windows, CUDA torch build)** — validates the CUDA
   path end-to-end (resolution, synthesis, `device_kind:"cuda"`, auto
   precedence over DirectML).

## Scenarios

| ID | Scenario | Steps | Expected | Automated?/Manual | Status |
|---|---|---|---|---|---|
| TC-01 | CPU spec resolves to CPU | `resolve_device("cpu")` with stubbed torch (no CUDA, no DML) | kind `cpu`, name `CPU` | Automated (unit test `test_cpu_spec_returns_cpu`) | covered |
| TC-02 | CUDA available | `resolve_device("cuda")` with CUDA stub | kind `cuda`, name from stub | Automated (`test_cuda_available`) | covered |
| TC-03 | CUDA unavailable → CPU fallback | `resolve_device("cuda")` with no-CUDA stub | kind `cpu`, warning logged, no crash | Automated (`test_cuda_unavailable_falls_back_to_cpu`) | covered |
| TC-04 | AMD with torch-directml | `resolve_device("amd")` with DML stub | kind `dml`, private device object returned, name includes adapter + "DirectML" | Automated (`test_amd_with_dml_stub`) | covered |
| TC-05 | AMD without torch-directml → CPU fallback | `resolve_device("amd")` with no DML stub | kind `cpu`, warning with fix hint, no crash | Automated (`test_amd_without_dml_falls_back_to_cpu`) | covered |
| TC-06 | Auto with no GPUs → CPU | `resolve_device("auto")`, no CUDA/DML | kind `cpu`, name `CPU` | Automated (`test_auto_no_gpus_cpu`) | covered |
| TC-07 | Auto prefers CUDA over DirectML | `resolve_device("auto")`, CUDA + DML stubs | kind `cuda` | Automated (`test_auto_prefers_cuda_over_dml`) | covered |
| TC-08 | Auto uses DML when no CUDA | `resolve_device("auto")`, DML stub only | kind `dml` | Automated (`test_auto_uses_dml_when_no_cuda`) | covered |
| TC-09 | Invalid spec treated as auto (no GPU) | `resolve_device("gpu")`, no stubs | kind `cpu`, warning | Automated (`test_invalid_spec_treated_as_auto`) | covered |
| TC-10 | Invalid spec treated as auto (CUDA present) | `resolve_device("gpu")` with CUDA stub | kind `cuda` | Automated (`test_invalid_spec_with_cuda_available`) | covered |
| TC-11 | GPU summary — CUDA | `current_gpu_summary()` with CUDA stub | `(True, "Test CUDA GPU")` | Automated (`test_summary_cuda`) | covered |
| TC-12 | GPU summary — DML | `current_gpu_summary()` with DML stub | `(True, "Test AMD GPU")` | Automated (`test_summary_dml`) | covered |
| TC-13 | GPU summary — neither | `current_gpu_summary()`, no stubs | `(False, None)` | Automated (`test_summary_neither`) | covered |
| TC-14 | describe_device format | `describe_device("cpu")` | `"cpu (CPU)"` | Automated (`test_describe`) | covered |
| TC-15 | CPU runtime synthesis | Set `VOICELINK_MODEL__DEVICE=cpu`, start server, `POST /v1/tts` short text; `GET /v1/health` | Audio returned; `device_kind:"cpu"`; no warnings about fallback | Manual | unverified — torch/kokoro not installed on this machine |
| TC-16 | CUDA runtime synthesis | On NVIDIA machine: `=cuda`, start, synth, health | Audio; `device_kind:"cuda"`, `device_name` = GPU name | Manual | unverified — no NVIDIA GPU available to the agent |
| TC-17 | AMD/DirectML runtime synthesis | On AMD machine with torch-directml: `=amd`, start, synth, health; check KModel-explicit path log | Audio; `device_kind:"dml"`; explicit KModel path taken for dml | Manual | unverified — no AMD GPU available to the agent |
| TC-18 | Real fallbacks at runtime | `=cuda` on non-CUDA machine; `=amd` without torch-directml; invalid `=gpu` | Server starts in all cases; warning in log; health `device_kind:"cpu"`; synthesis works | Manual | unverified — torch/kokoro not installed on this machine |
| TC-19 | Auto precedence at runtime | `=auto` on CUDA-only, DML-only, and CPU-only machines | Health reports cuda / dml / cpu respectively in that precedence | Manual | unverified — no GPUs available to the agent |
| TC-20 | Health API shape (additive) | `GET /v1/health` before and after model load | Pre-load: `device_kind`/`device_name` null; post-load: never null; old fields `gpu_available`/`gpu_name` unchanged; extra fields ignored by older clients | Manual | unverified — torch/kokoro not installed on this machine |
| TC-21 | GUI selector — persistence | Open Settings → Device select; change value; check `config.json` | Select shows persisted value; `config.json` contains `device` key | Manual | unverified — requires built Tauri app (GUI E2E in Tauri not runnable here) |
| TC-22 | GUI selector — restart prompt | Change device while server running | Modal "Restart server now to apply the new device?"; on confirm server restarts and health shows new device | Manual | unverified — GUI E2E in Tauri not runnable here |
| TC-23 | Dashboard device display | Health with new fields vs. old server without them | `#server-device` shows `device_name` with kind prefix when present; falls back to `gpu_name ?? (gpu_available ? "GPU" : "CPU")` for older servers | Manual | unverified — GUI E2E in Tauri not runnable here |
| TC-24 | config.json backward compat | Load old `config.json` with no `device` key | App starts fine; `get_settings` returns `device:"auto"` (serde default) | Manual | unverified — no Rust toolchain to build/run the Tauri app |
| TC-25 | Watchdog restart env propagation | Kill managed server process; wait for watchdog restart; check health | Watchdog respawn carries `VOICELINK_MODEL__DEVICE`; `device_kind` unchanged after restart | Manual | unverified — no Rust toolchain, no deployable build available |
| TC-26 | save_settings validation | `save_settings` with `device:"gpu"` (invalid) | Falls back to `"auto"` (or rejected), never persisted as invalid | Manual | unverified — no Rust toolchain |

## Unverified items

Explicit list of things this plan could not verify on the drafting machine:

1. **Real-GPU CUDA synthesis** (TC-16) — no NVIDIA GPU available to the agent.
2. **Real-GPU DirectML/AMD synthesis** (TC-17) — no AMD GPU available to the
   agent; also the `KPipeline(device=<dml object>)` risk from the design doc
   (KModel-explicit path for dml) remains unverified.
3. **Watchdog restart env propagation** (TC-25) — requires a built Tauri app
   and a killable managed server; no Rust toolchain on this machine.
4. **GUI selector E2E in the Tauri app** (TC-21–TC-23) — requires building and
   running the Tauri GUI; no Rust toolchain on this machine.
5. **`cargo check` / any Rust compilation** — no Rust toolchain installed, so
   `lib.rs` changes (AppConfig, serde default, env injection ×2,
   save_settings) are compile-unverified.
6. **Runtime server behavior generally** (TC-15, TC-18–TC-20) — torch/kokoro
   not installed on this machine; only stubbed unit tests executed.

## Regression checks

- **CPU/CUDA resolution path unchanged** — TC-01–TC-03, TC-06–TC-07 (covered by
  existing unit tests) confirm `resolve_device` behavior for cpu/cuda/auto
  specs matches pre-change semantics; no changes to Qwen3 CUDA gating.
- **Health API additive only** — TC-20: `gpu_available`/`gpu_name`/`status`/
  `model`/`model_loaded`/`uptime_seconds` fields and semantics unchanged;
  `device_kind`/`device_name` are new optional fields; GUI dashboard keeps the
  old `gpu_name`-based fallback for older servers.
- **config.json backward compatibility** — TC-24: `#[serde(default =
  "default_device")]` plus `Default` impl entry means stale config files load
  with `device:"auto"`; `get_settings`/`save_settings` round-trips preserve
  all existing keys.
- **Fallback never crashes** — TC-03/TC-05/TC-09 (covered) plus runtime TC-18:
  invalid or unavailable selections degrade to CPU with a logged warning.
