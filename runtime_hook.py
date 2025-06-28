import os
import sys
import tempfile
import shutil
from pathlib import Path

# Get the path to the temporary directory PyInstaller creates
temp_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.getcwd()

# Copy all .lua and .manifest files from source to the current working directory
def copy_data_files():
    # Skip file copying when running as executable - files are already included
    if getattr(sys, 'frozen', False):  # Running as compiled executable
        return
    
    # Only copy files when running directly as Python script
    source_dir = os.path.dirname(os.path.abspath(__file__))
    dest_dir = os.getcwd()
    
    # Don't copy if source and destination are the same
    if os.path.normpath(source_dir) == os.path.normpath(dest_dir):
        return
        
    for file in os.listdir(source_dir):
        if file.endswith('.lua') or file.endswith('.manifest') or file.endswith('.st'):
            src = os.path.join(source_dir, file)
            dst = os.path.join(dest_dir, file)
            # Skip if files are identical to avoid unnecessary copies
            if os.path.exists(dst) and os.path.getsize(src) == os.path.getsize(dst):
                continue
            shutil.copy2(src, dst)
            print(f"Copied {file} to working directory from Python script")

# Always run the copy function regardless of frozen state
copy_data_files()

# Clean up memory by removing unused modules
# This reduces memory footprint and can reduce executable size slightly
def cleanup_modules():
    """Remove unnecessary modules from memory"""
    unnecessary_modules = [
        'ctypes.macholib', 'distutils', 'encodings.idna', 'encodings.utf_32',
        'encodings.utf_16', 'encodings.utf_7', 'encodings.utf_8_sig',
        'encodings.gb18030', 'encodings.gbk', 'encodings.gb2312',
        'encodings.cp950', 'encodings.cp949', 'encodings.cp936', 'encodings.cp932',
        'encodings.cp869', 'encodings.cp866', 'encodings.cp865', 'encodings.cp864',
        'encodings.cp863', 'encodings.cp862', 'encodings.cp861', 'encodings.cp860',
        'encodings.cp857', 'encodings.cp856', 'encodings.cp855', 'encodings.cp852',
        'encodings.cp775', 'encodings.cp720', 'encodings.cp437', 'curses', 'lzma', 
        'tty', 'unicodedata'
    ]
    
    for module in list(sys.modules.keys()):
        for unnecessary in unnecessary_modules:
            if module == unnecessary or module.startswith(f"{unnecessary}."):
                if module in sys.modules:
                    try:
                        del sys.modules[module]
                    except:
                        pass

cleanup_modules()
