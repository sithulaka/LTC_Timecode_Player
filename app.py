import eel
import os
import sys
import json
import tempfile
import atexit
from pathlib import Path
from ltc_decoder import LTCDecoder, TimecodeInfo, LTCAnalysis
import numpy as np
import soundfile as sf
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
import matplotlib.pyplot as plt
import base64
from io import BytesIO

# Global decoder instance
ltc_decoder = LTCDecoder()
current_file_path = None
playback_position = 0.0

# Track temp files for cleanup (Issue #7)
_temp_files = set()


def _cleanup_temp_files():
    """Remove any remaining temp files on exit."""
    for path in list(_temp_files):
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass

atexit.register(_cleanup_temp_files)


@eel.expose
def load_ltc_file(file_path):
    """Load LTC audio file for analysis"""
    global current_file_path, ltc_decoder

    try:
        # Issue #18: removed redundant os.path.exists check inside the not-exists block
        if not os.path.exists(file_path):
            # If file doesn't exist as provided, it might be just a filename
            # Let's try to find it in common locations
            possible_paths = []

            # Try user's desktop
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            desktop_path = os.path.join(desktop, file_path)
            if os.path.exists(desktop_path):
                possible_paths.append(desktop_path)

            # Try user's Downloads folder
            downloads = os.path.join(os.path.expanduser("~"), "Downloads")
            downloads_path = os.path.join(downloads, file_path)
            if os.path.exists(downloads_path):
                possible_paths.append(downloads_path)

            # Try Documents folder
            documents = os.path.join(os.path.expanduser("~"), "Documents")
            documents_path = os.path.join(documents, file_path)
            if os.path.exists(documents_path):
                possible_paths.append(documents_path)

            if possible_paths:
                file_path = possible_paths[0]  # Use first found path
            else:
                return {"success": False, "message": f"File not found: {file_path}. Please ensure the file exists and try using the full file path."}

        # Load audio file
        success = ltc_decoder.load_audio_file(file_path)
        if not success:
            return {"success": False, "message": "Failed to load audio file"}

        # Analyze LTC signal
        analysis = ltc_decoder.analyze_ltc_signal()
        if not analysis:
            return {"success": False, "message": "Failed to analyze LTC signal"}

        current_file_path = file_path

        # Get file size for the response (Issue #6 frontend support) — before cleanup
        try:
            file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
        except OSError:
            file_size = 0

        # Issue #7: clean up temp file after analysis if it was a temp upload
        if file_path in _temp_files:
            try:
                os.remove(file_path)
            except OSError:
                pass
            _temp_files.discard(file_path)

        # Return analysis results
        return {
            "success": True,
            "message": "LTC file loaded successfully",
            "analysis": {
                "filename": os.path.basename(file_path),
                "file_size": file_size,
                "sample_rate": analysis.sample_rate,
                "duration": analysis.duration,
                "frame_rate": analysis.detected_frame_rate.get_display_name() if analysis.detected_frame_rate else "Unknown",
                "signal_quality": analysis.signal_quality,
                "valid_frames": len(analysis.timecode_frames),
                "sync_word_count": analysis.sync_word_count,
                "errors": analysis.errors
            }
        }

    except Exception as e:
        return {"success": False, "message": f"Error: {str(e)}"}

@eel.expose
def save_uploaded_file(file_data, filename):
    """Save uploaded file data to temporary location for processing"""
    try:
        # Create a temporary file
        temp_dir = tempfile.gettempdir()
        temp_path = os.path.join(temp_dir, f"ltc_upload_{filename}")

        # Decode base64 file data and save
        file_bytes = base64.b64decode(file_data.split(',')[1])  # Remove data URL prefix

        with open(temp_path, 'wb') as f:
            f.write(file_bytes)

        # Issue #7: track temp file for cleanup
        _temp_files.add(temp_path)

        return {
            "success": True,
            "temp_path": temp_path,
            "message": f"File uploaded successfully to {temp_path}"
        }

    except Exception as e:
        return {"success": False, "message": f"Error uploading file: {str(e)}"}

