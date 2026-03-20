# LTC Timecode Player - Issues Report

## Critical Issues (App-Breaking)

### 1. Flawed Bi-Phase Mark (Manchester) Decoding Algorithm
**File:** `ltc_decoder.py:218-268`

The `extract_ltc_bits()` method uses an oversimplified approach that will fail on real-world LTC audio signals:

- **No clock recovery mechanism:** Proper LTC decoding requires a Phase-Locked Loop (PLL) or equivalent adaptive clock recovery. The current code uses a fixed `bit_duration_samples` calculated from the frame rate, which drifts with any sample rate jitter or speed variation.
- **Naive thresholding:** Uses a simple `np.std(audio_data) * 0.5` threshold (line 228). Real LTC signals have varying amplitude, DC offset, and noise. This static threshold will misclassify bits frequently.
- **Incorrect bit classification logic (lines 255-260):** The code classifies transitions based on `bit_center_offset` ranges (0.4-0.6 as clock, <0.2 or >0.8 as data), but this doesn't properly implement bi-phase mark decoding. In bi-phase mark encoding, every bit has a transition at the start, and a '1' bit has an additional transition at the midpoint. The current logic does not track this correctly.
- **Missing transition pairing:** Bi-phase mark decoding requires pairing boundary and midpoint transitions. The code processes transitions individually without pairing, leading to incorrect bit sequences.

**Impact:** The core decoding pipeline will produce garbage data or zero valid frames for most real LTC audio files.

---

### 2. Frame Rate Fallback Loop Does Nothing
**File:** `ltc_decoder.py:283-285`

```python
for frame_rate in [FrameRate.FR_30_NDF, FrameRate.FR_29_97_DF, FrameRate.FR_25_NDF]:
    detected_frame_rate = frame_rate
    break
```

This `for` loop immediately assigns `FR_30_NDF` and `break`s on the first iteration. The other two frame rates are never tried. The intent appears to be to test each frame rate and pick the best one, but no test/validation is performed — it just blindly picks the first entry.

**Impact:** When automatic frame rate detection fails, the decoder always assumes 30 fps NDF regardless of the actual signal, causing incorrect bit extraction for 25 fps, 29.97 fps, etc.

---

### 3. Async `updateDisplay()` Flooding from `setInterval`
**File:** `web/script.js:356-363`

```javascript
this.playbackTimer = setInterval(() => {
    this.currentPosition += 1 / this.frameRate;
    // ...
    this.updateDisplay();  // async but not awaited
}, 1000 / this.frameRate);
```

`updateDisplay()` is an `async` method that makes an RPC call to `eel.get_timecode_at_position()`. The `setInterval` callback does not `await` it. At high frame rates (e.g., 59.94 fps), this fires every ~16ms, creating a backlog of unawaited promises and flooding the Eel websocket with requests. Previous requests may not resolve before new ones are sent.

**Impact:** At high frame rates, the UI becomes unresponsive, the backend gets overwhelmed, and the browser may run out of memory from accumulated unresolved promises.

---

### 4. JavaScript Missing Line Breaks Between Methods
**File:** `web/script.js:20, 103`

```javascript
    }    setupEventListeners() {
```
```javascript
    }    async loadFile(file) {
```

Two method boundaries have the closing `}` of one method and the opening of the next method on the **same line** with no newline. While technically valid JavaScript, some parsers (especially in older browsers or stricter Eel webview environments) may have issues with this. More critically, it makes the code very fragile — any minor syntax change could silently break parsing.

**Impact:** Potential parsing failures in certain browser environments.

---

## Major Issues (Functional Problems)

### 5. No Actual Audio Playback
**File:** `web/script.js:349-363`

The `play()` method simulates playback using `setInterval()` to advance a position counter. There is no Web Audio API integration, no `<audio>` element, and no actual audio output. The user sees a timecode counter advancing but hears nothing.

**Impact:** The "Player" is a visual-only simulation. Users cannot hear the LTC audio to verify it against the displayed timecode.

---

### 6. File Size Shows "0 Bytes" for Browse-Loaded Files
**File:** `web/script.js:37`

```javascript
this.displayFileInfo({ name: loadResult.analysis.filename, size: 0 }, loadResult.analysis);
```

When files are loaded via the "Browse" button (tkinter dialog), the file size is hardcoded to `0`. The `displayFileInfo()` method then shows "0 Bytes" in the UI.

**Impact:** Incorrect file information displayed to the user.

---

### 7. Uploaded Temp Files Are Never Cleaned Up
**File:** `app.py:98-107`

