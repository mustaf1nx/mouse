"""Process-lifetime lock for a single installation of the client."""
import ctypes
import hashlib
import os
from pathlib import Path
import sys


class InstanceLock:
    def __init__(self):
        self.handle = None
        self.file = None

    def acquire(self):
        if sys.platform == 'win32':
            from ctypes import wintypes
            api = ctypes.WinDLL('kernel32', use_last_error=True)
            api.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
            api.CreateMutexW.restype = wintypes.HANDLE
            api.CloseHandle.argtypes = [wintypes.HANDLE]
            key = hashlib.sha256(str(Path(sys.executable if getattr(sys, 'frozen', False) else __file__).resolve().parent).lower().encode()).hexdigest()[:24]
            handle = api.CreateMutexW(None, False, 'Local\\MouseAssistant-' + key)
            if not handle:
                raise ctypes.WinError(ctypes.get_last_error())
            if ctypes.get_last_error() == 183:
                api.CloseHandle(handle)
                return False
            self.handle, self.api = handle, api
        else:
            import fcntl
            self.file = open(Path(__file__).with_name('.instance.lock'), 'a')
            try:
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                self.file.close()
                self.file = None
                return False
        return True

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None
        if self.file:
            self.file.close()
            self.file = None