@eel.expose
def browse_for_file():
    """Open file browser dialog for selecting an LTC audio file"""  # Issue #19: cross-platform description
    try:
        import tkinter as tk
        from tkinter import filedialog

        # Create root window but hide it
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)

        # Open file dialog
        file_path = filedialog.askopenfilename(
            title="Select LTC Audio File",
            filetypes=[
                ("Audio files", "*.wav *.aiff *.flac"),
                ("WAV files", "*.wav"),
                ("AIFF files", "*.aiff"),
                ("FLAC files", "*.flac"),
                ("All files", "*.*")
            ]
        )

        root.destroy()

        if file_path:
            return {"success": True, "file_path": file_path}
        else:
            return {"success": False, "message": "No file selected"}

    except ImportError:
        return {"success": False, "message": "File browser not available. Please drag and drop files or provide the full file path."}
    except Exception as e:
        return {"success": False, "message": f"Error opening file browser: {str(e)}"}

@eel.expose
def get_timecode_at_position(position_seconds):
    """Get timecode at specific position in audio"""
    global ltc_decoder

    try:
        timecode_info = ltc_decoder.get_timecode_at_position(float(position_seconds))
        if timecode_info:
            return {
                "success": True,
                "timecode": {
                    "hours": timecode_info.hours,
                    "minutes": timecode_info.minutes,
                    "seconds": timecode_info.seconds,
                    "frames": timecode_info.frames,
                    "drop_frame": timecode_info.drop_frame,
                    "frame_rate": timecode_info.frame_rate.get_display_name(),
                    "timestamp": timecode_info.timestamp,
                    "user_bits": timecode_info.user_bits,
                    "formatted": str(timecode_info)
                }
            }
        else:
            return {"success": False, "message": "No timecode found at position"}

    except Exception as e:
        return {"success": False, "message": f"Error: {str(e)}"}

@eel.expose
def get_timecode_list(start_time=0, count=50):
    """Get list of timecode frames"""
    global ltc_decoder

    try:
        if not ltc_decoder.analysis_results:
            return {"success": False, "message": "No analysis data available"}

        frames = ltc_decoder.analysis_results.timecode_frames
        start_idx = int(start_time * (ltc_decoder.analysis_results.detected_frame_rate.get_fps() if ltc_decoder.analysis_results.detected_frame_rate else 30))
        end_idx = min(start_idx + count, len(frames))

        timecode_list = []
        for i in range(start_idx, end_idx):
            frame = frames[i]
            timecode_list.append({
                "index": i,
                "timestamp": frame.timestamp,
                "timecode": str(frame),
                "hours": frame.hours,
                "minutes": frame.minutes,
                "seconds": frame.seconds,
                "frames": frame.frames,
                "drop_frame": frame.drop_frame,
                "user_bits": frame.user_bits
            })

        return {
            "success": True,
            "timecode_list": timecode_list,
            "total_frames": len(frames)
        }

    except Exception as e:
        return {"success": False, "message": f"Error: {str(e)}"}

@eel.expose
def generate_waveform():
    """Generate waveform visualization"""
    global ltc_decoder

    try:
        if ltc_decoder.audio_data is None:
            return {"success": False, "message": "No audio data loaded"}

        # Create waveform plot
        plt.figure(figsize=(12, 4))

        # Downsample for visualization if needed
        audio_data = ltc_decoder.audio_data
        sample_rate = ltc_decoder.sample_rate

        if len(audio_data) > 100000:  # Downsample if too many samples
            factor = len(audio_data) // 100000
            audio_data = audio_data[::factor]
            sample_rate = sample_rate // factor

        # Time axis
        time_axis = np.linspace(0, len(audio_data) / sample_rate, len(audio_data))

        # Plot waveform
        plt.plot(time_axis, audio_data, color='#667eea', linewidth=0.5)
        plt.fill_between(time_axis, audio_data, alpha=0.3, color='#667eea')

        plt.title('LTC Audio Waveform', fontsize=14, fontweight='bold')
        plt.xlabel('Time (seconds)', fontsize=12)
        plt.ylabel('Amplitude', fontsize=12)
        plt.grid(True, alpha=0.3)
        plt.tight_layout()

        # Convert to base64 for web display
        buffer = BytesIO()
        plt.savefig(buffer, format='png', dpi=100, bbox_inches='tight')
        buffer.seek(0)
        image_base64 = base64.b64encode(buffer.getvalue()).decode()
        plt.close()

        return {
            "success": True,
            "waveform_image": f"data:image/png;base64,{image_base64}"
        }

    except Exception as e:
        return {"success": False, "message": f"Error generating waveform: {str(e)}"}

