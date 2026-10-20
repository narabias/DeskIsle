# Build with: python -m PyInstaller packaging/DeskIsle.spec --distpath ... --workpath ...
from pathlib import Path
import os
import sys

# Do not bundle unrelated ICU/OpenSSL DLLs injected by development tools.
# Qt uses Windows' ICU ABI, which is incompatible with e.g. Poppler's ICU DLL.
os.environ['PATH'] = os.pathsep.join([str(Path(sys.executable).parent),
                                    str(Path(os.environ['WINDIR']) / 'System32'),
                                    os.environ['WINDIR']])

root = Path(SPECPATH).parent
assets = [(str(root / 'deskisle/assets'), 'deskisle/assets'),
          (str(root / 'docs'), 'docs')]
app = Analysis([str(root / 'main.py')], pathex=[str(root)], binaries=[], datas=assets,
               hiddenimports=['PySide6.QtSvg', 'PySide6.QtTest'],
               excludes=['tkinter', 'matplotlib', 'numpy', 'pandas', 'scipy'],
               hookspath=[], runtime_hooks=[], noarchive=False)
helper = Analysis([str(root / 'tools/shell_menu_entry.py')], pathex=[str(root)],
                  binaries=[], datas=[], hiddenimports=['win32com.shell.shell', 'pythoncom'],
                  excludes=['PySide6', 'tkinter', 'numpy', 'matplotlib'],
                  hookspath=[], runtime_hooks=[], noarchive=False)
main_exe = EXE(PYZ(app.pure), app.scripts, [], exclude_binaries=True,
               name='DeskIsle', console=False, debug=False, strip=False, upx=False,
               icon=str(root / 'packaging/DeskIsle.ico'))
menu_exe = EXE(PYZ(helper.pure), helper.scripts, [], exclude_binaries=True,
               name='DeskIsleShellMenu', console=True, debug=False, strip=False, upx=False,
               icon=str(root / 'packaging/DeskIsle.ico'))
collection = COLLECT(main_exe, menu_exe, app.binaries, app.datas, helper.binaries, helper.datas,
                     strip=False, upx=False, name='DeskIsle')
