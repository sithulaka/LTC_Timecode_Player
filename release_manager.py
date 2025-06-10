#!/usr/bin/env python3
"""
Release management script for LTC Timecode Player
"""

import os
import sys
import json
import subprocess
from datetime import datetime

VERSION_FILE = "version.json"

def get_current_version():
    """Get current version from version file"""
    if os.path.exists(VERSION_FILE):
        with open(VERSION_FILE, 'r') as f:
            data = json.load(f)
            return data.get('version', '1.0.0')
    return '1.0.0'

def update_version(new_version):
    """Update version in version file"""
    data = {
        'version': new_version,
        'build_date': datetime.now().isoformat(),
        'build_number': get_build_number()
    }
    
    with open(VERSION_FILE, 'w') as f:
        json.dump(data, f, indent=2)
    
    print(f"✓ Updated version to {new_version}")

def get_build_number():
    """Generate build number based on timestamp"""
    return int(datetime.now().timestamp())

def create_git_tag(version):
    """Create git tag for the version"""
    try:
        # Check if we're in a git repository
        subprocess.check_call(['git', 'status'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # Add all files
        subprocess.check_call(['git', 'add', '.'])
        
        # Commit changes
        commit_message = f"Release version {version}"
        subprocess.check_call(['git', 'commit', '-m', commit_message])
        
        # Create tag
        tag_name = f"v{version}"
        subprocess.check_call(['git', 'tag', '-a', tag_name, '-m', f"Version {version}"])
        
        print(f"✓ Created git tag: {tag_name}")
        print("To push the release, run:")
        print(f"  git push origin main")
        print(f"  git push origin {tag_name}")
        
        return True
        
    except subprocess.CalledProcessError:
        print("✗ Git operations failed")
        return False
    except FileNotFoundError:
        print("✗ Git not found")
        return False

def build_release(version):
    """Build the release executable"""
    print(f"Building release for version {version}...")
    
    # Update version in the app
    update_app_version(version)
    
    # Run build script
    try:
        subprocess.check_call([sys.executable, 'build_executable.py'])
        print("✓ Release build completed")
        return True
    except subprocess.CalledProcessError:
        print("✗ Build failed")
        return False

def update_app_version(version):
    """Update version in app.py"""
    app_file = "app.py"
    
    # Read current app.py
    with open(app_file, 'r') as f:
        content = f.read()
    
    # Add version info at the top
    version_comment = f'# LTC Timecode Player v{version}\n# Build date: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n\n'
    
    # If version comment already exists, replace it
    lines = content.split('\n')
    if lines[0].startswith('# LTC Timecode Player v'):
        # Remove existing version lines
        while lines and lines[0].startswith('#'):
            lines.pop(0)
        # Remove empty line after comments
        if lines and lines[0].strip() == '':
            lines.pop(0)
        content = '\n'.join(lines)
    
    # Add new version comment
    content = version_comment + content
    
    # Write back to file
    with open(app_file, 'w') as f:
        f.write(content)
    
    print(f"✓ Updated app.py with version {version}")

def main():
    """Main release process"""
    print("=" * 50)
    print("LTC Timecode Player - Release Manager")
    print("=" * 50)
    
    current_version = get_current_version()
    print(f"Current version: {current_version}")
    
    # Ask for new version
    new_version = input(f"Enter new version (current: {current_version}): ").strip()
    
    if not new_version:
        print("No version provided, exiting.")
        return
    
    # Validate version format (simple check)
    if not new_version.replace('.', '').replace('-', '').replace('_', '').isalnum():
        print("Invalid version format")
        return
    
    print(f"Preparing release for version {new_version}")
    
    # Update version
    update_version(new_version)
    
    # Build release
    if not build_release(new_version):
        print("Build failed, aborting release")
        return
    
    # Create git tag
    create_git = input("Create git tag and commit? (y/n): ").strip().lower()
    if create_git == 'y':
        create_git_tag(new_version)
    
    print("\n" + "=" * 50)
    print("✓ Release preparation completed!")
    print("=" * 50)
    print(f"Version: {new_version}")
    print(f"Executable: dist/LTC-Timecode-Player.exe")
    print(f"Release package: release/")
    
    if create_git == 'y':
        print("\nNext steps:")
        print("1. Push changes to GitHub:")
        print("   git push origin main")
        print(f"   git push origin v{new_version}")
        print("2. GitHub Actions will automatically create the release")
        print("3. Download and test the release artifacts")

if __name__ == "__main__":
    main()
