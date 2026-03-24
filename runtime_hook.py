import os
import sys

# When PyInstaller --onefile extracts to _MEIXXXXXX, pywintypes DLL
# may not be on the DLL search path. Fix it here.
_dll_dir_handle = None
if getattr(sys, 'frozen', False):
    base = sys._MEIPASS
    # Keep the handle alive so the directory stays on the search path
    if hasattr(os, 'add_dll_directory'):
        _dll_dir_handle = os.add_dll_directory(base)
    # Also prepend to PATH as fallback
    os.environ['PATH'] = base + os.pathsep + os.environ.get('PATH', '')
