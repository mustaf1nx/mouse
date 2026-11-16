"""Select a stable window region; no mouse input is generated here."""
import ctypes
from ctypes import wintypes
import sys


def clip_rect(rect, desktop):
    x, y, width, height = desktop
    left, top, right, bottom = rect
    left, top = max(left, x), max(top, y)
    right, bottom = min(right, x + width), min(bottom, y + height)
    if right <= left or bottom <= top:
        raise ValueError('Window is outside the supported screen')
    return left, top, right - left, bottom - top


def _api():
    api = ctypes.windll.user32
    api.WindowFromPoint.argtypes = [wintypes.POINT]
    api.WindowFromPoint.restype = wintypes.HWND
    api.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    api.GetAncestor.restype = wintypes.HWND
    api.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    api.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    api.IsWindowVisible.argtypes = [wintypes.HWND]
    api.IsIconic.argtypes = [wintypes.HWND]
    api.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    return api


def window_rect(handle, desktop):
    api = _api()
    if not api.IsWindowVisible(handle) or api.IsIconic(handle):
        raise ValueError('Question window is hidden or closed')
    rect, origin = wintypes.RECT(), wintypes.POINT(0, 0)
    if not api.GetClientRect(handle, ctypes.byref(rect)) or not api.ClientToScreen(handle, ctypes.byref(origin)):
        raise ValueError('Cannot read question window geometry')
    return clip_rect((origin.x, origin.y, origin.x + rect.right, origin.y + rect.bottom), desktop)


def select_region(position, desktop):
    if sys.platform != 'win32':
        return desktop, None
    api = _api()
    handle = api.GetAncestor(api.WindowFromPoint(wintypes.POINT(*map(int, position))), 2)
    if not handle:
        raise ValueError('Point the cursor at the question window before triggering')
    name = ctypes.create_unicode_buffer(256)
    api.GetClassNameW(handle, name, len(name))
    if name.value in ('ConsoleWindowClass', 'CASCADIA_HOSTING_WINDOW_CLASS', 'Progman', 'WorkerW', 'Shell_TrayWnd'):
        raise ValueError('Trigger over the question window, not the console or desktop')
    return window_rect(handle, desktop), handle


def region_unchanged(handle, rect, desktop):
    if handle is None:
        return rect == desktop
    try:
        return window_rect(handle, desktop) == rect
    except ValueError:
        return False
