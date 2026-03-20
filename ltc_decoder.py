import bisect
import numpy as np
import soundfile as sf
from scipy import signal
from enum import Enum
from dataclasses import dataclass
from typing import Tuple, List, Optional
import struct

class FrameRate(Enum):
    """Standard international frame rates"""
    FR_23_976_NDF = (24000, 1001, False, "23.976 fps NDF")
    FR_24_NDF = (24, 1, False, "24 fps NDF")
    FR_25_NDF = (25, 1, False, "25 fps NDF")
    FR_29_97_NDF = (30000, 1001, False, "29.97 fps NDF")
    FR_30_NDF = (30, 1, False, "30 fps NDF")
    FR_50_NDF = (50, 1, False, "50 fps NDF")
    FR_59_94_NDF = (60000, 1001, False, "59.94 fps NDF")
    FR_60_NDF = (60, 1, False, "60 fps NDF")
    FR_29_97_DF = (30000, 1001, True, "29.97 fps DF")
    FR_59_94_DF = (60000, 1001, True, "59.94 fps DF")

    def get_fps(self) -> float:
        return self.value[0] / self.value[1]

    def is_drop_frame(self) -> bool:
        return self.value[2]

    def get_display_name(self) -> str:
        return self.value[3]

    def get_max_frames(self) -> int:
        """Return the maximum frame number (exclusive) for this frame rate."""
        fps = self.get_fps()
        if fps < 24.5:
            return 24
        elif fps < 25.5:
            return 25
        elif fps < 30.5:
            return 30
        elif fps < 50.5:
            return 50
        else:
            return 60

@dataclass
class TimecodeInfo:
    """Timecode information extracted from LTC"""
    hours: int
    minutes: int
    seconds: int
    frames: int
    frame_rate: FrameRate
    drop_frame: bool
    user_bits: List[int]
    timestamp: float  # Time position in audio file

    def __str__(self):
        df_suffix = " DF" if self.drop_frame else ""
        return f"{self.hours:02d}:{self.minutes:02d}:{self.seconds:02d}:{self.frames:02d}{df_suffix}"

@dataclass
class LTCAnalysis:
    """Complete LTC analysis results"""
    sample_rate: int
    duration: float
    detected_frame_rate: Optional[FrameRate]
    timecode_frames: List[TimecodeInfo]
    signal_quality: float  # 0.0 to 1.0
    sync_word_count: int
    errors: List[str]
    total_error_count: int

