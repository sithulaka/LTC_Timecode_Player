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
            nyquist = sample_rate // 2
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
    
    def decode_ltc_word(self, bits: List[int]) -> Optional[TimecodeInfo]:
        """Decode 80-bit LTC word to timecode information"""
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
            
            # Extract user bits
            user_bits = []
            user_bit_positions = [4, 20, 36, 52]  # User bit groups
            for pos in user_bit_positions:
                user_byte = 0
                for i in range(4):
                    user_byte |= (bits[pos+i] << i)
                user_bits.append(user_byte)
            
            # Determine frame rate (simplified - would need more sophisticated detection)
            frame_rate = FrameRate.FR_30_NDF  # Default assumption
            
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
        """Extract LTC bits from audio signal using bi-phase mark decoding"""
        try:
            # Calculate expected bit duration
            fps = frame_rate.get_fps()
            frame_duration_samples = int(sample_rate / fps)
            bit_duration_samples = frame_duration_samples // 80
            
            # Threshold audio signal
            threshold = np.std(audio_data) * 0.5
            digital_signal = np.where(audio_data > threshold, 1, -1)
            
            # Find transitions (edge detection)
            transitions = np.diff(digital_signal)
            transition_indices = np.where(np.abs(transitions) > 0)[0]
            
            if len(transition_indices) < 160:  # Need at least 2 frames worth
                return []
            
            # Group transitions into bits
            ltc_words = []
            current_bits = []
            bit_start = 0
            
            for i, trans_idx in enumerate(transition_indices):
                # Calculate expected bit position
                expected_bit_pos = trans_idx // bit_duration_samples
                
                if len(current_bits) == 0:
                    bit_start = expected_bit_pos
                
                relative_pos = expected_bit_pos - bit_start
                
                # Check if this is a data transition (at bit boundary) or clock transition (at bit center)
                bit_center_offset = (trans_idx % bit_duration_samples) / bit_duration_samples
                
                if 0.4 < bit_center_offset < 0.6:  # Clock transition at bit center
                    continue
                elif bit_center_offset < 0.2 or bit_center_offset > 0.8:  # Data transition at boundary
                    current_bits.append(1)  # Data '1' has transition at boundary
                else:
                    current_bits.append(0)  # Data '0' has no transition at boundary
                
                # Check if we have a complete 80-bit word
                if len(current_bits) >= 80:
                    ltc_words.append(current_bits[:80])
                    current_bits = []
                    bit_start = expected_bit_pos
            
            return ltc_words
            
        except Exception as e:
            print(f"Error extracting LTC bits: {e}")
            return []
    
    def analyze_ltc_signal(self) -> Optional[LTCAnalysis]:
        """Perform complete LTC signal analysis"""
        if self.audio_data is None:
            return None
            
        try:
            # Detect frame rate
            detected_frame_rate = self.detect_frame_rate(self.audio_data, self.sample_rate)
            if not detected_frame_rate:
                # Try common frame rates
                for frame_rate in [FrameRate.FR_30_NDF, FrameRate.FR_29_97_DF, FrameRate.FR_25_NDF]:
                    detected_frame_rate = frame_rate
                    break
            
            # Extract LTC bits
            ltc_words = self.extract_ltc_bits(self.audio_data, self.sample_rate, detected_frame_rate)
            
            # Decode timecode frames
            timecode_frames = []
            sync_word_count = 0
            errors = []
            
            for i, word_bits in enumerate(ltc_words):
                timecode_info = self.decode_ltc_word(word_bits)
                if timecode_info:
                    # Calculate timestamp in audio file
                    fps = detected_frame_rate.get_fps()
                    timecode_info.timestamp = i / fps
                    timecode_info.frame_rate = detected_frame_rate
                    timecode_frames.append(timecode_info)
                    sync_word_count += 1
                else:
                    errors.append(f"Failed to decode LTC word at position {i}")
            
            # Calculate signal quality
            total_words = len(ltc_words)
            valid_words = len(timecode_frames)
            signal_quality = valid_words / total_words if total_words > 0 else 0.0
            
            # Calculate duration
            duration = len(self.audio_data) / self.sample_rate
            
            self.analysis_results = LTCAnalysis(
                sample_rate=self.sample_rate,
                duration=duration,
                detected_frame_rate=detected_frame_rate,
                timecode_frames=timecode_frames,
                signal_quality=signal_quality,
                sync_word_count=sync_word_count,
                errors=errors[:10]  # Limit error list
            )
            
            return self.analysis_results
            
        except Exception as e:
            print(f"Error analyzing LTC signal: {e}")
            return None
    
    def get_timecode_at_position(self, position_seconds: float) -> Optional[TimecodeInfo]:
        """Get timecode at specific audio position"""
        if not self.analysis_results or not self.analysis_results.timecode_frames:
            return None
            
        # Find closest timecode frame
        closest_frame = None
        min_diff = float('inf')
        
        for frame in self.analysis_results.timecode_frames:
            diff = abs(frame.timestamp - position_seconds)
            if diff < min_diff:
                min_diff = diff
                closest_frame = frame
        
        return closest_frame
    
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
                    f.write(f"\nErrors ({len(self.analysis_results.errors)}):\n")
                    f.write("-" * 40 + "\n")
                    for error in self.analysis_results.errors:
                        f.write(f"- {error}\n")
            
            return True
            
        except Exception as e:
            print(f"Error exporting timecode list: {e}")
            return False
