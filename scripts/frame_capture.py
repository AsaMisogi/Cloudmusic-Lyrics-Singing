"""抓取测试窗口本身（含系统标题栏），不读取桌面或其他应用的内容。"""
import ctypes
from ctypes import wintypes
from PySide6.QtGui import QImage


def grab_frame(window):
    """返回以物理像素计的完整窗口及标题栏中线；ClientToScreen 自动纳入当前 DPI。"""
    user, gdi = ctypes.windll.user32, ctypes.windll.gdi32
    hwnd = wintypes.HWND(int(window.winId()))
    rect, origin = wintypes.RECT(), wintypes.POINT()
    user.GetWindowRect(hwnd, ctypes.byref(rect))
    user.ClientToScreen(hwnd, ctypes.byref(origin))
    user.GetWindowDC.restype = wintypes.HDC
    gdi.CreateCompatibleDC.restype = wintypes.HDC
    gdi.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi.SelectObject.restype = wintypes.HGDIOBJ
    source = wintypes.HDC(user.GetWindowDC(hwnd))
    memory = wintypes.HDC(gdi.CreateCompatibleDC(source))
    bitmap = wintypes.HBITMAP(gdi.CreateCompatibleBitmap(source, rect.right-rect.left, rect.bottom-rect.top))
    previous = wintypes.HGDIOBJ(gdi.SelectObject(memory, bitmap))
    try:
        # PW_RENDERFULLCONTENT 包含 Qt WebEngine 的子窗口和 Windows 合成的标题栏。
        if not user.PrintWindow(hwnd, memory, 2):
            raise RuntimeError("Windows 未返回窗口图像")
        return QImage.fromHBITMAP(bitmap.value), (origin.y-rect.top)//2
    finally:
        gdi.SelectObject(memory, previous)
        gdi.DeleteObject(bitmap)
        gdi.DeleteDC(memory)
        user.ReleaseDC(hwnd, source)
