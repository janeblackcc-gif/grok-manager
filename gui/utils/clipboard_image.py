from __future__ import annotations

import io
import sys

from PIL import Image


def copy_image_to_clipboard(path: str) -> None:
    if not sys.platform.startswith("win"):
        raise RuntimeError("当前平台不支持图像剪贴板复制")

    import win32clipboard

    with Image.open(path) as img:
        output = io.BytesIO()
        img.convert("RGB").save(output, "BMP")
        data = output.getvalue()[14:]

    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32clipboard.CF_DIB, data)
    finally:
        win32clipboard.CloseClipboard()
