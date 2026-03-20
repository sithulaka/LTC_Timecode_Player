# LTC Timecode Player & Analyzer

A desktop tool that decodes SMPTE Linear Time Code (LTC) from audio files, displays the timecode, plays back the audio, and exports analysis reports. Built with Python (backend) and a web UI served via Eel.

![Python](https://img.shields.io/badge/python-v3.7+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)

## How It Works

### Architecture

The app is a Python process that runs a local web server (Eel/Bottle on port 8001). The browser renders the UI; Python handles audio decoding and analysis. Communication happens over WebSocket RPC.

```
Browser (index.html + script.js)
    |
    |  WebSocket RPC (Eel)
    v
Python backend (app.py)
    |
    v
LTC Decoder (ltc_decoder.py)
    |
    v
Audio file (WAV/AIFF/FLAC via libsndfile)
```

### LTC Decoding Pipeline

When you load a file, here's what happens step by step:

**1. Audio Loading**
The audio file is read into memory as 32-bit float samples using `soundfile`. Stereo files are mixed down to mono by averaging channels.

**2. Frame Rate Detection**
A bandpass filter (500-5000 Hz, 4th-order Butterworth) isolates the LTC signal. An FFT on a 2-second window finds the dominant frequency. Since LTC's average frequency = frame_rate x 40, dividing the peak frequency by 40 estimates the frame rate. The result is matched to the nearest standard rate within a 2 fps tolerance.

If FFT detection fails, the decoder tries each of the common rates (30 NDF, 29.97 DF, 25 NDF), runs the full bit extraction on each, and picks whichever rate produces the most valid sync words.

**3. Bi-Phase Mark Decoding (extract_ltc_bits)**
This is the core of the decoder. LTC uses bi-phase mark encoding where:
- Every bit period begins with a signal transition (polarity flip)
- A `1` bit has an additional transition at the midpoint
- A `0` bit has no midpoint transition

The decoder works as follows:

- **Zero-crossing detection with hysteresis**: The raw audio is converted to a binary state signal (+1/-1). Hysteresis thresholds (20% of RMS) prevent noise-induced false crossings.
- **Transition extraction**: Indices where the binary state changes are collected.
- **Interval classification**: The time between consecutive transitions is compared to the expected bit duration:
  - Short interval (~0.5T): Part of a `1` bit. Two consecutive short intervals are paired to form one `1` bit.
  - Long interval (~1.0T): A `0` bit.
  - Very short (<0.3T): Noise, skipped.
  - Very long (>1.5T): Signal gap, resets the clock estimate.
- **PLL-style clock recovery**: The bit duration estimate is continuously updated using a gain factor of 0.05, tracking any speed drift in the signal.
- **Sync word search**: As bits accumulate, the last 80 bits are checked for the SMPTE sync pattern (0x3FFD in bits 64-79). When found, those 80 bits are extracted as one LTC word.

**4. LTC Word Decoding (decode_ltc_word)**
Each 80-bit word is decoded per SMPTE 12M:

```
Bits  0-3:   Frame units (BCD)
Bits  4-7:   User bits group 1
Bits  8-9:   Frame tens (BCD)
Bit  10:     Drop frame flag
Bit  11:     Color frame flag
Bits 12-15:  User bits group 2
Bits 16-19:  Seconds units (BCD)
Bits 20-23:  User bits group 3
Bits 24-26:  Seconds tens (BCD)
Bits 28-31:  User bits group 4
Bits 32-35:  Minutes units (BCD)
Bits 36-39:  User bits group 5
Bits 40-42:  Minutes tens (BCD)
Bits 44-47:  User bits group 6
Bits 48-51:  Hours units (BCD)
Bits 52-55:  User bits group 7
Bits 56-57:  Hours tens (BCD)
Bits 60-63:  User bits group 8
Bits 64-79:  Sync word (0x3FFD)
```

BCD values are range-validated: hours 0-23, minutes 0-59, seconds 0-59, frames 0 to max for the detected rate. Invalid values are rejected.

All 8 user bit groups (32 bits total) are extracted.

**5. Drop Frame Detection**
After decoding all frames, the decoder checks if a majority have the drop_frame flag set. If so, the frame rate is promoted from NDF to the DF variant (e.g., 30 NDF -> 29.97 DF, 60 NDF -> 59.94 DF). FFT alone can't distinguish these since the frequencies are nearly identical.

**6. Continuity Checking**
Consecutive decoded timecodes are compared. The decoder reports:
- Duplicate timecodes (same frame repeated)
- Backward jumps
- Gaps (skipped frames), with an exception for legitimate drop-frame skips at minute boundaries

**7. Quality Metrics**
- Signal quality = valid decoded frames / total extracted words
- Errors are counted before the display list is truncated to 10. The `total_error_count` field preserves the real count.

### Frontend Playback

The browser UI uses `requestAnimationFrame` for smooth playback at native display refresh rate. Backend RPC calls for timecode lookup are throttled to ~10/sec to avoid flooding the WebSocket.

Audio playback uses an HTML5 `<audio>` element:
- **Drag-and-drop files**: A blob URL is created directly from the File object (no re-download needed)
- **Browse-loaded files**: Audio data is fetched from the backend as a base64 data URL

The audio element's `currentTime` is synced with the timecode position counter.

### Timecode Lookup

`get_timecode_at_position()` uses `bisect` binary search on the sorted timestamp array for O(log n) lookup, instead of scanning all frames linearly.

## Installation

### Requirements
- Python 3.7+
- A modern web browser (Chrome, Firefox, Edge)

### Setup

```bash
git clone https://github.com/sithulaka/LTC-Timecode-Player.git
cd LTC-Timecode-Player
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

The app opens in your browser automatically. If port 8001 is busy, it tries 8002-8010, then falls back to an OS-assigned port.

When you close the browser tab, the Python process exits automatically.

### Dependencies

| Package | Purpose |
|---------|---------|
| `eel` | Python-to-browser bridge (WebSocket RPC + static file server) |
| `numpy` | Signal processing arrays and math |
| `scipy` | Butterworth bandpass filter, FFT |
| `soundfile` | Read WAV/AIFF/FLAC via libsndfile |
| `matplotlib` | Waveform visualization (rendered server-side as PNG) |

## Usage

### Loading a File

Two methods:
1. **Drag and drop** an audio file onto the drop zone. The file is read as base64, sent to the backend, saved as a temp file, analyzed, then the temp file is cleaned up.
2. **Click "Browse for File"**. This opens a native tkinter file dialog (works on all platforms). The backend reads the file directly from disk.

### What You See After Loading

- **File info**: Name, duration, sample rate, file size
- **Signal quality meter**: Color-coded bar (red <40%, yellow 40-70%, green >70%)
- **Analysis cards**: Detected frame rate, valid frame count, sync word count
- **Waveform**: Server-rendered matplotlib plot of the audio signal
- **Timecode player**: Large TC display, transport controls, position slider (0.01% resolution)
- **Timecode list**: Paginated table of all decoded frames with timestamps and user bits
- **Validation**: Pass/fail checks for signal presence, quality, frame rate detection, continuity, error rate

### Player Controls

| Control | Action |
|---------|--------|
| Play/Pause | Start/stop playback with audio |
| -1f / +1f | Step one frame backward/forward |
| Start / End | Jump to beginning/end |
| Slider | Seek to any position |
| Table row click | Jump to that timecode's position |

### Exporting

Click "Export Report" to write a text file with all analysis data. The report is saved next to the source file, or on your Desktop if the source location isn't writable.

## Supported Frame Rates

| Rate | Standard | Drop Frame |
|------|----------|------------|
| 23.976 fps | Film/streaming | No |
| 24 fps | Film | No |
| 25 fps | PAL/SECAM broadcast | No |
| 29.97 fps | NTSC | NDF and DF |
| 30 fps | NTSC broadcast | No |
| 50 fps | High frame rate PAL | No |
| 59.94 fps | High frame rate NTSC | NDF and DF |
| 60 fps | High frame rate | No |

## Project Structure

```
LTC_Timecode_Player/
├── app.py                 # Eel backend: file loading, RPC endpoints, temp file management
├── ltc_decoder.py         # LTC decoder: signal processing, bit extraction, frame decoding
├── web/
│   ├── index.html         # UI layout
│   ├── styles.css         # Styling
│   └── script.js          # Player logic, audio playback, RPC calls
├── build_executable.py    # PyInstaller build script (Windows/macOS/Linux)
├── requirements.txt       # Python dependencies
└── test_player.py         # Basic feature demo/test
```

### Key Files Explained

**ltc_decoder.py** contains:
- `FrameRate` enum with all standard rates, FPS calculation, max frames per rate
- `TimecodeInfo` dataclass for a single decoded frame
- `LTCAnalysis` dataclass for complete analysis results (includes `total_error_count`)
- `LTCDecoder` class with methods: `load_audio_file`, `detect_frame_rate`, `extract_ltc_bits`, `decode_ltc_word`, `analyze_ltc_signal`, `get_timecode_at_position`, `export_timecode_list`

**app.py** exposes these Eel RPC endpoints:
- `load_ltc_file(path)` - Load and analyze an LTC audio file
- `save_uploaded_file(data, name)` - Save drag-and-drop upload to temp
- `browse_for_file()` - Open native file picker
- `get_timecode_at_position(seconds)` - Look up timecode at audio position
- `get_timecode_list(start, count)` - Paginated frame list
- `generate_waveform()` - Render waveform as base64 PNG
- `serve_audio_file()` - Return audio as base64 data URL for browser playback
- `export_timecode_report()` - Write analysis to text file
- `validate_ltc_signal()` - Run validation checks
- `get_audio_info()` - File metadata
- `get_file_size(path)` - File size in bytes

## Building an Executable

```bash
python build_executable.py
```

This uses PyInstaller to create a standalone binary. The script detects the platform and produces:
- Windows: `dist/LTC-Timecode-Player.exe`
- macOS/Linux: `dist/LTC-Timecode-Player`

A release package is created in `release/` with the binary and documentation.

## Troubleshooting

**App won't start**: Check that port 8001 isn't in use. The app will auto-try ports 8002-8010. If all fail, it uses a random available port.

**No signal detected**: The file must contain actual LTC audio (a specific encoded signal), not regular speech or music. LTC sounds like a buzzing/clicking tone.

**Low quality / wrong frame numbers**: Heavy noise degrades decoding. The decoder tolerates moderate noise but will lose frames below ~10dB SNR. The signal quality percentage tells you what fraction of frames decoded successfully.

**File size shows 0**: This only happens if the file was deleted before the size could be read. Should not occur in normal use.

**Browser didn't open**: Navigate to `http://localhost:8001` manually. Or try `http://localhost:8002` if 8001 was busy.

## Standards

The decoder implements:
- **SMPTE 12M** (SMPTE Timecode)
- **IEC 60461** (Timecode for Audio)

## License

MIT License - see [LICENSE](LICENSE).
