#!/usr/bin/env python3
"""
Build script for creating executable versions of LTC Timecode Player
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

def install_pyinstaller():
    """Install PyInstaller if not already installed"""
    try:
        import PyInstaller
        print("✓ PyInstaller is already installed")
    except ImportError:
        print("Installing PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
        print("✓ PyInstaller installed successfully")

def clean_build_dirs():
    """Clean previous build directories"""
    dirs_to_clean = ['build', 'dist', '__pycache__']
    for dir_name in dirs_to_clean:
        if os.path.exists(dir_name):
            shutil.rmtree(dir_name)
            print(f"✓ Cleaned {dir_name} directory")

def create_spec_file():
    """Create PyInstaller spec file"""
    spec_content = '''# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('web', 'web'),
    ],
    hiddenimports=[
        'eel',
        'numpy',
        'scipy',
        'soundfile',
        'matplotlib',
        'matplotlib.backends.backend_agg',
        'tkinter',
        'tkinter.filedialog',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='LTC-Timecode-Player',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='web/favicon.ico' if os.path.exists('web/favicon.ico') else None,
)
'''
    
    with open('LTC-Timecode-Player.spec', 'w') as f:
        f.write(spec_content)
    print("✓ Created PyInstaller spec file")

def build_executable():
    """Build the executable"""
    print("Building executable...")
    print("This may take several minutes...")
    
    try:
        # Build using the spec file
        subprocess.check_call([
            sys.executable, "-m", "PyInstaller",
            "--clean",
            "--noconfirm",
            "LTC-Timecode-Player.spec"
        ])
        print("✓ Executable built successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"✗ Build failed: {e}")
        return False

def create_release_package():
    """Create a release package with documentation"""
    if not os.path.exists('dist/LTC-Timecode-Player.exe'):
        print("✗ Executable not found")
        return False
    
    # Create release directory
    release_dir = "release"
    if os.path.exists(release_dir):
        shutil.rmtree(release_dir)
    os.makedirs(release_dir)
    
    # Copy executable
    shutil.copy2('dist/LTC-Timecode-Player.exe', f'{release_dir}/LTC-Timecode-Player.exe')
    
    # Copy documentation
    files_to_copy = ['README.md', 'LICENSE']
    for file in files_to_copy:
        if os.path.exists(file):
            shutil.copy2(file, f'{release_dir}/{file}')
    
    # Create a simple usage file
    usage_content = """# LTC Timecode Player - Quick Start

## Running the Application
1. Double-click on LTC-Timecode-Player.exe
2. The application will open in your default web browser
3. Load an LTC audio file using drag & drop or the browse button

## Supported File Formats
- WAV files (*.wav)
- AIFF files (*.aiff)  
- FLAC files (*.flac)

## System Requirements
- Windows 10 or later
- Modern web browser (Chrome, Firefox, Edge)
- Minimum 4GB RAM recommended

## Troubleshooting
- If the application doesn't start, try running as administrator
- Make sure your antivirus isn't blocking the executable
- Check Windows Defender SmartScreen settings if blocked

## Support
For issues and support, visit:
https://github.com/sithulaka/LTC-Timecode-Player/issues
"""
    
    with open(f'{release_dir}/USAGE.txt', 'w') as f:
        f.write(usage_content)
    
    print(f"✓ Release package created in '{release_dir}' directory")
    return True

def main():
    """Main build process"""
    print("=" * 60)
    print("LTC Timecode Player - Executable Builder")
    print("=" * 60)
    
    # Check if we're in the right directory
    if not os.path.exists('app.py'):
        print("✗ Error: Please run this script from the LTC_Timecode_Player directory")
        return False
    
    # Install PyInstaller
    install_pyinstaller()
    
    # Clean previous builds
    clean_build_dirs()
    
    # Create spec file
    create_spec_file()
    
    # Build executable
    if not build_executable():
        return False
    
    # Create release package
    if not create_release_package():
        return False
    
    print("\n" + "=" * 60)
    print("✓ Build completed successfully!")
    print("=" * 60)
    print(f"Executable location: {os.path.abspath('dist/LTC-Timecode-Player.exe')}")
    print(f"Release package: {os.path.abspath('release/')}")
    print("\nTo test the executable:")
    print("1. Navigate to the 'dist' folder")
    print("2. Double-click on 'LTC-Timecode-Player.exe'")
    print("\nFor distribution, use the files in the 'release' folder")
    
    return True

if __name__ == "__main__":
    success = main()
    if not success:
        sys.exit(1)