```python
temp_path = os.path.join(temp_dir, f"ltc_upload_{filename}")
# ... file is written but never deleted
```

When files are uploaded via drag-and-drop, a copy is saved to the system temp directory. These files are never deleted — not on analysis completion, not on app exit, not on loading a new file.

**Impact:** Repeated use fills the temp directory with large audio files. A 10-minute 48kHz WAV is ~50MB; each upload leaves an orphaned copy.

---

### 8. Division by Zero When No File is Loaded
**File:** `web/script.js:400`

```javascript
const percentage = (this.currentPosition / this.duration) * 100;
```

If `this.duration` is `0` (default, before any file is loaded), this produces `NaN` or `Infinity`, which gets set on the slider's `value`.

**Impact:** Calling `updateDisplay()` before loading a file (e.g., clicking Play with no file) produces NaN in the UI.

---

### 9. `validate_ltc_signal` False Negative with Zero Frames
**File:** `app.py:345`

```python
"low_error_rate": len(analysis.errors) < len(analysis.timecode_frames) * 0.1
```

When `timecode_frames` is empty and `errors` is also empty: `0 < 0 * 0.1` evaluates to `0 < 0.0` which is `False`. So the validation reports a "high error rate" even when there are zero errors, simply because there are also zero frames.

**Impact:** Misleading validation result — the app reports "High error rate" for files with no signal at all, when the real issue is just "no signal detected."

---

### 10. `sys.platform` Check for 'win64' Is Invalid
**File:** `app.py:395`

```python
if sys.platform in ['win32', 'win64']:
```

Python's `sys.platform` returns `'win32'` on **both** 32-bit and 64-bit Windows. The value `'win64'` is never returned by Python. This doesn't cause a functional bug (because `'win32'` matches), but indicates misunderstanding of the platform detection and could cause confusion.

**Impact:** Minor — no functional impact since `'win32'` covers all Windows versions, but demonstrates incorrect platform handling.

---

### 11. Hardcoded Port with No Conflict Handling
**File:** `app.py:392-398`

```python
eel.start('index.html', size=(1200, 800), port=8001)
```

Port 8001 is hardcoded. If another application (or a previous instance) is using port 8001, the app crashes with an `OSError`. There is no retry with an alternative port, no user-facing error message, and no port auto-selection.

**Impact:** App fails to start if port 8001 is occupied.

---

### 12. `eel.init('web')` Called at Module Level
**File:** `app.py:17`

```python
eel.init('web')
```

This runs at import time, before `main()` is called. If the working directory is not the project root (e.g., when the script is run from a different directory, or imported as a module), Eel will fail to find the `web/` folder and raise an error.

**Impact:** Running `python /path/to/app.py` from a different directory crashes immediately.

---

### 13. Export Report Writes to Potentially Read-Only Directory
**File:** `app.py:282-283`

```python
output_dir = os.path.dirname(current_file_path)
output_path = os.path.join(output_dir, report_filename)
```

For drag-and-drop uploaded files, `current_file_path` points to the system temp directory. For browse-loaded files from read-only locations (network drives, protected folders), the export will fail with a permission error.

**Impact:** Export fails silently or with an unhelpful error for files loaded from protected or temp locations.

---

### 14. `decode_ltc_word` Hardcodes Frame Rate to 30 NDF
**File:** `ltc_decoder.py:201`

```python
frame_rate = FrameRate.FR_30_NDF  # Default assumption
```

Every decoded timecode frame gets `FR_30_NDF` as its frame rate. The calling function `analyze_ltc_signal()` overrides this on line 302, but if `decode_ltc_word()` is used standalone or the override is skipped, all frames report the wrong rate.

**Impact:** Frame rate information in decoded `TimecodeInfo` objects is unreliable.

---

### 15. User Bits Extraction Is Incomplete
**File:** `ltc_decoder.py:192-198`

```python
user_bit_positions = [4, 20, 36, 52]  # User bit groups
for pos in user_bit_positions:
    user_byte = 0
    for i in range(4):
        user_byte |= (bits[pos+i] << i)
    user_bits.append(user_byte)
```

SMPTE 12M LTC defines **32 user bits** organized as 8 groups of 4 bits (binary groups BG1-BG8). The code only extracts 4 groups (16 bits), missing the other 4 groups at positions 12, 28, 44, and 60.

**Impact:** Only half the user bits data is extracted. Applications relying on full user bits (e.g., embedded metadata, VITC cross-reference) will get incomplete data.

---

### 16. Large File Upload Memory Issues
**File:** `web/script.js:135-165`

