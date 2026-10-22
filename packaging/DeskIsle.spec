# 桌屿 DeskIsle 2.0 - PyInstaller spec (Windows, one-folder build).
#
#   python -m PyInstaller packaging/DeskIsle.spec --noconfirm --clean --distpath ... --workpath ...
#
# Produces dist/DeskIsle/ with three programs sharing one _internal folder:
#   DeskIsle.exe           the app (windowed; also --watchdog / --self-test)
#   deskisle-cli.exe       console CLI + MCP stdio server for AI assistants (no Qt)
#   DeskIsleShellMenu.exe  helper that shows the native Explorer context menu
from pathlib import Path
import os
import sys

from PyInstaller.utils.hooks import collect_submodules

# Do not bundle unrelated ICU/OpenSSL DLLs injected by development tools.
# Qt uses Windows' ICU ABI, which is incompatible with e.g. Poppler's ICU DLL.
os.environ['PATH'] = os.pathsep.join([str(Path(sys.executable).parent),
                                    str(Path(os.environ['WINDIR']) / 'System32'),
                                    os.environ['WINDIR']])

root = Path(SPECPATH).parent

# Data files keep their source layout below _internal/, because the code finds
# them relative to its own modules (deskisle/qml, deskisle/assets, ...) and the
# settings page opens README/CHANGELOG/notices from the bundle root.
datas = [(str(root / 'deskisle/qml'), 'deskisle/qml'),
         (str(root / 'deskisle/assets'), 'deskisle/assets'),
         (str(root / 'deskisle/agent/GUIDE.md'), 'deskisle/agent'),
         (str(root / 'docs'), 'docs')]
for name in ('README.md', 'CHANGELOG.md', 'THIRD-PARTY-NOTICES.md', 'LICENSE', 'VERSION'):
    if (root / name).is_file():
        datas.append((str(root / name), '.'))

# Services are created by name (importlib), so PyInstaller cannot see them:
# name them and take the whole package.  WinRT namespaces are partly imported
# from C code.  (collect_submodules imports in a child process that only sees
# sys.path, so make sure the source tree is on it whatever the working folder.)
sys.path.insert(0, str(root))
SERVICES = ['deskisle.services.' + name for name in ('base', 'clock', 'weather', 'nowplaying', 'everything', 'todo')]
hiddenimports = sorted(set(collect_submodules('deskisle') + SERVICES)) + [
    'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtNetwork', 'PySide6.QtSvg',
    # Multimedia: video island backgrounds (QML "import QtMultimedia"); listing
    # the Python module makes PyInstaller collect the FFmpeg media backend.
    'PySide6.QtMultimedia',
    'lunar_python',
    'win32com.shell.shell', 'pythoncom',
    'winrt.system', 'winrt.runtime',
    'winrt.windows.foundation', 'winrt.windows.foundation.collections',
    'winrt.windows.media', 'winrt.windows.media.control', 'winrt.windows.storage.streams',
    'winrt.windows.devices.geolocation',
]

# Web islands use the system's Edge WebView2 runtime through ctypes; only the
# small WebView2Loader.dll travels along in deskisle/assets/webview2.  No
# Chromium copy (Qt WebEngine, ~200 MB) and no other unused Qt add-on.
excludes = ['tkinter', 'matplotlib', 'numpy', 'pandas', 'scipy', 'PIL',
            'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineQuick',
            'PySide6.QtWebChannel', 'PySide6.QtWebSockets', 'PySide6.QtWebView',
            'PySide6.QtQuickWidgets', 'PySide6.QtQuick3D', 'PySide6.QtCharts', 'PySide6.QtGraphs',
            'PySide6.QtDataVisualization', 'PySide6.QtLocation', 'PySide6.QtPositioning',
            'PySide6.QtSensors', 'PySide6.QtScxml', 'PySide6.QtRemoteObjects',
            'PySide6.QtTextToSpeech', 'PySide6.QtBluetooth', 'PySide6.QtNfc',
            'PySide6.QtSerialPort', 'PySide6.QtSerialBus', 'PySide6.QtSpatialAudio',
            'PySide6.Qt3DCore', 'PySide6.Qt3DRender', 'PySide6.QtPdf', 'PySide6.QtPdfWidgets',
            'PySide6.QtDesigner', 'PySide6.QtHelp', 'PySide6.QtSql', 'PySide6.QtTest',
            'PySide6.QtUiTools']

