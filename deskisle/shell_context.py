"""Typed COM calls for shell menus, including IContextMenu2/3 message handling.

pywin32 exposes the IContextMenu2/3 IIDs but some builds do not register Python
wrappers for them. Use the actual COM vtables instead of relying on wrappers.
This module is imported only by the Windows menu helper.
"""
from __future__ import annotations

import ctypes as ct
from ctypes import wintypes as wt
from uuid import UUID


class GUID(ct.Structure):
    _fields_ = [('data', ct.c_ubyte * 16)]

    @classmethod
    def parse(cls, value):
        return cls.from_buffer_copy(UUID(str(value).strip('{}')).bytes_le)


class InvokeInfo(ct.Structure):
    _fields_ = [('cbSize', wt.DWORD), ('fMask', wt.DWORD), ('hwnd', wt.HWND),
                ('lpVerb', ct.c_void_p), ('lpParameters', ct.c_char_p),
                ('lpDirectory', ct.c_char_p), ('nShow', ct.c_int),
                ('dwHotKey', wt.DWORD), ('hIcon', wt.HANDLE)]


def _check(hr):
    if hr < 0:
        raise OSError(f'Windows Shell HRESULT 0x{hr & 0xFFFFFFFF:08X}')
    return hr


def _call(pointer, slot, argtypes, *args, restype=ct.c_long):
    table = ct.cast(pointer, ct.POINTER(ct.POINTER(ct.c_void_p))).contents
    method = ct.WINFUNCTYPE(restype, ct.c_void_p, *argtypes)(table[slot])
    return method(pointer, *args)


class ShellContext:
    def __init__(self, pointer):
        self.pointer = pointer

    def close(self):
        if self.pointer:
            _call(self.pointer, 2, [], restype=wt.ULONG)
            self.pointer = None

    def QueryInterface(self, iid):  # noqa: N802
        result = ct.c_void_p()
        guid = GUID.parse(iid)
        _check(_call(self.pointer, 0, [ct.POINTER(GUID), ct.POINTER(ct.c_void_p)],
                     ct.byref(guid), ct.byref(result)))
        return ShellContext(result)

    def QueryContextMenu(self, menu, index, first, last, flags):  # noqa: N802
        return _check(_call(self.pointer, 3, [wt.HMENU, wt.UINT, wt.UINT, wt.UINT, wt.UINT],
                            menu, index, first, last, flags)) & 0xFFFF

    def InvokeCommand(self, args):  # noqa: N802
        mask, hwnd, verb, parameters, directory, show, hotkey, icon = args
        info = InvokeInfo(ct.sizeof(InvokeInfo), mask, hwnd, verb, parameters,
                          directory, show, hotkey, icon)
        _check(_call(self.pointer, 4, [ct.POINTER(InvokeInfo)], ct.byref(info)))

    def GetCommandString(self, index, flags=0):  # noqa: N802
        buffer = ct.create_string_buffer(1024)
        _check(_call(self.pointer, 5, [ct.c_size_t, wt.UINT, ct.c_void_p, ct.c_void_p, wt.UINT],
                     index, flags, None, buffer, len(buffer)))
        return buffer.value

    def HandleMenuMsg(self, msg, wp, lp):  # noqa: N802
        _check(_call(self.pointer, 6, [wt.UINT, wt.WPARAM, wt.LPARAM], msg, wp, lp))

    def HandleMenuMsg2(self, msg, wp, lp):  # noqa: N802
        result = ct.c_ssize_t()
        _check(_call(self.pointer, 7, [wt.UINT, wt.WPARAM, wt.LPARAM, ct.POINTER(ct.c_ssize_t)],
                     msg, wp, lp, ct.byref(result)))
        return result.value


def create_context(paths):
    shell = ct.WinDLL('shell32')
    ole = ct.WinDLL('ole32')
    shell.SHParseDisplayName.argtypes = [wt.LPCWSTR, ct.c_void_p, ct.POINTER(ct.c_void_p),
                                        wt.DWORD, ct.POINTER(wt.DWORD)]
    shell.SHParseDisplayName.restype = ct.c_long
    shell.SHCreateShellItemArrayFromIDLists.argtypes = [wt.UINT, ct.POINTER(ct.c_void_p), ct.POINTER(ct.c_void_p)]
    shell.SHCreateShellItemArrayFromIDLists.restype = ct.c_long
    ole.CoTaskMemFree.argtypes = [ct.c_void_p]
    ole.CoTaskMemFree.restype = None
    pidls = []
    items = ct.c_void_p()
    try:
        for path in paths:
            pidl = ct.c_void_p()
            _check(shell.SHParseDisplayName(path, None, ct.byref(pidl), 0, None))
            pidls.append(pidl)
        array = (ct.c_void_p * len(pidls))(*(p.value for p in pidls))
        _check(shell.SHCreateShellItemArrayFromIDLists(len(pidls), array, ct.byref(items)))
        bhid = GUID.parse('3981E225-F559-11D3-8E3A-00C04F6837D5')  # BHID_SFUIObject
        iid = GUID.parse('000214E4-0000-0000-C000-000000000046')  # IContextMenu
        context = ct.c_void_p()
        _check(_call(items, 3, [ct.c_void_p, ct.POINTER(GUID), ct.POINTER(GUID), ct.POINTER(ct.c_void_p)],
                     None, ct.byref(bhid), ct.byref(iid), ct.byref(context)))
        return ShellContext(context)
    finally:
        if items:
            _call(items, 2, [], restype=wt.ULONG)
        for pidl in pidls:
            ole.CoTaskMemFree(pidl)
