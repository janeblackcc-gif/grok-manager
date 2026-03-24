# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('assets', 'assets')]
binaries = [('C:\\Users\\12695\\AppData\\Local\\Programs\\Python\\Python312\\Lib\\site-packages\\pywin32_system32\\pywintypes312.dll', '.'), ('C:\\Users\\12695\\AppData\\Local\\Programs\\Python\\Python312\\Lib\\site-packages\\pywin32_system32\\pythoncom312.dll', '.'), ('C:\\Users\\12695\\AppData\\Local\\Programs\\Python\\Python312\\Lib\\site-packages\\win32\\win32api.pyd', '.'), ('C:\\Users\\12695\\AppData\\Local\\Programs\\Python\\Python312\\Lib\\site-packages\\win32\\win32job.pyd', '.'), ('C:\\Users\\12695\\AppData\\Local\\Programs\\Python\\Python312\\Lib\\site-packages\\win32\\win32process.pyd', '.')]
hiddenimports = ['win32api', 'win32job', 'win32process', 'pywintypes', 'win32con']
tmp_ret = collect_all('customtkinter')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['main_gui.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['runtime_hook.py'],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='GrokManager',
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
    icon=['assets\\icon.ico'],
)
