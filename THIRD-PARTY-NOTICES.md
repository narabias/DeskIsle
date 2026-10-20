# 第三方组件与许可声明

桌屿 DeskIsle 自身代码以 MIT 许可发布（见仓库根目录 `LICENSE`）。
本项目**打包发布**的安装包中还包含下列第三方组件，它们各自保留原有许可。

## 运行时依赖

### PySide6 / Qt 6 — LGPLv3

- 项目主页：https://www.qt.io/qt-for-python
- 许可：GNU Lesser General Public License v3
- 许可全文：https://www.gnu.org/licenses/lgpl-3.0.html

DeskIsle 通过 PyInstaller 的 one-folder 模式打包，Qt 库以**动态链接**方式加载，
用户可自行替换安装目录 `_internal/PySide6/` 下的 Qt DLL。

依据 LGPLv3，你拥有以下权利：

1. 以任何目的运行本程序；
2. 研究并修改本程序（DeskIsle 源码本身已完整公开）；
3. 重新分发副本；
4. **替换或重新链接所使用的 Qt 库**——用你自己编译或获取的 Qt 6 / PySide6
   二进制文件覆盖安装目录中的同名文件即可。

如需 Qt/PySide6 源代码，请访问上述项目主页获取。

#### Qt WebEngine（含 Chromium）

- 用途：HTML 动画岛与固定网页岛
- Qt WebEngine 模块随 PySide6 以 LGPLv3 提供；其中集成的 Chromium 及其依赖（Blink、V8、Skia、ICU 等）
  分别以 BSD、MIT、LGPL 等各自的许可发布。
- 完整许可清单：https://doc.qt.io/qt-6/qtwebengine-licensing.html
- 安装目录中的 `QtWebEngineProcess.exe`、`Qt6WebEngineCore.dll` 及 `resources/` 等文件同样可按上文方式替换。

#### Qt Multimedia 与 FFmpeg

- 用途：背景视频播放（图片背景不依赖它）
- Qt Multimedia 以 LGPLv3 提供；PySide6 附带的 FFmpeg 动态库（`avcodec-*.dll`、`avformat-*.dll`、
  `avutil-*.dll`、`swscale-*.dll`、`swresample-*.dll`）以 LGPLv2.1 或更高版本发布，可自行替换。
- FFmpeg 源代码与许可：https://ffmpeg.org/legal.html

### pywin32 — PSF 风格许可

- 项目主页：https://github.com/mhammond/pywin32
- 许可：Python Software Foundation License
- 用途：Windows Shell 右键菜单集成

### Pillow — MIT-CMU

- 项目主页：https://python-pillow.org
- 许可：MIT-CMU License
- 用途：**仅构建期使用**，用于从 PNG 生成多尺寸 `.ico`，不随安装包分发。

### PyInstaller — GPLv2 加例外条款

- 项目主页：https://pyinstaller.org
- 许可：GPL v2 with a special exception allowing bootloader bundling
- 用途：**仅构建期使用**，不随安装包分发。

## 素材

### Tabler Icons — MIT

- 项目主页：https://tabler-icons.io
- 版权：Copyright (c) 2020-2026 Paweł Kuna
- 许可全文见 `deskisle/assets/icons/LICENSE-TABLER.txt`
- 用途：界面图标（`deskisle/assets/icons/*.svg`）

### 界面素材与演示动画

`deskisle/assets/ui/*.svg`（勾选、箭头等小图标）与 `deskisle/assets/demo/aurora.html`（演示用 HTML 动画）
均为本项目原创，随项目以 MIT 许可发布。

### 应用图标

`packaging/DeskIsle.ico` 与 `packaging/DeskIsle.png` 由仓库内
`tools/make_app_icon.py` 用代码绘制生成，不包含第三方素材。