@eel.expose
def export_timecode_report():
    """Export timecode analysis report"""
    global ltc_decoder, current_file_path

    try:
        if not ltc_decoder.analysis_results or not current_file_path:
            return {"success": False, "message": "No analysis data available"}

        # Generate report filename
        base_name = os.path.splitext(os.path.basename(current_file_path))[0]
        report_filename = f"{base_name}_timecode_report.txt"

        # Issue #13: determine a writable output directory
        output_dir = os.path.dirname(current_file_path)
        temp_dir = tempfile.gettempdir()

        # Fall back if the directory is inside temp or not writable
        if output_dir.startswith(temp_dir) or not os.access(output_dir, os.W_OK):
            # Try Desktop first, then home directory
            desktop_dir = os.path.join(os.path.expanduser("~"), "Desktop")
            if os.path.isdir(desktop_dir) and os.access(desktop_dir, os.W_OK):
                output_dir = desktop_dir
            else:
                output_dir = os.path.expanduser("~")

        output_path = os.path.join(output_dir, report_filename)

        # Export report
        success = ltc_decoder.export_timecode_list(output_path)

        if success:
            return {
                "success": True,
                "message": f"Report exported successfully",
                "filename": report_filename,
                "path": output_path
            }
        else:
            return {"success": False, "message": "Failed to export report"}

    except Exception as e:
        return {"success": False, "message": f"Error: {str(e)}"}

@eel.expose
def get_audio_info():
    """Get basic audio file information"""
    global ltc_decoder, current_file_path

    try:
        if not current_file_path or ltc_decoder.audio_data is None:
            return {"success": False, "message": "No audio file loaded"}

        file_size = os.path.getsize(current_file_path)
        duration = len(ltc_decoder.audio_data) / ltc_decoder.sample_rate

        return {
            "success": True,
            "info": {
                "filename": os.path.basename(current_file_path),
                "file_size": file_size,
                "duration": duration,
                "sample_rate": ltc_decoder.sample_rate,
                "channels": 1 if len(ltc_decoder.audio_data.shape) == 1 else ltc_decoder.audio_data.shape[1],
                "samples": len(ltc_decoder.audio_data)
            }
        }

    except Exception as e:
        return {"success": False, "message": f"Error: {str(e)}"}

@eel.expose
def get_file_size(file_path):
    """Return the file size in bytes for the given path (Issue #6 frontend support)"""
    try:
        if not file_path or not os.path.exists(file_path):
            return {"success": False, "message": "File not found"}
        size = os.path.getsize(file_path)
        return {"success": True, "file_size": size}
    except Exception as e:
        return {"success": False, "message": f"Error: {str(e)}"}

@eel.expose
def serve_audio_file():
    """Return the current audio file as base64-encoded data for browser playback (Issue #5 support)"""
    global current_file_path
    try:
        if not current_file_path or not os.path.exists(current_file_path):
            return {"success": False, "message": "No audio file loaded"}

        with open(current_file_path, 'rb') as f:
            raw = f.read()

        ext = os.path.splitext(current_file_path)[1].lower()
        mime_types = {
            '.wav': 'audio/wav',
            '.aiff': 'audio/aiff',
            '.aif': 'audio/aiff',
            '.flac': 'audio/flac',
        }
        mime = mime_types.get(ext, 'application/octet-stream')

        encoded = base64.b64encode(raw).decode('ascii')
        data_url = f"data:{mime};base64,{encoded}"

        return {"success": True, "audio_data": data_url}
    except Exception as e:
        return {"success": False, "message": f"Error: {str(e)}"}