class LTCDecoder:
    """Professional LTC Timecode Decoder and Player"""

    SYNC_WORD = 0x3FFD

    def __init__(self):
        self.audio_data = None
        self.sample_rate = None
        self.analysis_results = None

    def load_audio_file(self, file_path: str) -> bool:
        """Load audio file for LTC analysis"""
        try:
            self.audio_data, self.sample_rate = sf.read(file_path, dtype=np.float32)

            # Convert stereo to mono if needed
            if len(self.audio_data.shape) > 1:
                self.audio_data = np.mean(self.audio_data, axis=1)

            return True
        except Exception as e:
            print(f"Error loading audio file: {e}")
            return False

    def detect_frame_rate(self, audio_data: np.ndarray, sample_rate: int) -> Optional[FrameRate]:
        """Detect frame rate from LTC signal frequency analysis"""
        try:
            # Calculate fundamental frequency of LTC signal
            # LTC frequency = frame_rate * 80 / 2 (80 bits per frame, bi-phase encoding)

            # Apply bandpass filter to isolate LTC frequencies (500-5000 Hz)
            nyquist = sample_rate / 2  # Issue #20: float division
            low_freq = 500 / nyquist
            high_freq = min(5000 / nyquist, 0.99)

            b, a = signal.butter(4, [low_freq, high_freq], btype='band')
            filtered_signal = signal.filtfilt(b, a, audio_data)

            # Find dominant frequency using FFT
            window_size = min(sample_rate * 2, len(filtered_signal))  # 2 second window
            fft = np.fft.fft(filtered_signal[:window_size])
            freqs = np.fft.fftfreq(window_size, 1/sample_rate)

            # Find peak frequency in LTC range
            magnitude = np.abs(fft)
            peak_idx = np.argmax(magnitude[50:window_size//2]) + 50  # Skip DC component
            peak_freq = abs(freqs[peak_idx])

            # Convert frequency back to frame rate
            # LTC_freq = frame_rate * 40 (average frequency)
            estimated_fps = peak_freq / 40

            # Match to closest standard frame rate
            best_match = None
            min_diff = float('inf')

            for frame_rate in FrameRate:
                diff = abs(frame_rate.get_fps() - estimated_fps)
                if diff < min_diff:
                    min_diff = diff
                    best_match = frame_rate

            # Only return match if it's close enough
            if min_diff < 2.0:  # Within 2 fps tolerance
                return best_match

            return None

        except Exception as e:
            print(f"Error detecting frame rate: {e}")
            return None

    def decode_ltc_word(self, bits: List[int], frame_rate: FrameRate = FrameRate.FR_30_NDF) -> Optional[TimecodeInfo]:
        """Decode 80-bit LTC word to timecode information.

        Args:
            bits: List of 80 bits representing an LTC word.
            frame_rate: The frame rate to assign to the decoded timecode.
        """
        if len(bits) != 80:
            return None

        try:
            # Check sync word (last 16 bits)
            sync_word = 0
            for i in range(16):
                sync_word |= (bits[79-15+i] << i)

            if sync_word != self.SYNC_WORD:
                return None

            # Extract timecode data
            frame_units = 0
            for i in range(4):
                frame_units |= (bits[i] << i)

            frame_tens = 0
            for i in range(2):
                frame_tens |= (bits[8+i] << i)

            frames = frame_tens * 10 + frame_units

            # Drop frame flag
            drop_frame = bool(bits[10])

            # Seconds
            seconds_units = 0
            for i in range(4):
                seconds_units |= (bits[16+i] << i)

            seconds_tens = 0
            for i in range(3):
                seconds_tens |= (bits[24+i] << i)

            seconds = seconds_tens * 10 + seconds_units

            # Minutes
            minutes_units = 0
            for i in range(4):
                minutes_units |= (bits[32+i] << i)

            minutes_tens = 0
            for i in range(3):
                minutes_tens |= (bits[40+i] << i)

            minutes = minutes_tens * 10 + minutes_units

            # Hours
            hours_units = 0
            for i in range(4):
                hours_units |= (bits[48+i] << i)

            hours_tens = 0
            for i in range(2):
                hours_tens |= (bits[56+i] << i)

            hours = hours_tens * 10 + hours_units

            # Issue #26: BCD range validation
            max_frames = frame_rate.get_max_frames()
            if not (0 <= frames < max_frames):
                return None
            if not (0 <= seconds <= 59):
                return None
            if not (0 <= minutes <= 59):
                return None
            if not (0 <= hours <= 23):
                return None

            # Issue #15: Extract all 8 user bit groups (BG1-BG8) per SMPTE 12M
            user_bits = []
            user_bit_positions = [4, 12, 20, 28, 36, 44, 52, 60]
            for pos in user_bit_positions:
                user_byte = 0
                for i in range(4):
                    user_byte |= (bits[pos+i] << i)
                user_bits.append(user_byte)

            return TimecodeInfo(
                hours=hours,
                minutes=minutes,
                seconds=seconds,
                frames=frames,
                frame_rate=frame_rate,
                drop_frame=drop_frame,
                user_bits=user_bits,
                timestamp=0.0  # Will be set by calling function
            )

        except Exception as e:
            print(f"Error decoding LTC word: {e}")
            return None

    def extract_ltc_bits(self, audio_data: np.ndarray, sample_rate: int,
                        frame_rate: FrameRate) -> List[List[int]]:
        """Extract LTC bits from audio signal using proper bi-phase mark decoding
        with PLL-style adaptive clock recovery and zero-crossing detection."""
        try:
            # Calculate expected bit duration
            fps = frame_rate.get_fps()
            nominal_bit_duration = sample_rate / (fps * 80)

            # Apply hysteresis-based zero-crossing detection
            rms = np.sqrt(np.mean(audio_data ** 2))
            if rms < 1e-6:
                return []
            hysteresis_high = rms * 0.2
            hysteresis_low = -hysteresis_high

            # Build binary state signal with hysteresis
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

            # Find zero-crossing (transition) indices
            transitions = np.diff(state)
            transition_indices = np.where(transitions != 0)[0]

            if len(transition_indices) < 160:
                return []

            # Compute intervals between consecutive transitions
            intervals = np.diff(transition_indices).astype(np.float64)

            # PLL-style adaptive clock recovery
            # In bi-phase mark coding:
            #   - A '0' bit has one transition at the bit boundary (interval ~ 1 bit period)
            #   - A '1' bit has an additional mid-bit transition (interval ~ 0.5 bit period)
            # So intervals cluster around 0.5T and 1.0T where T is the bit duration.

            bit_duration = nominal_bit_duration  # PLL tracked estimate
            pll_gain = 0.05  # PLL tracking bandwidth

            bits_buffer = []  # all decoded bits in sequence
            # Map each bit to its approximate sample position
            bit_sample_positions = []
            ltc_words = []

            i = 0
            while i < len(intervals):
                interval = intervals[i]
                ratio = interval / bit_duration

                if ratio < 0.3:
                    # Spurious/noise transition, skip
                    i += 1
                    continue
                elif ratio < 0.75:
                    # Short interval (~0.5T): this is the mid-bit transition of a '1' bit.
                    # The next interval should also be ~0.5T (second half of the bit).
                    # Together they form one '1' bit.
                    if i + 1 < len(intervals):
                        next_interval = intervals[i + 1]
                        full_period = interval + next_interval
                        # Update PLL estimate
                        bit_duration += pll_gain * (full_period - bit_duration)
                        bits_buffer.append(1)
                        bit_sample_positions.append(transition_indices[i])
                        i += 2
                    else:
                        i += 1
                elif ratio < 1.5:
                    # Long interval (~1.0T): this is a '0' bit (transition only at boundary)
                    # Update PLL estimate
                    bit_duration += pll_gain * (interval - bit_duration)
                    bits_buffer.append(0)
                    bit_sample_positions.append(transition_indices[i])
                    i += 1
                else:
                    # Very long interval - likely a gap or loss of signal, reset
                    bits_buffer.append(0)
                    bit_sample_positions.append(transition_indices[i])
                    # Reset PLL to nominal
                    bit_duration = nominal_bit_duration
                    i += 1

                # Try to find sync words in the accumulated bits
                if len(bits_buffer) >= 80:
                    # Check last 80 bits for sync word
                    candidate = bits_buffer[-80:]
                    sync_word = 0
                    for si in range(16):
                        sync_word |= (candidate[79-15+si] << si)

                    if sync_word == self.SYNC_WORD:
                        ltc_words.append(list(candidate))
                        bits_buffer.clear()
                        bit_sample_positions.clear()

            return ltc_words

        except Exception as e:
            print(f"Error extracting LTC bits: {e}")
            return []

    def _check_timecode_continuity(self, timecode_frames: List[TimecodeInfo],
                                    frame_rate: FrameRate) -> List[str]:
        """Check consecutive timecodes for gaps, duplicates, and jumps."""
        errors = []
        if len(timecode_frames) < 2:
            return errors

        max_frames = frame_rate.get_max_frames()

        def tc_to_total_frames(tc: TimecodeInfo) -> int:
            return ((tc.hours * 3600 + tc.minutes * 60 + tc.seconds) * max_frames
                    + tc.frames)

        for i in range(1, len(timecode_frames)):
            prev = timecode_frames[i - 1]
            curr = timecode_frames[i]
            prev_total = tc_to_total_frames(prev)
            curr_total = tc_to_total_frames(curr)
            diff = curr_total - prev_total

            if diff == 0:
                errors.append(
                    f"Duplicate timecode {curr} at position {curr.timestamp:.3f}s"
                )
            elif diff < 0:
                errors.append(
                    f"Timecode jumped backwards from {prev} to {curr} "
                    f"at position {curr.timestamp:.3f}s"
                )
            elif diff > 1:
                # Allow diff > 1 only for drop-frame skips (frames 0,1 at minute boundaries)
                is_df_skip = (frame_rate.is_drop_frame() and diff <= 3
                              and curr.frames <= 3 and curr.seconds == 0
                              and curr.minutes % 10 != 0)
                if not is_df_skip:
                    errors.append(
                        f"Timecode gap of {diff} frames from {prev} to {curr} "
                        f"at position {curr.timestamp:.3f}s"
                    )

        return errors

    def analyze_ltc_signal(self) -> Optional[LTCAnalysis]:
        """Perform complete LTC signal analysis"""
        if self.audio_data is None:
            return None

        try:
            # Detect frame rate
            detected_frame_rate = self.detect_frame_rate(self.audio_data, self.sample_rate)
            if not detected_frame_rate:
                # Issue #2: Actually try each candidate rate and pick the best
                best_rate = None
                best_sync_count = -1
                for candidate_rate in [FrameRate.FR_30_NDF, FrameRate.FR_29_97_DF,
                                       FrameRate.FR_25_NDF, FrameRate.FR_24_NDF,
                                       FrameRate.FR_29_97_NDF, FrameRate.FR_23_976_NDF]:
                    candidate_words = self.extract_ltc_bits(
                        self.audio_data, self.sample_rate, candidate_rate
                    )
                    # Count valid sync words by attempting decode
                    sync_count = 0
                    for word_bits in candidate_words:
                        if self.decode_ltc_word(word_bits, candidate_rate) is not None:
                            sync_count += 1
                    if sync_count > best_sync_count:
                        best_sync_count = sync_count
                        best_rate = candidate_rate
                detected_frame_rate = best_rate if best_rate else FrameRate.FR_30_NDF

            # Extract LTC bits
            ltc_words = self.extract_ltc_bits(self.audio_data, self.sample_rate, detected_frame_rate)

            # Decode timecode frames
            timecode_frames = []
            sync_word_count = 0
            errors = []

            for i, word_bits in enumerate(ltc_words):
                timecode_info = self.decode_ltc_word(word_bits, detected_frame_rate)
                if timecode_info:
                    # Calculate timestamp in audio file
                    fps = detected_frame_rate.get_fps()
                    timecode_info.timestamp = i / fps
                    timecode_info.frame_rate = detected_frame_rate
                    timecode_frames.append(timecode_info)
                    sync_word_count += 1
                else:
                    errors.append(f"Failed to decode LTC word at position {i}")

            # Issue #27: Check drop frame flag to select correct FrameRate variant
            if timecode_frames:
                df_count = sum(1 for tc in timecode_frames if tc.drop_frame)
                if df_count > len(timecode_frames) / 2:
                    # Majority have drop_frame set - switch to DF variant if available
                    df_map = {
                        FrameRate.FR_29_97_NDF: FrameRate.FR_29_97_DF,
                        FrameRate.FR_30_NDF: FrameRate.FR_29_97_DF,
                        FrameRate.FR_59_94_NDF: FrameRate.FR_59_94_DF,
                        FrameRate.FR_60_NDF: FrameRate.FR_59_94_DF,
                    }
                    if detected_frame_rate in df_map:
                        detected_frame_rate = df_map[detected_frame_rate]
                        # Update all decoded frames with corrected rate
                        for tc in timecode_frames:
                            tc.frame_rate = detected_frame_rate

            # Issue #22: Timecode continuity validation
            continuity_errors = self._check_timecode_continuity(
                timecode_frames, detected_frame_rate
            )
            errors.extend(continuity_errors)

            # Calculate signal quality
            total_words = len(ltc_words)
            valid_words = len(timecode_frames)
            signal_quality = valid_words / total_words if total_words > 0 else 0.0

            # Calculate duration
            duration = len(self.audio_data) / self.sample_rate

            # Issue #25: Track total error count before truncating
            total_error_count = len(errors)

            self.analysis_results = LTCAnalysis(
                sample_rate=self.sample_rate,
                duration=duration,
                detected_frame_rate=detected_frame_rate,
                timecode_frames=timecode_frames,
                signal_quality=signal_quality,
                sync_word_count=sync_word_count,
                errors=errors[:10],  # Limit error list
                total_error_count=total_error_count
            )

            return self.analysis_results

        except Exception as e:
            print(f"Error analyzing LTC signal: {e}")
            return None

    def get_timecode_at_position(self, position_seconds: float) -> Optional[TimecodeInfo]:
        """Get timecode at specific audio position using binary search."""
        if not self.analysis_results or not self.analysis_results.timecode_frames:
            return None

        frames = self.analysis_results.timecode_frames
        timestamps = [f.timestamp for f in frames]

        # Use bisect for O(log n) lookup
        idx = bisect.bisect_left(timestamps, position_seconds)

        # Find the closest frame among the neighboring candidates
        candidates = []
        if idx > 0:
            candidates.append(idx - 1)
        if idx < len(frames):
            candidates.append(idx)

        if not candidates:
            return None

        closest_idx = min(candidates, key=lambda i: abs(timestamps[i] - position_seconds))
        return frames[closest_idx]

    def export_timecode_list(self, filename: str):
        """Export timecode list to text file"""
        if not self.analysis_results:
            return False

        try:
            with open(filename, 'w') as f:
                f.write("LTC Timecode Analysis Results\n")
                f.write("=" * 40 + "\n\n")
                f.write(f"Sample Rate: {self.analysis_results.sample_rate} Hz\n")
                f.write(f"Duration: {self.analysis_results.duration:.2f} seconds\n")
                f.write(f"Frame Rate: {self.analysis_results.detected_frame_rate.get_display_name() if self.analysis_results.detected_frame_rate else 'Unknown'}\n")
                f.write(f"Signal Quality: {self.analysis_results.signal_quality:.1%}\n")
                f.write(f"Valid Frames: {len(self.analysis_results.timecode_frames)}\n\n")

                f.write("Timecode List:\n")
                f.write("-" * 40 + "\n")
                f.write("Audio Time    | Timecode     | User Bits\n")
                f.write("-" * 40 + "\n")

                for frame in self.analysis_results.timecode_frames[:100]:  # Limit to first 100
                    user_bits_str = " ".join([f"{ub:02X}" for ub in frame.user_bits])
                    f.write(f"{frame.timestamp:8.2f}s | {frame} | {user_bits_str}\n")

                if self.analysis_results.errors:
                    f.write(f"\nErrors ({self.analysis_results.total_error_count} total, showing first {len(self.analysis_results.errors)}):\n")
                    f.write("-" * 40 + "\n")
                    for error in self.analysis_results.errors:
                        f.write(f"- {error}\n")

            return True

        except Exception as e:
            print(f"Error exporting timecode list: {e}")
            return False