The `uploadAndLoadFile()` method reads the entire audio file as a Base64 data URL via `FileReader.readAsDataURL()`. Base64 encoding increases size by ~33%. A 500MB WAV file becomes ~667MB in memory, all sent over the Eel websocket in a single message.

**Impact:** Large files (>100MB) can crash the browser tab or exceed the Eel websocket message size limit.

---

## Minor Issues

### 17. `get_timecode_at_position` Uses Linear Search
**File:** `ltc_decoder.py:332-347`

```python
for frame in self.analysis_results.timecode_frames:
    diff = abs(frame.timestamp - position_seconds)
    if diff < min_diff:
        min_diff = diff
        closest_frame = frame
```

This is O(n) linear search through all frames. For a 1-hour file at 30fps, that's ~108,000 iterations per call. Combined with Issue #3 (interval flooding), this compounds performance problems.

**Fix:** Use `bisect` module for O(log n) binary search on sorted timestamps.

---

### 18. Redundant `os.path.exists` Check
**File:** `app.py:31-37`

```python
if not os.path.exists(file_path):     # line 31: file doesn't exist
    if os.path.exists(file_path):     # line 37: check if file exists (always False here)
        possible_paths.append(file_path)
```

Line 37 re-checks `os.path.exists(file_path)` inside a block that only executes when `os.path.exists(file_path)` returned `False` on line 31. This inner check can never be `True`.

**Impact:** Dead code — no functional impact, but indicates copy-paste error.

---

### 19. `browse_for_file` Docstring Says "Windows Only"
**File:** `app.py:119`

```python
def browse_for_file():
    """Open file browser dialog (Windows only)"""
```

The function uses `tkinter.filedialog` which works cross-platform (Windows, macOS, Linux). The docstring is misleading.

---

### 20. Integer Division for Nyquist Frequency
**File:** `ltc_decoder.py:89`

```python
nyquist = sample_rate // 2
```

Uses integer division. For odd sample rates (unlikely but possible), this truncates. Should use float division for signal processing calculations, though in practice standard sample rates are always even.

---

### 21. `formatTime` Omits Hours
**File:** `web/script.js:460-470`

```javascript
formatTime(seconds, includeMs = false) {
    const hours = Math.floor(seconds / 3600);
    // hours is calculated but never included in the return value
    return `${minutes}:${secs}`;
}
```

The hours value is computed but not included in the formatted output. A file longer than 60 minutes would show `60:00` instead of `1:00:00`.

---

### 22. No Timecode Continuity Validation
**File:** `ltc_decoder.py:274-330`

The `analyze_ltc_signal()` method decodes frames individually but never checks that consecutive timecodes are sequential. Dropped frames, duplicates, or out-of-order timecodes are not detected, despite the validation check for "continuous_timecode" which only checks `len(frames) > 10`.

---

### 23. Quality Bar Color Is Misleading
**File:** `web/styles.css:230-231`

```css
.quality-fill {
    background: linear-gradient(90deg, #ef4444, #f59e0b, #10b981);
}
```

The gradient always shows red-to-green across the full bar width. A 30% quality fill would show a mostly-red segment, which visually makes sense, but at 60% it shows red-yellow which could be confusing — the color at any given width doesn't meaningfully correspond to "good" or "bad."

---

### 24. `build_executable.py` Only Handles Windows `.exe`
**File:** `build_executable.py:114`

```python
if not os.path.exists('dist/LTC-Timecode-Player.exe'):
```

The `create_release_package()` function hardcodes the `.exe` extension. On macOS or Linux, PyInstaller produces a binary without an extension, so this function always reports failure on non-Windows platforms.

---

### 25. Error List Truncated Without Notification
**File:** `ltc_decoder.py:323`

```python
errors=errors[:10]  # Limit error list
```

The error list is silently truncated to 10 entries. The total error count is never communicated to the frontend. The validation check on `app.py:345` compares `len(analysis.errors)` (max 10) against total frames, making the "low error rate" check unreliable for files with more than 10 errors.

---

### 26. No BCD Range Validation on Decoded Timecodes
**File:** `ltc_decoder.py:130-212`

The `decode_ltc_word()` method extracts BCD-encoded hours, minutes, seconds, and frames but **never validates their ranges**. Corrupted or noisy bit sequences can produce invalid values like:
- `hours = 99` (valid BCD but invalid timecode, max is 23)
- `seconds = 79` (valid BCD but max is 59)
- `frames = 39` (exceeds max frames for any standard frame rate)

These invalid `TimecodeInfo` objects are accepted as valid frames, inflating the "valid frames" count and corrupting the timecode list.

