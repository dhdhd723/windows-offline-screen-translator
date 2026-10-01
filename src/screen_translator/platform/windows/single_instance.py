from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes


class SingleInstance:
    """Session-scoped named mutex; initialization acquires it without waiting."""

    def __init__(self, name: str = "Local\\ScreenTranslatorOffline") -> None:
        self.name = name
        self._handle = None
        self.acquired = False
        self.already_running = False
        self.acquire()

    @property
    def is_primary(self) -> bool:
        return self.acquired

    def acquire(self) -> bool:
        if self._handle is not None:
            return self.acquired
        if sys.platform != "win32":
            self.acquired = True
            return True
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        handle = kernel32.CreateMutexW(None, True, self.name)
        if not handle:
            raise OSError(ctypes.get_last_error(), "无法创建程序单实例锁")
        self._handle = handle
        self.already_running = ctypes.get_last_error() == 183
        self.acquired = not self.already_running
        return self.acquired

    def close(self) -> None:
        if self._handle is not None and sys.platform == "win32":
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            if self.acquired:
                kernel32.ReleaseMutex(self._handle)
            kernel32.CloseHandle(self._handle)
        self._handle = None
        self.acquired = False

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        self.close()
