# -*- mode: python ; coding: utf-8 -*-
import os
import sys

# Add the steamctl directory to the path
steamctl_dir = os.path.join(os.path.dirname(os.path.abspath('__file__')), 'steamctl_trimmed')
sys.path.append(steamctl_dir)

a = Analysis(
    ['reboot_downloader.py'],
    pathex=[steamctl_dir],  # Add steamctl to path
    binaries=[],
    datas=[
        # Include files in both root and subdirectory for compatibility
        ('1244460.lua', '.'),  # Include in root for compatibility
        ('1244461_3466130684209996467.manifest', '.'),  # Include in root for compatibility 
        ('1244460.lua', 'resource_files'),  # Also in resource_files subdirectory
        ('228990_1829726630299308803.manifest', 'resource_files'),  # Also in resource_files subdirectory
        ('228988_6645201662696499616.manifest', 'resource_files'),  # Also in resource_files subdirectory
        ('steamctl_trimmed', 'steamctl_trimmed'),  # Include complete steamctl directory
    ],
    hiddenimports=['steamctl.commands.depot.gcmds'],  # Add hidden imports
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['runtime_hook.py'],  # Add runtime hook
    excludes=['tkinter', 'matplotlib', 'numpy', 'pandas', 'PyQt5', 'PySide2', 'PIL', 
              'scipy', 'xml', 'html', 'multiprocessing', 'pydoc', 
              'unittest', 'doctest', 'pdb', 'pywin', 'IPython', 'pkg_resources'],  # Exclude unnecessary modules
    noarchive=False,
    optimize=2,  # Use maximum optimization level
)
pyz = PYZ(a.pure, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Jurassic World Evolution 2',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,  # Strip symbols to reduce size
    upx=True,
    upx_exclude=[],
    upx_include=['vcruntime140.dll', 'python*.dll', 'ucrtbase.dll'],  # Target specific large DLLs
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico',
)