**Impact:** Garbage timecodes displayed to the user from noisy signals. The signal quality metric becomes meaningless.

---

### 27. Drop Frame Flag Not Used to Select Correct FrameRate Variant
**File:** `ltc_decoder.py:156, 274-326`

The drop frame flag is correctly extracted from bit 10 of each LTC word (line 156), but `analyze_ltc_signal()` never uses it to distinguish between NDF and DF frame rate variants. The FFT-based `detect_frame_rate()` cannot distinguish 29.97 NDF from 29.97 DF (identical frequency). So:
- A 29.97 DF signal gets detected as `FR_29_97_NDF`
- A 59.94 DF signal gets detected as `FR_59_94_NDF`

The decoded `drop_frame` boolean per-frame is set correctly, but the `detected_frame_rate` on the `LTCAnalysis` object is wrong.

**Impact:** Wrong frame rate label displayed. Drop frame timecode math (frame skipping at minute boundaries) is not applied correctly.

---

### 28. Position Slider Has Only 101 Discrete Steps
**File:** `web/index.html:126`

```html
<input type="range" id="positionSlider" min="0" max="100" value="0">
```

No `step` attribute is set, so it defaults to `1` (integer steps). The slider has exactly 101 positions (0 through 100). For a 1-hour file, each slider step represents ~36 seconds. For a 10-minute file, each step is ~6 seconds. Frame-accurate seeking via the slider is impossible.

**Impact:** Extremely coarse seeking resolution. Users cannot scrub to precise positions.

---

### 29. No Eel Shutdown Handler — Python Process Becomes Zombie
**File:** `app.py:388-398`

There is no `eel.on_close` callback or `close_callback` parameter in `eel.start()`. When the user closes the browser tab or window:
- The Eel server keeps running
- The Python process stays alive in the background
- Port 8001 remains occupied
- Reopening the app fails (port conflict, Issue #11)

The user must manually kill the Python process to restart the app.

**Impact:** Zombie process after closing the browser. App cannot be restarted without killing the process.

---

### 30. Browse Button Path Has No Loading Indicator
**File:** `web/script.js:29-56`

The browse button handler (`browseBtn` click listener) calls `eel.browse_for_file()` and then `eel.load_ltc_file()` **without calling `this.showLoading(true/false)`**. The drag-and-drop path (`loadFile()` on line 109) properly shows/hides the loading overlay, but the browse path does not.

LTC analysis can take several seconds on large files. During this time, the UI appears frozen with no visual feedback.

**Impact:** No loading spinner when loading files via browse. User thinks the app is stuck.

---

### 31. Issue #4 Downgrade — JS Line Breaks Are Valid Syntax
**File:** `web/script.js:20, 103`

After further review, the missing line breaks between methods (`}    setupEventListeners() {`) are **valid JavaScript**. Class method definitions are separated by `}` and the parser handles this regardless of whitespace. This is a code quality/readability issue, not a functional bug. Downgraded from Critical to Minor.

---

## Summary

| Severity | Count | Key Areas |
|----------|-------|-----------|
| Critical | 3 | LTC decoding algorithm (#1), frame rate fallback (#2), async flooding (#3) |
| Major | 15 | No audio playback (#5), file size 0 (#6), temp cleanup (#7), div by zero (#8), validation logic (#9), platform check (#10), port conflict (#11), module-level init (#12), export path (#13), frame rate hardcode (#14), user bits incomplete (#15), large file memory (#16), no BCD validation (#26), drop frame detection (#27), zombie process (#29) |
| Minor | 13 | Linear search (#17), dead code (#18), misleading docs (#19), integer Nyquist (#20), hours omitted (#21), no continuity check (#22), quality bar color (#23), Windows-only build (#24), error truncation (#25), slider resolution (#28), no loading on browse (#30), JS formatting (#4/31) |
| **Total** | **31** | |

### Will Fixing All These Make The App Work?

**Mostly yes, but Issue #1 requires a complete rewrite, not a patch.** The bi-phase mark decoding algorithm (`extract_ltc_bits`) is fundamentally flawed — it cannot be fixed with small changes. A proper implementation needs:
- Adaptive clock recovery (PLL or equivalent)
- Zero-crossing detection with hysteresis
- Proper Manchester/bi-phase mark state machine
- Noise-tolerant transition detection

If Issue #1 is properly rewritten and all other issues are fixed, the app should work as a functional LTC analyzer. The remaining gap would be Issue #5 (no audio playback) — the app would still only *analyze* LTC, not *play* audio, despite being called a "Player."
