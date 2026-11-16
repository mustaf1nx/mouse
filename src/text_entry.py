"""Clipboard and guarded plain text entry. Never submits or clears a field."""
import ctypes
from ctypes import wintypes
import json
import subprocess
import sys
import time


def copy_text(text):
    if sys.platform == 'darwin':
        subprocess.run(['pbcopy'],input=text.encode('utf-8'),check=True,timeout=3)
        return
    if sys.platform != 'win32':
        raise RuntimeError('Clipboard is supported on Windows and macOS')
    user=ctypes.WinDLL('user32',use_last_error=True)
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    user.OpenClipboard.argtypes=[wintypes.HWND]
    user.SetClipboardData.argtypes=[wintypes.UINT,wintypes.HANDLE]
    user.SetClipboardData.restype=wintypes.HANDLE
    user.CreateWindowExW.argtypes=[wintypes.DWORD,wintypes.LPCWSTR,wintypes.LPCWSTR,wintypes.DWORD,
                                  ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,
                                  wintypes.HWND,wintypes.HMENU,wintypes.HINSTANCE,ctypes.c_void_p]
    user.CreateWindowExW.restype=wintypes.HWND
    user.DestroyWindow.argtypes=[wintypes.HWND]
    kernel.GlobalAlloc.argtypes=[wintypes.UINT,ctypes.c_size_t]
    kernel.GlobalAlloc.restype=wintypes.HGLOBAL
    kernel.GlobalLock.argtypes=[wintypes.HGLOBAL]
    kernel.GlobalLock.restype=ctypes.c_void_p
    kernel.GlobalUnlock.argtypes=[wintypes.HGLOBAL]
    kernel.GlobalFree.argtypes=[wintypes.HGLOBAL]
    data=(text+'\0').encode('utf-16-le')
    handle=kernel.GlobalAlloc(0x0002,len(data))
    if not handle:raise ctypes.WinError(ctypes.get_last_error())
    opened=False
    owner=None
    try:
        owner=user.CreateWindowExW(0,'STATIC','MouseAssistantClipboard',0,0,0,0,0,wintypes.HWND(-3),None,None,None)
        if not owner:raise ctypes.WinError(ctypes.get_last_error())
        pointer=kernel.GlobalLock(handle)
        if not pointer:raise ctypes.WinError(ctypes.get_last_error())
        ctypes.memmove(pointer,data,len(data))
        kernel.GlobalUnlock(handle)
        for _ in range(10):
            if user.OpenClipboard(owner):opened=True;break
            time.sleep(.03)
        if not opened:raise RuntimeError('Clipboard is busy')
        if not user.EmptyClipboard():raise ctypes.WinError(ctypes.get_last_error())
        if not user.SetClipboardData(13,handle):raise ctypes.WinError(ctypes.get_last_error())
        handle=None  # Clipboard now owns the memory.
    finally:
        if opened:user.CloseClipboard()
        if owner:user.DestroyWindow(owner)
        if handle:kernel.GlobalFree(handle)


def foreground_is(window):
    if sys.platform!='win32' or window is None:return False
    api=ctypes.windll.user32
    api.GetForegroundWindow.restype=wintypes.HWND
    return api.GetForegroundWindow()==window


def focused_field():
    if sys.platform!='win32':return None
    # Read-only UI Automation: only the currently focused control is inspected.
    script=r'''$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
try {
 $e=[System.Windows.Automation.AutomationElement]::FocusedElement
 if ($null -eq $e -or $e.Current.IsPassword -or -not $e.Current.IsEnabled -or $e.Current.ControlType -ne [System.Windows.Automation.ControlType]::Edit) { '{}'; exit }
 $v=$e.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
 if ($v.Current.IsReadOnly) { '{}'; exit }
 $r=$e.Current.BoundingRectangle
 @{value=$v.Current.Value; bounds=@($r.Left,$r.Top,$r.Right,$r.Bottom); id=($e.GetRuntimeId() -join ',')} | ConvertTo-Json -Compress
} catch { '{}' }
'''
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],capture_output=True,timeout=4,creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:return None
    try:
        value=json.loads(result.stdout.decode('utf-8-sig'))
        return value if isinstance(value,dict) and isinstance(value.get('value'),str) and len(value.get('bounds',[]))==4 else None
    except (ValueError,UnicodeError):return None


def field_matches(focus, expected, click):
    if not focus:return False
    left,top,right,bottom=focus['bounds']
    x,y=click
    if not left<=x<right or not top<=y<bottom:return False
    l,t,r,b=expected
    overlap=max(0,min(right,r)-max(left,l))*max(0,min(bottom,b)-max(top,t))
    smaller=min((right-left)*(bottom-top),(r-l)*(b-t))
    return smaller>0 and overlap/smaller>=.6


def type_checked(text, field, click, window, cancel, validate, controller,
                 focus_reader=focused_field, foreground=foreground_is, validate_focused=None):
    if cancel.wait(.2) or not foreground(window):return 'cancelled before typing'
    focus=focus_reader()
    if not field_matches(focus,field,click):return 'cannot verify editable field; paste manually'
    if focus['value']!='':return 'field is not empty; automatic replacement skipped'
    if cancel.is_set():return 'input cancelled before validation'
    valid = validate_focused(focus['bounds']) if validate_focused else validate()
    if not valid or not foreground(window):return 'question changed; typing cancelled'
    # Confirm that validation did not race with a focus/content change.
    check=focus_reader()
    if not field_matches(check,field,click) or check.get('id')!=focus.get('id') or check['value']!='':
        return 'focus or field contents changed; typing cancelled'
    for char in text:
        if cancel.is_set() or not foreground(window):
            return 'typing interrupted; check partial text before pasting'
        controller.type(char)
        if cancel.wait(.02):return 'typing interrupted; check partial text before pasting'
    after=focus_reader()
    if after and after.get('id')==focus.get('id') and after['value']==text:
        return 'text entered and verified; submit manually'
    return 'input not verified; inspect the field before using clipboard'
