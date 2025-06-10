#!/usr/bin/env python3
"""
Test script for LTC Timecode Player
This script demonstrates the LTC player functionality without the web UI.
"""

import os
import sys
from ltc_decoder import LTCDecoder, TimecodeInfo, LTCAnalysis

def test_ltc_analysis():
    """Test LTC analysis with sample files"""
    
    print("LTC Timecode Player & Analyzer Test")
    print("=" * 45)
    
    # Check if we have any test files from the generator
    generator_path = "../LTC_Timecode_Generator"
    test_files = []
    
    if os.path.exists(generator_path):
        for file in os.listdir(generator_path):
            if file.endswith('.wav'):
                test_files.append(os.path.join(generator_path, file))
    
    # Also check current directory
    for file in os.listdir('.'):
        if file.endswith('.wav'):
            test_files.append(file)
    
    if not test_files:
        print("No test WAV files found.")
        print("Please run the LTC Generator first to create test files, or")
        print("place some LTC audio files in this directory.")
        return
    
    print(f"Found {len(test_files)} test file(s)")
    print("-" * 45)
    
    decoder = LTCDecoder()
    
    for i, file_path in enumerate(test_files[:3], 1):  # Test first 3 files
        print(f"\n{i}. Testing: {os.path.basename(file_path)}")
        print("-" * 30)
        
        try:
            # Load audio file
            success = decoder.load_audio_file(file_path)
            if not success:
                print(f"   ✗ Failed to load audio file")
                continue
            
            print(f"   ✓ Audio loaded successfully")
            print(f"   Sample Rate: {decoder.sample_rate} Hz")
            print(f"   Duration: {len(decoder.audio_data) / decoder.sample_rate:.2f} seconds")
            
            # Analyze LTC signal
            analysis = decoder.analyze_ltc_signal()
            if not analysis:
                print(f"   ✗ Failed to analyze LTC signal")
                continue
            
            print(f"   ✓ LTC analysis completed")
            print(f"   Frame Rate: {analysis.detected_frame_rate.get_display_name() if analysis.detected_frame_rate else 'Unknown'}")
            print(f"   Signal Quality: {analysis.signal_quality:.1%}")
            print(f"   Valid Frames: {len(analysis.timecode_frames)}")
            print(f"   Sync Words: {analysis.sync_word_count}")
            
            # Show first few timecode frames
            if analysis.timecode_frames:
                print(f"   First Timecode: {analysis.timecode_frames[0]}")
                if len(analysis.timecode_frames) > 1:
                    print(f"   Last Timecode: {analysis.timecode_frames[-1]}")
            
            # Test timecode extraction at specific positions
            test_positions = [0.0, analysis.duration / 2, analysis.duration - 1]
            for pos in test_positions:
                if pos >= 0 and pos < analysis.duration:
                    timecode = decoder.get_timecode_at_position(pos)
                    if timecode:
                        print(f"   Timecode at {pos:.1f}s: {timecode}")
            
            # Export report
            report_filename = f"{os.path.splitext(os.path.basename(file_path))[0]}_analysis.txt"
            if decoder.export_timecode_list(report_filename):
                print(f"   ✓ Report exported: {report_filename}")
            
            print(f"   Errors: {len(analysis.errors)}")
            if analysis.errors:
                for error in analysis.errors[:3]:  # Show first 3 errors
                    print(f"     - {error}")
                
        except Exception as e:
            print(f"   ✗ Error: {str(e)}")
    
    print(f"\n{'='*45}")
    print("Test completed!")
    print("\nTo use the web interface:")
    print("1. Run: python app.py")
    print("2. Open browser to http://localhost:8001")
    print("3. Load LTC audio files for analysis")

def demo_decoder_features():
    """Demonstrate decoder features"""
    print("\nLTC Decoder Features Demo")
    print("-" * 30)
    
    # Show supported frame rates
    from ltc_decoder import FrameRate
    print("Supported Frame Rates:")
    for frame_rate in FrameRate:
        fps = frame_rate.get_fps()
        drop_frame = " (Drop Frame)" if frame_rate.is_drop_frame() else ""
        print(f"  {frame_rate.get_display_name()}: {fps:.3f} fps{drop_frame}")
    
    print(f"\nDecoder Capabilities:")
    print("  • Bi-phase mark (Manchester) decoding")
    print("  • Automatic frame rate detection")
    print("  • Signal quality assessment")
    print("  • SMPTE sync word validation")
    print("  • User bits extraction")
    print("  • Drop frame compensation")
    print("  • Comprehensive error reporting")
    
    print(f"\nFile Format Support:")
    print("  • WAV (most common)")
    print("  • AIFF (Apple/Pro Tools)")
    print("  • FLAC (lossless compression)")
    print("  • Mono and stereo (auto-converted)")
    print("  • 16-bit and 24-bit depth")
    print("  • 44.1kHz to 192kHz sample rates")

if __name__ == "__main__":
    # Check if we're in the right directory
    if not os.path.exists("ltc_decoder.py"):
        print("Error: Please run this script from the LTC_Timecode_Player directory")
        sys.exit(1)
    
    # Show decoder features
    demo_decoder_features()
    
    # Run tests
    test_ltc_analysis()
