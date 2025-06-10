# LTC Timecode Player - Documentation

## Overview
This documentation provides detailed information about the LTC Timecode Player application.

## Screenshots
- `screenshot.png` - Main application interface
- `analysis-view.png` - LTC analysis results
- `player-controls.png` - Timecode player interface

## Technical Documentation

### Architecture
The application consists of:
- **Backend**: Python with Eel framework for web interface
- **Frontend**: HTML/CSS/JavaScript for user interface
- **Core Engine**: Custom LTC decoder implementing SMPTE standards

### LTC Decoding Algorithm
1. **Signal Preprocessing**: Bandpass filtering to isolate LTC frequencies
2. **Edge Detection**: Manchester encoding transition detection
3. **Bit Recovery**: Convert analog transitions to digital bits
4. **Frame Sync**: Locate SMPTE sync words (0x3FFD)
5. **Data Extraction**: Parse timecode and user bits
6. **Validation**: Quality assessment and error detection

### Supported Standards
- **SMPTE 12M**: Linear Time Code standard
- **IEC 60461**: Audio timecode specification
- **ITU-R BR.780**: Broadcasting timecode systems

## API Reference

### Core Functions
- `load_ltc_file(file_path)` - Load and analyze LTC audio file
- `get_timecode_at_position(seconds)` - Get timecode at specific position
- `get_timecode_list(start, count)` - Get paginated timecode frames
- `validate_ltc_signal()` - Perform signal quality validation
- `export_timecode_report()` - Generate analysis report

### Frame Rate Detection
Automatic detection of standard broadcast frame rates:
- 23.976, 24, 25, 29.97, 30, 50, 59.94, 60 fps
- Drop frame and non-drop frame support

## Development

### Building from Source
```bash
git clone https://github.com/sithulaka/LTC-Timecode-Player.git
cd LTC-Timecode-Player
pip install -r requirements.txt
python app.py
```

### Creating Executable
```bash
python build_executable.py
```

### Running Tests
```bash
python test_player.py
```

## Troubleshooting

### Common Issues
1. **File Not Found**: Check file path and permissions
2. **No LTC Signal**: Verify file contains actual LTC audio
3. **Poor Quality**: Check source audio for noise/distortion
4. **Frame Rate Issues**: Ensure standard broadcast frame rates

### Performance Tips
- Use WAV files for best compatibility
- Avoid very large files (>100MB) for faster processing
- Close other applications for better performance
- Use SSD storage for faster file access

## License
MIT License - see LICENSE file for details
