"""给系统标题栏着色。保持原生窗口样式，让 Windows 负责贴靠、缩放和系统菜单。"""

import ctypes
import logging
import re
import sys
from ctypes import wintypes


def apply_frame_theme(window, dark: bool, background: str, text: str):
    """Windows 11 接受指定标题色；旧系统沿用系统能提供的明暗窗口外观。"""
    if sys.platform != "win32" or not all(re.fullmatch(r"#[0-9a-fA-F]{6}", c) for c in (background, text)):
        return
    build = sys.getwindowsversion().build
    if build < 17763:
        return
    # COLORREF 以 0x00BBGGRR 表示而非 CSS 的 RRGGBB；HWND 在 x64 下是指针宽度。
    hwnd = wintypes.HWND(int(window.winId()))
    set_attr = ctypes.windll.dwmapi.DwmSetWindowAttribute

    def set_value(attribute, value):
        data = wintypes.DWORD(value)
        hr = set_attr(hwnd, attribute, ctypes.byref(data), ctypes.sizeof(data))
        if hr and build >= 22000:
            logging.getLogger(__name__).debug("标题栏属性 %s 未应用：HRESULT %s", attribute, hr)

    set_value(20 if build >= 18985 else 19, int(dark))
    if build >= 22000:
        for attribute, color in ((35, background), (36, text)):
            set_value(attribute, int.from_bytes(bytes.fromhex(color[1:]), "little"))
