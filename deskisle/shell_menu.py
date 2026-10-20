"""Explorer's IContextMenu in a separate process (shell extensions may block)."""
from __future__ import annotations

import json
import os
import sys


def create_context_menu(paths, hwnd):
    from .shell_context import create_context

    return create_context([os.path.abspath(p) for p in paths])


def track_menu(paths, allow_remove=False):
    import pythoncom
    import win32api
    import win32con
    import win32gui
    from win32com.shell import shell, shellcon

    pythoncom.CoInitialize()
    context = context2 = context3 = None
    hwnd = menu = None
    class_name = 'DeskIsleShellMenu'
    groups = {}
    contexts = []
    menu_contexts = {}
    for path in paths:
        folder = os.path.normcase(os.path.dirname(os.path.abspath(path)))
        groups.setdefault(folder, []).append(path)

    def wndproc(owner, msg, wp, lp):
        nonlocal context2, context3
        if msg == win32con.WM_INITMENUPOPUP and wp in menu_contexts:
            context2, context3 = menu_contexts[wp]
        if msg in (win32con.WM_INITMENUPOPUP, win32con.WM_DRAWITEM,
                   win32con.WM_MEASUREITEM, win32con.WM_MENUCHAR):
            try:
                if context3 is not None:
                    return context3.HandleMenuMsg2(msg, wp, lp)
                if context2 is not None and msg != win32con.WM_MENUCHAR:
                    context2.HandleMenuMsg(msg, wp, lp)
                    return 0
            except OSError:
                pass
        return win32gui.DefWindowProc(owner, msg, wp, lp)

    try:
        wc = win32gui.WNDCLASS()
        wc.hInstance = win32api.GetModuleHandle(None)
        wc.lpszClassName = class_name
        wc.lpfnWndProc = wndproc
        win32gui.RegisterClass(wc)
        # Native cursor coordinates avoid Qt logical/physical DPI conversion.
        x, y = win32gui.GetCursorPos()
        hwnd = win32gui.CreateWindowEx(win32con.WS_EX_TOOLWINDOW, class_name, '',
                                      win32con.WS_POPUP, x, y, 1, 1,
                                      0, 0, wc.hInstance, None)
        menu = win32gui.CreatePopupMenu()
        flags = shellcon.CMF_NORMAL
        if win32api.GetKeyState(win32con.VK_SHIFT) < 0:
            flags |= shellcon.CMF_EXTENDEDVERBS
        next_id = 1
        for folder, selection in groups.items():
            context = create_context_menu(selection, hwnd)
            context2 = context3 = None
            for iid, version in ((shell.IID_IContextMenu3, 3), (shell.IID_IContextMenu2, 2)):
                try:
                    interface = context.QueryInterface(iid)
                    if version == 3:
                        context3 = interface
                    else:
                        context2 = interface
                except OSError:
                    pass
            target_menu = menu
            if len(groups) > 1:
                target_menu = win32gui.CreatePopupMenu()
                win32gui.AppendMenu(menu, win32con.MF_POPUP, target_menu, folder)
            count = context.QueryContextMenu(target_menu, 0, next_id, 0x7FFF, flags)
            menu_contexts[target_menu] = (context2, context3)
            contexts.append((next_id, next_id + count, context))
            next_id += count
        if allow_remove:
            win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, '')
            win32gui.AppendMenu(menu, win32con.MF_STRING, 0x8000, '从收纳岛移出（不删除文件）')
        win32gui.ShowWindow(hwnd, win32con.SW_SHOWNOACTIVATE)
        win32gui.SetForegroundWindow(hwnd)
        command = win32gui.TrackPopupMenu(menu, win32con.TPM_RETURNCMD | win32con.TPM_RIGHTBUTTON,
                                         x, y, 0, hwnd, None)
        win32gui.PostMessage(hwnd, win32con.WM_NULL, 0, 0)
        if command == 0x8000:
            return {'remove': True}
        if command:
            # Keep this helper alive until the handler has completed its work.
            for first, end, handler in contexts:
                if first <= command < end:
                    handler.InvokeCommand((0x100, hwnd, command - first,  # CMIC_MASK_NOASYNC
                                           None, None, win32con.SW_SHOWNORMAL, 0, 0))
                    break
        return {'remove': False}
    finally:
        if menu:
            win32gui.DestroyMenu(menu)
        for pair in menu_contexts.values():
            for interface in pair:
                if interface is not None:
                    interface.close()
        for _first, _end, interface in contexts:
            interface.close()
        # These can exist even if QueryContextMenu failed before registration.
        for interface in (context3, context2, context):
            if interface is not None:
                interface.close()
        context3 = context2 = context = None
        menu_contexts.clear()
        contexts.clear()
        if hwnd:
            win32gui.DestroyWindow(hwnd)
        win32gui.UnregisterClass(class_name, win32api.GetModuleHandle(None))
        pythoncom.CoUninitialize()


def probe_menu(paths):
    """Build a real menu and check its extensions without invoking a command."""
    import pythoncom
    import win32gui
    from win32com.shell import shell
    pythoncom.CoInitialize()
    context = extension = None
    menu = None
    try:
        context = create_context_menu(paths, 0)
        menu = win32gui.CreatePopupMenu()
        count = context.QueryContextMenu(menu, 0, 1, 0x7FFF, 0)
        extension = context.QueryInterface(shell.IID_IContextMenu3)
        verbs = []
        for index in range(count):
            try:
                verbs.append(context.GetCommandString(index).decode('ascii', errors='replace'))
            except OSError:
                pass
        return {'verbs': verbs, 'extended_menu': True}
    finally:
        if menu:
            win32gui.DestroyMenu(menu)
        if extension:
            extension.close()
        if context:
            context.close()
        pythoncom.CoUninitialize()


def main():
    try:
        request = json.loads(sys.stdin.buffer.read().decode('utf-8'))
        result = probe_menu(request['paths']) if request.get('probe') else track_menu(request['paths'], request.get('allow_remove', False))
    except Exception as exc:
        result = {'error': str(exc)}
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))
    sys.stdout.buffer.flush()


if __name__ == '__main__':
    main()