@eel.expose
def validate_ltc_signal():
    """Validate LTC signal integrity"""
    global ltc_decoder

    try:
        if not ltc_decoder.analysis_results:
            return {"success": False, "message": "No analysis data available"}

        analysis = ltc_decoder.analysis_results

        # Issue #9: use total_error_count and handle zero-frame case
        total_frames = len(analysis.timecode_frames)
        error_count = analysis.total_error_count if hasattr(analysis, 'total_error_count') else len(analysis.errors)

        # Validation criteria
        validations = {
            "signal_detected": total_frames > 0,
            "good_quality": analysis.signal_quality > 0.8,
            "frame_rate_detected": analysis.detected_frame_rate is not None,
            "continuous_timecode": total_frames > 10,
            "low_error_rate": True if total_frames == 0 else error_count < total_frames * 0.1
        }

        overall_valid = all(validations.values())

        return {
            "success": True,
            "validation": {
                "overall_valid": overall_valid,
                "checks": validations,
                "signal_quality_percent": round(analysis.signal_quality * 100, 1),
                "error_count": error_count,
                "recommendations": _get_validation_recommendations(validations, analysis)
            }
        }

    except Exception as e:
        return {"success": False, "message": f"Error: {str(e)}"}

def _get_validation_recommendations(validations, analysis):
    """Get recommendations based on validation results"""
    recommendations = []

    if not validations["signal_detected"]:
        recommendations.append("No LTC signal detected. Check if file contains valid LTC audio.")

    if not validations["good_quality"]:
        recommendations.append(f"Signal quality is {analysis.signal_quality:.1%}. Consider using a cleaner source.")

    if not validations["frame_rate_detected"]:
        recommendations.append("Frame rate could not be detected automatically.")

    if not validations["continuous_timecode"]:
        recommendations.append("Timecode appears to be intermittent or very short.")

    if not validations["low_error_rate"]:
        recommendations.append("High error rate detected. Check for signal distortion or noise.")

    if not recommendations:
        recommendations.append("LTC signal appears to be valid and of good quality.")

    return recommendations


# Issue #29: close callback to prevent zombie process
def _on_close(page, sockets):
    """Handle browser window close to prevent zombie process."""
    sys.exit(0)


def main():
    """Main application entry point"""
    # Issue #12: init eel inside main using the script's directory
    web_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web')
    eel.init(web_dir)

    # Issue #11: try a range of ports to avoid conflicts
    ports_to_try = list(range(8001, 8011))  # 8001-8010
    last_error = None

    for port in ports_to_try:
        try:
            # Start Eel with Chrome
            eel.start('index.html', size=(1200, 800), port=port, close_callback=_on_close)
            return  # If start returns normally, we're done
        except OSError as e:
            last_error = e
            continue
        except EnvironmentError:
            # Fallback to Edge on Windows or default browser elsewhere
            try:
                # Issue #10: only check 'win32' (not 'win64')
                if sys.platform == 'win32':
                    eel.start('index.html', mode='edge', port=port, close_callback=_on_close)
                else:
                    eel.start('index.html', mode='default', port=port, close_callback=_on_close)
                return
            except OSError as e:
                last_error = e
                continue

    # All fixed ports failed; let the OS pick one (port=0)
    try:
        eel.start('index.html', size=(1200, 800), port=0, close_callback=_on_close)
    except EnvironmentError:
        if sys.platform == 'win32':
            eel.start('index.html', mode='edge', port=0, close_callback=_on_close)
        else:
            eel.start('index.html', mode='default', port=0, close_callback=_on_close)


if __name__ == "__main__":
    main()
