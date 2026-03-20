# LTC Timecode Player - Improvements Roadmap

A comprehensive analysis of potential improvements across all components of the application, organized by priority and area.

---

## Table of Contents

- [1. LTC Decoder (ltc_decoder.py)](#1-ltc-decoder-ltc_decoderpy)
  - [1.1 Performance](#11-performance)
  - [1.2 Signal Processing](#12-signal-processing)
  - [1.3 Missing Features](#13-missing-features)
  - [1.4 Code Quality](#14-code-quality)
- [2. Backend (app.py)](#2-backend-apppy)
  - [2.1 Security](#21-security)
  - [2.2 Concurrency](#22-concurrency)
  - [2.3 Error Handling](#23-error-handling)
  - [2.4 Performance](#24-performance)
  - [2.5 API Design](#25-api-design)
  - [2.6 Resource Management](#26-resource-management)
- [3. Frontend (script.js, index.html, styles.css)](#3-frontend-scriptjs-indexhtml-stylescss)
  - [3.1 Accessibility](#31-accessibility)
  - [3.2 Performance](#32-performance)
  - [3.3 UX](#33-ux)
  - [3.4 Audio Playback Edge Cases](#34-audio-playback-edge-cases)
  - [3.5 Browser Compatibility](#35-browser-compatibility)
  - [3.6 State Management](#36-state-management)
  - [3.7 CSS](#37-css)
- [4. Infrastructure & Build](#4-infrastructure--build)
  - [4.1 Testing](#41-testing)
  - [4.2 Dependencies](#42-dependencies)
  - [4.3 Build Script](#43-build-script)
  - [4.4 Deployment](#44-deployment)
  - [4.5 Development Tooling](#45-development-tooling)
- [Summary Table](#summary-table)
- [Recommended Priority Order](#recommended-priority-order)

---

## 1. LTC Decoder (ltc_decoder.py)

### 1.1 Performance

#### P1. Hysteresis loop is a pure Python for-loop over every audio sample
**Lines:** 264-273
**Severity:** High
**Current behavior:** The zero-crossing detection iterates sample-by-sample in Python. For a 1-hour 48kHz file, that's 172.8M iterations. This is the single largest bottleneck — roughly half of total analysis time.

**Improvement:** Use `numba.jit(nopython=True)` to compile the loop to native code (~50-100x speedup), or rewrite using vectorized numpy operations with `np.cumsum` for state propagation. Adding numba as an optional dependency is the lowest-effort fix:

```python
@numba.jit(nopython=True)
def _build_hysteresis_state(audio_data, hysteresis_high, hysteresis_low):
    n = len(audio_data)
    state = np.zeros(n, dtype=np.int8)
    current_state = 1 if audio_data[0] >= 0 else -1
    state[0] = current_state
    for idx in range(1, n):
        if current_state == -1 and audio_data[idx] > hysteresis_high:
            current_state = 1
        elif current_state == 1 and audio_data[idx] < hysteresis_low:
            current_state = -1
        state[idx] = current_state
    return state
```

#### P2. Sync word detection is duplicated and runs on every loop iteration
**Lines:** 158-160, 341-343
**Severity:** Medium
**Current behavior:** The same 16-bit sync word extraction loop exists in both `decode_ltc_word()` and `extract_ltc_bits()`. The one in `extract_ltc_bits` runs on every iteration of the main while loop, even when the buffer has fewer than 80 bits.

**Improvement:** Extract into a single helper method. The buffer length check already exists (`if len(bits_buffer) >= 80`) but the sync computation inside it could use a precomputed lookup or direct bit comparison instead of a loop.

#### P3. Unused `bit_sample_positions` list accumulated but never read
**Lines:** 296, 318, 327, 348
**Severity:** Low
**Current behavior:** Sample positions are tracked for every decoded bit but the list is never returned or used. Wastes memory proportional to signal length.

**Improvement:** Remove the variable, or return it alongside the bit data for waveform annotation features.

---

### 1.2 Signal Processing

#### S1. Hysteresis thresholds are asymmetric around zero — fails on DC offset signals
**Lines:** 256-261
**Severity:** Medium
**Current behavior:** Thresholds are `±(RMS * 0.2)`, centered on zero. Real LTC signals from analog sources often have DC offset from recording chain bias. A signal centered at +0.1V would have different effective thresholds for positive and negative crossings, causing timing skew.

**Improvement:** Center hysteresis on the signal mean:

```python
signal_mean = np.mean(audio_data)
rms = np.sqrt(np.mean((audio_data - signal_mean) ** 2))
hysteresis_band = rms * 0.2
hysteresis_high = signal_mean + hysteresis_band
hysteresis_low = signal_mean - hysteresis_band
```

#### S2. PLL gain is fixed — poor adaptation across signal conditions
**Lines:** 291-335
**Severity:** Medium
**Current behavior:** PLL gain is constant at 0.05. A fixed-gain PLL:
- On noisy signals: gain is too high, locks onto noise
- On clean signals: gain is too low, slow to adapt to tape speed drift
- On signals with wow/flutter: can't track rapid speed changes

**Improvement:** Implement adaptive gain based on recent interval variance:

```python
if len(recent_intervals) > 5:
    jitter = np.var(recent_intervals[-20:])
    pll_gain = np.clip(0.02 + 0.08 * np.exp(-jitter * 100), 0.02, 0.10)
```

Higher jitter (noisy signal) = lower gain (trust existing estimate). Lower jitter = higher gain (adapt faster).

#### S3. No guard against zero/near-zero peak frequency in frame rate detection
**Lines:** 123-124
**Severity:** Low
**Current behavior:** `estimated_fps = peak_freq / 40` proceeds even if peak_freq is 0 (silent/DC file). Doesn't crash but wastes CPU on the fallback brute-force loop.

**Improvement:** Add `if peak_freq < 10: return None` before the division.

#### S4. Bandpass filter parameters are not documented
**Lines:** 105-107
**Severity:** Low
**Current behavior:** `500 Hz` low, `5000 Hz` high, 4th order Butterworth. These encode domain knowledge (LTC frequency range across all standard frame rates) but someone maintaining the code wouldn't know why these specific values were chosen.

**Improvement:** Define as class constants with explanations:

```python
BANDPASS_LOW_FREQ = 500    # Hz — LTC fundamental at 24fps = 24*40 = 960 Hz, margin for harmonics
BANDPASS_HIGH_FREQ = 5000  # Hz — LTC fundamental at 60fps = 60*40 = 2400 Hz, plus harmonics
BANDPASS_ORDER = 4         # Butterworth — flat passband, reasonable rolloff
```

---

### 1.3 Missing Features

#### F1. No polarity inversion detection
**Severity:** Medium
**Current behavior:** If the LTC cable is wired with reversed polarity, the signal is inverted. The decoder still works (bi-phase mark is polarity-agnostic) but the user has no way to know the signal is inverted.

**Improvement:** Compare positive vs negative RMS energy. If negative dominates by >50%, report "Signal polarity: INVERTED" in the analysis results. Professional LTC analyzers flag this.

#### F2. No reverse playback detection
**Lines:** 356-396
**Severity:** Medium
**Current behavior:** Backward-running timecodes are flagged as errors ("jumped backwards"). But in post-production, reverse playback is legitimate (editors shuttle tape backwards). A sustained sequence of decreasing timecodes is reverse playback, not corruption.

**Improvement:** Detect contiguous sequences of decreasing timecodes. Report them separately as "reverse playback regions" rather than errors. Add a `reverse_regions: List[Tuple[int, int]]` field to `LTCAnalysis`.

#### F3. No status reason when bit extraction returns empty
**Lines:** 279-280
**Severity:** Low
**Current behavior:** `extract_ltc_bits()` returns `[]` for both "no transitions detected" and "transitions found but no valid sync words". The caller can't distinguish between "no signal" and "signal present but undecodable".

**Improvement:** Return a status alongside the data: `(ltc_words, "insufficient_transitions")` or `(ltc_words, "no_sync_words_found")`.

#### F4. Per-digit BCD validation during extraction
**Lines:** 166-221
**Severity:** Low
**Current behavior:** BCD digits are extracted first, combined into values (e.g., `hours_tens * 10 + hours_units`), then range-validated. A corrupted `hours_tens = 5` with `hours_units = 3` produces `hours = 53`, which is rejected. But you could reject earlier at the digit level (`hours_tens` must be 0-2).

**Improvement:** Validate each BCD digit during extraction: `hours_tens` max 2, `minutes_tens` max 5, etc. Catches corruption one step earlier.

---

### 1.4 Code Quality

#### Q1. Magic numbers scattered throughout
**Lines:** 105-107, 137, 260, 292, 304-308
**Severity:** Medium
**Current behavior:** Numeric constants like `0.2` (hysteresis), `0.05` (PLL gain), `0.3/0.75/1.5` (interval ratios), `2.0` (frame rate tolerance) appear inline without explanation.

**Improvement:** Define as class-level constants:

```python
class LTCDecoder:
    SYNC_WORD = 0x3FFD
    HYSTERESIS_THRESHOLD = 0.2
    PLL_GAIN = 0.05
    INTERVAL_NOISE_RATIO = 0.3
    INTERVAL_SHORT_MAX = 0.75
    INTERVAL_LONG_MAX = 1.5
    FRAME_RATE_TOLERANCE = 2.0
```

#### Q2. No SMPTE 12M documentation in docstrings
**Lines:** 130-245, 247-354
**Severity:** Medium
**Current behavior:** The bit layout of an 80-bit LTC word is only understood by reading the extraction code. Someone unfamiliar with SMPTE 12M has to reverse-engineer which bits correspond to which fields.

**Improvement:** Add a comprehensive docstring to `decode_ltc_word()` showing the full 80-bit layout with field positions, and a docstring to `extract_ltc_bits()` explaining bi-phase mark encoding rules.

---

## 2. Backend (app.py)

### 2.1 Security

#### SEC1. No upload size limit — base64 bomb vulnerability
**Lines:** 128
**Severity:** High
**Current behavior:** `save_uploaded_file()` decodes and writes base64 data without any size check. A 100MB base64 string is ~75MB decoded, but nothing prevents a 10GB payload.

**Improvement:**

```python
MAX_UPLOAD_SIZE = 500 * 1024 * 1024  # 500MB
if len(file_data) > MAX_UPLOAD_SIZE * 1.37:  # base64 expansion factor
    return {"success": False, "message": "File too large (max 500MB)"}
```

#### SEC2. Predictable temp file names — symlink attack risk
**Lines:** 120-135
**Severity:** Medium
**Current behavior:** Temp files use `ltc_upload_{filename}` — predictable and user-controlled. On shared systems, an attacker could pre-create a symlink at that path pointing to a sensitive file.

**Improvement:** Use `tempfile.NamedTemporaryFile(prefix='ltc_', suffix=os.path.splitext(filename)[1], delete=False)` for unpredictable names.

#### SEC3. No file extension validation before processing
**Lines:** 120-135
**Severity:** Medium
**Current behavior:** `save_uploaded_file()` accepts any filename. User could upload a `.exe` or `.jpg` — it saves to disk, then `load_ltc_file()` passes it to soundfile which fails with a cryptic error.

**Improvement:** Validate extension against `['.wav', '.aiff', '.aif', '.flac']` before saving.

#### SEC4. Path fallback logic searches predictable directories
**Lines:** 45-72
**Severity:** Low
**Current behavior:** If a file path doesn't exist, the code searches Desktop, Downloads, Documents. This is convenient but could be exploited if an attacker places files in those directories.

**Improvement:** Remove the fallback search. Require users to provide correct full paths. The browse dialog and drag-drop always provide full paths anyway.

---

### 2.2 Concurrency

#### CON1. Global mutable state without thread safety
**Lines:** 17-20
**Severity:** Medium
**Current behavior:** `ltc_decoder`, `current_file_path`, and `playback_position` are global variables modified by multiple Eel-exposed functions. Eel uses gevent/threading, so concurrent requests can race.

**Scenario:** User loads File A (long analysis). While analysis runs, user loads File B. `current_file_path` is overwritten. File A analysis completes with wrong path context.

**Improvement:** Add a `threading.RLock()` around all global state mutations:

```python
_state_lock = threading.RLock()

@eel.expose
def load_ltc_file(file_path):
    with _state_lock:
        # ... all modifications
```

#### CON2. `serve_audio_file()` loads entire file into memory as base64
**Lines:** 385-398
**Severity:** Medium
**Current behavior:** For a 500MB WAV file, this creates a 667MB base64 string and sends it over WebSocket. Can exceed Eel's buffer limits or crash with OOM.

**Improvement:** Serve the file via a temporary HTTP endpoint instead of base64 encoding, or stream it in chunks. Alternatively, cap the size and return an error for files over 100MB with guidance to use drag-and-drop (which creates a local blob URL without backend transfer).

---

### 2.3 Error Handling

#### ERR1. Generic exception catching hides root cause
**Lines:** 142-143, 94-95, and most endpoints
**Severity:** Medium
**Current behavior:** Every endpoint wraps everything in `except Exception as e: return {"message": str(e)}`. Disk full, permission denied, corrupted file, and invalid input all produce the same generic error format.

**Improvement:** Catch specific exceptions and return actionable messages:

```python
except PermissionError:
    return {"success": False, "message": "Permission denied — check file permissions"}
except OSError as e:
    if e.errno == errno.ENOSPC:
        return {"success": False, "message": "Disk full"}
    raise
```

#### ERR2. Zero-frame analysis reported as success
**Lines:** 74-81
**Severity:** Medium
**Current behavior:** If a random audio file (music, speech) is loaded, `analyze_ltc_signal()` returns an `LTCAnalysis` with 0 frames and 0 quality. But `load_ltc_file()` returns `"success": True`, and the frontend shows "File loaded successfully" — misleading.

**Improvement:** Return a warning when no LTC signal is detected:

```python
if len(analysis.timecode_frames) == 0:
    return {"success": True, "warning": "No LTC signal detected in this file", ...}
```

#### ERR3. No cleanup on partial failures
**Lines:** 91-97
**Severity:** Low
**Current behavior:** If an exception occurs after `save_uploaded_file()` succeeds but before analysis completes, the temp file is never cleaned up.

**Improvement:** Wrap the entire load-analyze sequence in try/finally that cleans up temp files on failure.

---

### 2.4 Performance

#### PERF1. Waveform generation downsamples insufficiently and has no caching
**Lines:** 247-293
**Severity:** Medium
**Current behavior:** Downsamples to 100K points (a 2-second file at 48kHz isn't downsampled at all). Every call regenerates from scratch. Matplotlib is slow for large point counts.

**Improvement:** Always target ~2000 points for visualization (more than enough for a 1200px-wide image). Cache the result keyed on `current_file_path`:

```python
_waveform_cache = {}

@eel.expose
def generate_waveform():
    if current_file_path in _waveform_cache:
        return _waveform_cache[current_file_path]
    # ... generate with target_points = 2000
    _waveform_cache[current_file_path] = result
    return result
```

#### PERF2. Matplotlib figure and BytesIO buffer not properly cleaned up
**Lines:** 281-285
**Severity:** Low
**Current behavior:** `plt.close()` is called but the BytesIO buffer is never explicitly closed. In a long-running process with repeated waveform generations, this leaks memory.

**Improvement:** Use try/finally:

```python
buffer = BytesIO()
try:
    fig, ax = plt.subplots(figsize=(12, 4))
    # ... render
    fig.savefig(buffer, ...)
    buffer.seek(0)
    result = base64.b64encode(buffer.getvalue()).decode()
finally:
    plt.close(fig)
    buffer.close()
```

---

### 2.5 API Design

#### API1. Inconsistent response formats across endpoints
**Severity:** Medium
**Current behavior:** Each endpoint nests data under different keys:

```python
return {"success": True, "file_path": ...}         # browse_for_file
return {"success": True, "analysis": {...}}         # load_ltc_file
return {"success": True, "timecode_list": [...]}    # get_timecode_list
return {"success": True, "info": {...}}             # get_audio_info
return {"success": True, "validation": {...}}       # validate_ltc_signal
```

Frontend must handle each response shape individually.

**Improvement:** Standardize to `{"success": bool, "data": {...}, "error": {"code": str, "message": str}}`.

#### API2. No input validation on public endpoints
**Lines:** 182-244
**Severity:** Medium
**Current behavior:** `get_timecode_at_position(position_seconds)` doesn't validate input. `float("abc")` raises ValueError. `float('inf')` produces undefined behavior. `get_timecode_list(count=-1000)` creates negative ranges.

**Improvement:** Validate and clamp all numeric inputs at the endpoint level.

---

### 2.6 Resource Management

#### RES1. Global LTCDecoder holds audio data indefinitely
**Lines:** 17-18
**Severity:** Medium
**Current behavior:** Once a file is loaded, `ltc_decoder.audio_data` (potentially hundreds of MB) stays in memory until a new file replaces it or the app exits. No way to free it.

**Improvement:** Add a cleanup method. After analysis and waveform generation are complete, the raw audio data is no longer needed (decoded timecodes are stored separately). Release it:

```python
def release_audio_data(self):
    self.audio_data = None
```

#### RES2. atexit cleanup doesn't run on SIGKILL or crash
**Lines:** 26-35
**Severity:** Low
**Current behavior:** Temp file cleanup uses `atexit.register()` which only runs on normal exit. Force-kill, crash, or container shutdown leave orphaned files.

**Improvement:** Also clean up stale files on startup:

```python
def _cleanup_stale_temp_files(max_age_hours=24):
    for f in os.listdir(tempfile.gettempdir()):
        if f.startswith('ltc_upload_'):
            path = os.path.join(tempfile.gettempdir(), f)
            if time.time() - os.path.getmtime(path) > max_age_hours * 3600:
                os.remove(path)
```

---

## 3. Frontend (script.js, index.html, styles.css)

### 3.1 Accessibility

#### A1. File drop zone has no ARIA attributes
**File:** index.html, lines 30-41
**Severity:** High
**Current behavior:** The drop zone `<div>` has a click handler but no `role="button"`, no `aria-label`, and no `tabindex`. Screen reader users don't know it's interactive. Keyboard users can't tab to it.

**Improvement:** Add `role="button" tabindex="0" aria-label="Drop LTC audio file here or click to browse"`.

#### A2. Player controls lack ARIA labels
**File:** index.html, lines 134-154
**Severity:** High
**Current behavior:** Buttons use icon fonts (`<i class="fas fa-play">`) with visible text, but no `aria-label` on the buttons themselves. The timecode display has no `aria-live` region.

**Improvement:** Add `aria-label` to each button. Add `aria-live="polite"` to the timecode display `<div>` so screen readers announce timecode changes.

#### A3. No keyboard shortcuts
**File:** script.js
**Severity:** Medium
**Current behavior:** No keyboard bindings for Space (play/pause), Left/Right Arrow (step frame), Home/End (jump to start/end). Users must click buttons.

**Improvement:** Add a `keydown` listener:

```javascript
document.addEventListener('keydown', (e) => {
    if (e.code === 'Space') { e.preventDefault(); this.togglePlayback(); }
    if (e.code === 'ArrowLeft') this.stepFrame(-1);
    if (e.code === 'ArrowRight') this.stepFrame(1);
    if (e.code === 'Home') this.jumpToStart();
    if (e.code === 'End') this.jumpToEnd();
});
```

#### A4. No focus-visible styles on interactive elements
**File:** styles.css
**Severity:** Medium
**Current behavior:** Buttons have `:hover` styles but no `:focus` or `:focus-visible`. Keyboard users can't see which element has focus.

**Improvement:** Add `:focus-visible` rules for all buttons and the slider:

```css
.player-btn:focus-visible {
    outline: 3px solid #4f46e5;
    outline-offset: 2px;
}
```

#### A5. Color contrast issues
**File:** styles.css
**Severity:** Medium
**Current behavior:** Light gray text (`#6b7280`) on white/light backgrounds fails WCAG AA contrast ratio (4.5:1). Affects drop hint text (line 128), time labels (line 329), and table cells (line 406).

**Improvement:** Darken text colors to at least `#4b5563` for body text, `#374151` for important labels.

#### A6. Toast notifications not announced to screen readers
**File:** script.js, lines 620-629
**Severity:** Low
**Current behavior:** Toasts appear visually but have no `aria-live` attribute. Screen reader users miss success/error messages.

**Improvement:** Add `role="alert"` and `aria-live="assertive"` to the toast element.

---

### 3.2 Performance

#### FP1. Event listeners accumulate on timecode table rows
**File:** script.js, lines 316-318
**Severity:** Medium
**Current behavior:** Each call to `displayTimecodeList()` clears `tbody.innerHTML` then adds new rows with click listeners. The `innerHTML = ''` removes DOM nodes (which frees their listeners), but if any external references exist, listeners leak.

**Improvement:** Use event delegation on the `<tbody>` instead of per-row listeners:

```javascript
tbody.addEventListener('click', (e) => {
    const row = e.target.closest('tr');
    if (row && row.dataset.timestamp) {
        this.seekToPosition(parseFloat(row.dataset.timestamp) / this.duration * 100);
    }
});
```

This requires only one listener regardless of row count.

#### FP2. DOM elements queried repeatedly instead of cached
**File:** script.js, entire file
**Severity:** Low
**Current behavior:** `document.getElementById('positionSlider')` is called on every frame during playback (inside `updateDisplay` and `_updateSliderAndLabels`). Same for `timecodeDisplay`, `currentTime`, `totalTime`, etc.

**Improvement:** Cache element references in the constructor:

```javascript
constructor() {
    // ...
    this.elements = {
        slider: document.getElementById('positionSlider'),
        timecodeDisplay: document.getElementById('timecodeDisplay'),
        currentTime: document.getElementById('currentTime'),
        totalTime: document.getElementById('totalTime'),
    };
}
```

#### FP3. No `will-change` hints for animated elements
**File:** styles.css
**Severity:** Low
**Current behavior:** Toast transitions, spinner animation, and hover effects don't use `will-change` or `transform: translateZ(0)` for GPU compositing.

**Improvement:** Add `will-change: transform` to `.toast` and `.spinner` to promote them to GPU layers.

---

### 3.3 UX

#### UX1. Play button fails silently when no file is loaded
**File:** script.js, line 408
**Severity:** Medium
**Current behavior:** `if (!this.currentAnalysis) return;` — clicking Play with no file does nothing. No error, no guidance.

**Improvement:** Show a toast: `this.showToast('Load an LTC audio file first', 'info');`

#### UX2. Audio playback failure is silent
**File:** script.js, lines 69-76
**Severity:** Medium
**Current behavior:** If `serve_audio_file()` fails for browse-loaded files, only `console.warn()` is called. User sees "File loaded successfully" but can't hear audio. No indication that playback is unavailable.

**Improvement:** Show a non-blocking warning: `this.showToast('Audio playback unavailable — analysis only', 'info');`

#### UX3. Loading overlay text is always the same
**File:** index.html, line 235
**Severity:** Low
**Current behavior:** Always shows "Analyzing LTC signal..." even during file upload, waveform generation, or export.

**Improvement:** Accept a message parameter in `showLoading()`:

```javascript
showLoading(show, message = 'Analyzing LTC signal...') {
    document.getElementById('loadingOverlay').style.display = show ? 'flex' : 'none';
    if (show) document.querySelector('.loading-content p').textContent = message;
}
```

#### UX4. Toast auto-hides error messages before user can read them
**File:** script.js, line 627
**Severity:** Low
**Current behavior:** 5-second timeout for all toasts. Long error messages disappear too quickly.

**Improvement:** Use longer timeout for errors (8s), add a click-to-dismiss handler, or keep errors visible until dismissed.

#### UX5. No confirmation when loading a new file replaces current analysis
**Severity:** Low
**Current behavior:** Loading a new file instantly replaces the current analysis, player position, and audio. User loses everything with no undo.

**Improvement:** If analysis exists, show a confirm dialog: "Loading a new file will replace the current analysis. Continue?"

---

### 3.4 Audio Playback Edge Cases

#### AU1. No `ended` event handler on audio element
**File:** script.js
**Severity:** Medium
**Current behavior:** End-of-file is detected in the RAF loop (`currentPosition >= duration`), but the audio element fires its own `ended` event independently. If the audio finishes slightly before or after the RAF check, the two can desync.

**Improvement:** Add `this.audioElement.addEventListener('ended', () => this.pause());`

#### AU2. AutoPlay policy not handled
**File:** script.js, line 417
**Severity:** Medium
**Current behavior:** `this.audioElement.play()` is called directly. Modern browsers require a user gesture to start audio. The Play button click IS a user gesture, but if `play()` is called programmatically (e.g., from a seek callback), it may fail.

**Improvement:** Handle the play promise:

```javascript
const playPromise = this.audioElement.play();
if (playPromise !== undefined) {
    playPromise.catch((error) => {
        console.warn('Autoplay blocked:', error);
        this.showToast('Click Play to start audio', 'info');
    });
}
```

#### AU3. Audio not paused before source change
**File:** script.js, lines 35-42
**Severity:** Low
**Current behavior:** `_setAudioSource()` changes the `src` without pausing first. If audio is playing, browser behavior is undefined — some browsers stop, others glitch.

**Improvement:** Always pause and reset before changing source:

```javascript
_setAudioSource(url) {
    this.audioElement.pause();
    this.audioElement.currentTime = 0;
    if (this.audioBlobUrl) URL.revokeObjectURL(this.audioBlobUrl);
    this.audioBlobUrl = url;
    this.audioElement.src = url;
    this.audioElement.load();
}
```

#### AU4. Seeking while paused doesn't sync audio position
**Severity:** Low
**Current behavior:** Clicking the slider while paused calls `seekToPosition()` which updates `currentPosition` and `audioElement.currentTime`. But if the audio hasn't loaded yet (`readyState < 2`), the seek is silently ignored.

**Improvement:** Check `audioElement.readyState` before seeking, or queue the seek for when audio is ready.

---

### 3.5 Browser Compatibility

#### BC1. No feature detection for required APIs
**Severity:** Medium
**Current behavior:** Code uses `async/await`, `requestAnimationFrame`, `URL.createObjectURL`, and HTML5 `<audio>` without checking browser support.

**Improvement:** Add graceful degradation:

```javascript
if (typeof requestAnimationFrame === 'undefined') {
    window.requestAnimationFrame = (cb) => setTimeout(cb, 16);
}
```

#### BC2. CSS `backdrop-filter` not prefixed
**File:** styles.css, line 32
**Severity:** Low
**Current behavior:** `backdrop-filter: blur(10px)` has no `-webkit-` prefix. Doesn't work in older Safari versions.

**Improvement:** Add `-webkit-backdrop-filter: blur(10px);` before the unprefixed version.

#### BC3. No persistent state across page refreshes
**Severity:** Low
**Current behavior:** All state (loaded file, analysis, playback position) is lost on refresh.

**Improvement:** Use `sessionStorage` to save the last loaded file path and position. Offer to restore on reload.

---

### 3.6 State Management

#### SM1. Multiple async operations race on file load
**File:** script.js, lines 146-182
**Severity:** Medium
**Current behavior:** `loadFile()` fires upload, analysis, waveform, timecode list, and validation in sequence. But the browse handler fires similar operations. If user clicks browse while a drag-drop load is in progress, both modify `currentAnalysis` concurrently.

**Improvement:** Add a loading lock:

```javascript
async loadFile(file) {
    if (this._loadingInProgress) return;
    this._loadingInProgress = true;
    try { /* ... */ } finally { this._loadingInProgress = false; }
}
```

#### SM2. `duration` can stay zero after file load
**Severity:** Low
**Current behavior:** If analysis succeeds but returns `duration: 0` (empty file), the player and slider are broken. No validation prevents this.

**Improvement:** Guard against zero/negative duration: `this.duration = Math.max(analysis.duration, 0.001);`

---

### 3.7 CSS

#### CSS1. No dark mode support
**File:** styles.css
**Severity:** Medium
**Current behavior:** Hard-coded white background, purple gradient, dark text. Users with system-level dark mode preference see a bright white page.

**Improvement:** Add `@media (prefers-color-scheme: dark)` rules with dark background, light text, and adjusted accent colors.

#### CSS2. Responsive design has only one breakpoint
**File:** styles.css, lines 611-654
**Severity:** Low
**Current behavior:** Single `@media (max-width: 768px)` breakpoint. No tablet (1024px) or small phone (480px) optimizations.

**Improvement:** Add breakpoints at 480px (small phone) and 1024px (tablet). Make the timecode table horizontally scrollable on mobile. Increase touch target sizes to 44px minimum.

#### CSS3. Slider thumb too small for touch
**File:** styles.css, lines 309, 320
**Severity:** Low
**Current behavior:** 20px slider thumb. Apple's Human Interface Guidelines recommend 44px minimum for touch targets.

**Improvement:** Increase to 28-32px for desktop, 44px on touch devices via media query.

---

## 4. Infrastructure & Build

### 4.1 Testing

#### T1. No real test suite exists
**File:** test_player.py
**Severity:** Critical
**Current behavior:** `test_player.py` is a demo script that prints output. No assertions, no test framework, no CI integration. Zero test coverage of core decoding logic.

**Improvement:** Create a `tests/` directory with pytest-based tests:

```
tests/
  fixtures/           # Small LTC WAV test files (generated, committed)
  test_decoder.py     # Unit tests for extract_ltc_bits, decode_ltc_word
  test_frame_rate.py  # Frame rate detection with 25/29.97/30fps fixtures
  test_drop_frame.py  # DF vs NDF detection
  test_continuity.py  # Gap/duplicate/backwards detection
  test_app.py         # Backend endpoint tests
  conftest.py         # Shared fixtures
```

Generate small test audio files (1-2 seconds each) as fixtures and commit them to the repo.

#### T2. No CI/CD test step
**Severity:** Critical
**Current behavior:** GitHub Actions builds the executable but never runs tests. A broken decoder ships as long as it compiles.

**Improvement:** Add a test step before the build:

```yaml
- name: Run tests
  run: |
    pip install pytest pytest-cov
    pytest tests/ --cov=. --cov-report=xml -v
- name: Upload coverage
  uses: codecov/codecov-action@v3
```

---

### 4.2 Dependencies

#### D1. No version pinning
**File:** requirements.txt
**Severity:** High
**Current behavior:** All dependencies use `>=` with old minimum versions. Two builds on different dates can resolve to incompatible versions. numpy 2.0 has breaking API changes that could silently break bit operations.

**Improvement:** Pin exact versions:

```
numpy==2.4.3
eel==0.18.2
scipy==1.17.1
soundfile==0.13.1
matplotlib==3.10.8
```

Maintain a separate `requirements-dev.txt` for development tools (pytest, black, mypy, pyinstaller).

#### D2. Missing development dependencies
**Severity:** Medium
**Current behavior:** No testing, linting, formatting, or type-checking tools specified.

**Improvement:** Create `requirements-dev.txt`:

```
pytest>=7.0
pytest-cov>=4.0
black>=24.0
flake8>=7.0
mypy>=1.0
pyinstaller>=6.0
```

#### D3. Python version floor is too low
**Severity:** Low
**Current behavior:** README claims Python 3.7+ support. Python 3.7 reached EOL in June 2023 and is not tested in CI.

**Improvement:** Raise minimum to Python 3.9. Update README, add `python_requires='>=3.9'` if using setup.py/pyproject.toml.

---

### 4.3 Build Script

#### BS1. Build failures produce no diagnostic output
**File:** build_executable.py, lines 100-105
**Severity:** Medium
**Current behavior:** `subprocess.check_call()` raises `CalledProcessError` but stderr/stdout aren't captured or displayed.

**Improvement:** Use `subprocess.run(capture_output=True)` and print stderr on failure.

#### BS2. PyInstaller installed without version pin
**File:** build_executable.py, line 19
**Severity:** Medium
**Current behavior:** `pip install pyinstaller` installs latest version. Spec file format can change between major versions.

**Improvement:** Pin to a known-working version: `pip install pyinstaller==6.5.0`

#### BS3. No pre-build validation
**Severity:** Low
**Current behavior:** Build starts immediately. If `web/` directory is missing or `app.py` has syntax errors, PyInstaller fails deep in the process.

**Improvement:** Add checks before building:

```python
def validate_project():
    assert os.path.exists('app.py'), 'app.py not found'
    assert os.path.isdir('web'), 'web/ directory not found'
    assert os.path.exists('web/index.html'), 'web/index.html not found'
    # Syntax check
    import py_compile
    py_compile.compile('app.py', doraise=True)
    py_compile.compile('ltc_decoder.py', doraise=True)
```

#### BS4. Built executable not verified
**Severity:** Low
**Current behavior:** After building, the script checks if the file exists but doesn't verify it runs.

**Improvement:** Add a smoke test: launch the executable, wait 3 seconds, check it's running, then kill it.

---

### 4.4 Deployment

#### DEP1. No code signing for executables
**Severity:** Medium
**Current behavior:** Unsigned binaries trigger OS security warnings (Windows SmartScreen, macOS Gatekeeper). Users must manually allow execution.

**Improvement:** Add code signing step in CI for Windows (signtool) and macOS (codesign + notarization).

#### DEP2. No release checksums
**Severity:** Low
**Current behavior:** No SHA256 hashes published alongside releases. Users cannot verify download integrity.

**Improvement:** Generate and publish checksums:

```bash
sha256sum dist/LTC-Timecode-Player* > checksums.sha256
```

#### DEP3. version.json not updated during builds
**Severity:** Low
**Current behavior:** `version.json` has a hardcoded build date that goes stale.

**Improvement:** Derive version from git tags and update build_date automatically:

```python
import subprocess, json, datetime
version = subprocess.check_output(['git', 'describe', '--tags', '--always']).decode().strip()
with open('version.json', 'w') as f:
    json.dump({"version": version, "build_date": datetime.date.today().isoformat()}, f)
```

---

### 4.5 Development Tooling

#### DT1. No linting or formatting configuration
**Severity:** Medium
**Current behavior:** No `.flake8`, no `pyproject.toml` with tool config, no pre-commit hooks. Code style is inconsistent.

**Improvement:** Add `pyproject.toml`:

```toml
[tool.black]
line-length = 100

[tool.isort]
profile = "black"

[tool.mypy]
python_version = "3.9"
warn_return_any = true
```

Add `.pre-commit-config.yaml` with black, flake8, and isort hooks.

#### DT2. No type hints on core modules
**Severity:** Medium
**Current behavior:** Public functions have return type annotations but internal operations don't. No mypy configuration to enforce.

**Improvement:** Add type hints progressively, starting with `ltc_decoder.py` (highest-risk code). Run `mypy --strict` in CI.

---

## Summary Table

| Area | ID | Severity | Description |
|------|----|----------|-------------|
| **Decoder** | P1 | High | Hysteresis loop not vectorized — 50-100x slower than necessary |
| **Decoder** | S1 | Medium | Hysteresis fails on DC offset signals |
| **Decoder** | S2 | Medium | Fixed PLL gain — poor noise/drift adaptation |
| **Decoder** | F1 | Medium | No polarity inversion detection |
| **Decoder** | F2 | Medium | No reverse playback detection |
| **Decoder** | Q1 | Medium | Magic numbers not documented as constants |
| **Decoder** | Q2 | Medium | No SMPTE 12M layout in docstrings |
| **Backend** | SEC1 | High | No upload size limit (base64 bomb) |
| **Backend** | SEC2 | Medium | Predictable temp file names |
| **Backend** | SEC3 | Medium | No file extension validation before save |
| **Backend** | CON1 | Medium | Global state without thread safety |
| **Backend** | CON2 | Medium | Entire audio file base64-encoded over WebSocket |
| **Backend** | ERR1 | Medium | Generic exception catching hides root cause |
| **Backend** | ERR2 | Medium | Zero-frame analysis reported as success |
| **Backend** | PERF1 | Medium | Waveform not cached, insufficient downsampling |
| **Backend** | API1 | Medium | Inconsistent response formats |
| **Backend** | API2 | Medium | No input validation on endpoints |
| **Backend** | RES1 | Medium | Audio data held in memory indefinitely |
| **Frontend** | A1 | High | Drop zone missing ARIA attributes |
| **Frontend** | A2 | High | Player controls lack ARIA labels |
| **Frontend** | A3 | Medium | No keyboard shortcuts |
| **Frontend** | A4 | Medium | No focus-visible styles |
| **Frontend** | A5 | Medium | Color contrast fails WCAG AA |
| **Frontend** | UX1 | Medium | Play fails silently with no file loaded |
| **Frontend** | UX2 | Medium | Audio failure is silent |
| **Frontend** | AU1 | Medium | No `ended` event handler on audio |
| **Frontend** | AU2 | Medium | AutoPlay policy not handled |
| **Frontend** | SM1 | Medium | Concurrent file loads race |
| **Frontend** | CSS1 | Medium | No dark mode support |
| **Infra** | T1 | Critical | No real test suite |
| **Infra** | T2 | Critical | No CI test step |
| **Infra** | D1 | High | Dependencies not version-pinned |
| **Infra** | D2 | Medium | Missing dev dependencies |
| **Infra** | DT1 | Medium | No linting or formatting config |
| **Infra** | DT2 | Medium | No type hints enforced |
| **Infra** | BS1 | Medium | Build failures lack diagnostics |

---

## Recommended Priority Order

### Phase 1 — Reliability (do first)
1. **T1/T2**: Add pytest test suite with CI integration
2. **D1**: Pin all dependency versions
3. **SEC1**: Add upload size limits
4. **P1**: Vectorize hysteresis loop (numba or cython)
5. **ERR2**: Warn when no LTC signal detected

### Phase 2 — Robustness
6. **CON1**: Add thread safety to global state
7. **SEC2/SEC3**: Secure temp file handling and validate extensions
8. **S1**: Fix hysteresis for DC offset signals
9. **S2**: Implement adaptive PLL gain
10. **AU2**: Handle AutoPlay policy
11. **PERF1**: Cache waveform, downsample to 2K points

### Phase 3 — User Experience
12. **A1/A2/A3**: Accessibility — ARIA labels, keyboard shortcuts
13. **A4/A5**: Focus styles and contrast fixes
14. **CSS1**: Dark mode support
15. **UX1/UX2**: Show feedback for silent failures
16. **API1**: Standardize response format
17. **SM1**: Loading lock to prevent races

### Phase 4 — Polish
18. **F1/F2**: Polarity and reverse playback detection
19. **Q1/Q2**: Document constants and SMPTE layout
20. **DT1/DT2**: Linting, formatting, type hints
21. **DEP1/DEP2/DEP3**: Code signing, checksums, version automation
22. **BC1**: Feature detection for older browsers
23. **CSS2/CSS3**: Responsive refinements, touch target sizes