app = Analysis([str(root / 'main.py')], pathex=[str(root)], binaries=[], datas=datas,
               hiddenimports=hiddenimports, excludes=excludes,
               hookspath=[], runtime_hooks=[], noarchive=False)

# PyInstaller's QtQml hook copies *every* QML module of the Qt installation.
# DeskIsle imports only QtQuick (+ Effects, Shapes, Window) and QtMultimedia, so
# drop the big unused ones together with the Qt libraries only they pull in.
UNUSED_QML = ('Qt3D', 'QtQuick3D', 'QtCharts', 'QtDataVisualization', 'QtGraphs', 'QtLocation',
              'QtPositioning', 'QtSensors', 'QtScxml', 'QtRemoteObjects', 'QtTextToSpeech',
              'QtWebEngine', 'QtWebView', 'QtWebChannel', 'QtWebSockets', 'QtTest', 'Qt5Compat',
              'QtQml/StateMachine', 'QtQuick/Scene3D', 'QtQuick/Scene2D', 'QtQuick/VirtualKeyboard', 'QtQuick/Pdf',
              'QtQuick/Timeline/BlendTrees')
UNUSED_LIBS = ('qt63d', 'qt6quick3d', 'qt6charts', 'qt6datavisualization', 'qt6graphs',
               'qt6location', 'qt6positioning', 'qt6sensors', 'qt6scxml', 'qt6statemachine',
               'qt6remoteobjects', 'qt6texttospeech', 'qt6virtualkeyboard', 'qt6webengine',
               'qt6webview', 'qt6webchannel', 'qt6websockets', 'qt6pdf', 'qt6quicktest', 'qt6test',
               'qt6core5compat', 'qtwebengineprocess')


def _unused(dest):
    path = dest.replace('\\', '/')
    parts = path.split('/')
    if 'qml' in parts:
        rest = '/'.join(parts[parts.index('qml') + 1:])
        if any(rest == m or rest.startswith(m + '/') for m in UNUSED_QML):
            return True
    name = parts[-1].lower()
    return name.removeprefix('lib').startswith(UNUSED_LIBS)     # Qt6Foo.dll (libQt6Foo.so elsewhere)


app.binaries = [entry for entry in app.binaries if not _unused(entry[0])]
app.datas = [entry for entry in app.datas if not _unused(entry[0])]

cli = Analysis([str(root / 'tools/cli_entry.py')], pathex=[str(root)], binaries=[], datas=[],
               hiddenimports=['deskisle.agent.mcp'],
               excludes=['PySide6', 'shiboken6', 'tkinter', 'numpy', 'matplotlib', 'PIL',
                         'win32com', 'pythoncom', 'winrt', 'lunar_python'],
               hookspath=[], runtime_hooks=[], noarchive=False)
helper = Analysis([str(root / 'tools/shell_menu_entry.py')], pathex=[str(root)],
                  binaries=[], datas=[], hiddenimports=['win32com.shell.shell', 'pythoncom'],
                  excludes=['PySide6', 'shiboken6', 'tkinter', 'numpy', 'matplotlib', 'PIL'],
                  hookspath=[], runtime_hooks=[], noarchive=False)

icon = str(root / 'packaging/DeskIsle.ico')
main_exe = EXE(PYZ(app.pure), app.scripts, [], exclude_binaries=True,
               name='DeskIsle', console=False, debug=False, strip=False, upx=False, icon=icon)
cli_exe = EXE(PYZ(cli.pure), cli.scripts, [], exclude_binaries=True,
              name='deskisle-cli', console=True, debug=False, strip=False, upx=False, icon=icon)
menu_exe = EXE(PYZ(helper.pure), helper.scripts, [], exclude_binaries=True,
               name='DeskIsleShellMenu', console=True, debug=False, strip=False, upx=False, icon=icon)
collection = COLLECT(main_exe, cli_exe, menu_exe,
                     app.binaries, app.datas, cli.binaries, cli.datas, helper.binaries, helper.datas,
                     strip=False, upx=False, name='DeskIsle')
