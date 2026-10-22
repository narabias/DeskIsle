# 第三方组件与许可声明

桌屿 DeskIsle 自身的代码以 MIT 许可发布（见根目录 `LICENSE`）。
安装包中还包含下列第三方组件，它们各自保留原有的版权与许可；另有几项在线服务与可选软件，
桌屿只是调用它们，并不分发。

- [随安装包分发的运行时组件](#随安装包分发的运行时组件)
- [只在构建时使用的工具](#只在构建时使用的工具)
- [在线服务与可选软件（不随安装包分发）](#在线服务与可选软件不随安装包分发)
- [图标、素材与设计参考](#图标素材与设计参考)
- [应用图标](#应用图标)

## 随安装包分发的运行时组件

### Qt 6 / PySide6 — LGPLv3

- 项目主页：https://www.qt.io/qt-for-python
- 许可：GNU Lesser General Public License v3（PySide6 与 Shiboken6 同样以 LGPLv3 提供）
- 许可全文：https://www.gnu.org/licenses/lgpl-3.0.html
- 用途：全部界面与图形渲染（Qt Quick、Qt Quick Effects、Qt Quick Shapes、Qt Network、Qt SVG、Qt Multimedia）。

桌屿使用 PyInstaller 的 one-folder 模式打包，Qt 库以**动态链接**方式加载，位于安装目录
`_internal/PySide6/`。依据 LGPLv3，你可以：

1. 以任何目的运行本程序；
2. 研究并修改本程序（桌屿的源代码完整公开）；
3. 重新分发副本；
4. **替换或重新链接所用的 Qt 库**——用你自己编译或获取的同版本 Qt 6 / PySide6 二进制文件覆盖安装目录中的同名文件即可。

Qt 与 PySide6 的源代码可从上述项目主页获取。

#### Qt Multimedia 与 FFmpeg

- 用途：收纳岛的视频背景（图片与 GIF 背景不依赖它）。
- Qt Multimedia 以 LGPLv3 提供；PySide6 附带的 FFmpeg 动态库（`avcodec-*.dll`、`avformat-*.dll`、`avutil-*.dll`、
  `swscale-*.dll`、`swresample-*.dll`）以 LGPLv2.1 或更高版本发布，同样可以自行替换。
- FFmpeg 源代码与许可：https://ffmpeg.org/legal.html

### Python 运行时 — PSF License

- 项目主页：https://www.python.org
- 许可：Python Software Foundation License Version 2（https://docs.python.org/3/license.html）
- 安装包内含 Python 3 解释器与标准库，以及 Python 发行版附带的库（如 libffi、zlib、bzip2、xz、expat、OpenSSL），
  它们各自的许可见上述页面。

### lunar-python — MIT

- 项目主页：https://github.com/6tail/lunar-python
- 版权：Copyright (c) 2020 6tail
- 用途：时钟小组件的农历日期、节气与传统节日。

### pywinrt（`winrt-*` 软件包）— MIT

- 项目主页：https://github.com/pywinrt/pywinrt
- 用途：读取 Windows 系统媒体会话（“正在播放”）与 Windows 定位服务（天气自动定位）。
- 安装包内含 `winrt-runtime` 以及 `Windows.Foundation`、`Windows.Foundation.Collections`、`Windows.Media`、
  `Windows.Media.Control`、`Windows.Storage.Streams`、`Windows.Devices.Geolocation` 的 Python 投影。

### pywin32 — PSF 风格许可

- 项目主页：https://github.com/mhammond/pywin32
- 许可：Python Software Foundation License
- 用途：Windows 外壳集成（原生右键菜单、快捷方式、COM）。

### Microsoft Edge WebView2 — 运行时由系统提供，加载器为 BSD 风格许可

- 用途：网页岛与本地 HTML 动画。
- **WebView2 运行时**是 Windows 的系统组件（Windows 11 及绝大多数 Windows 10 已预装），由 Microsoft 通过 Windows 更新维护，
  **不随桌屿分发**；缺少时可从 https://developer.microsoft.com/microsoft-edge/webview2/ 免费下载“常青版引导程序”安装。
- 安装包只附带 WebView2 SDK 中的 `WebView2Loader.dll`（`_internal/deskisle/assets/webview2/<架构>/`），
  版权 © Microsoft Corporation，按 BSD 风格许可再分发；许可全文与 Microsoft 的第三方声明见同目录的
  `LICENSE.txt`、`NOTICE.txt`。
- 桌屿通过 ctypes 直接调用 WebView2 的 COM 接口，没有使用 pythonnet、pywebview 等额外库。

### PyInstaller 引导程序 — GPLv2（带分发例外）

- 项目主页：https://pyinstaller.org
- `DeskIsle.exe`、`deskisle-cli.exe`、`DeskIsleShellMenu.exe` 中包含 PyInstaller 的引导程序（bootloader）。
  PyInstaller 以 GPL v2 发布，并附有例外条款：用它生成的程序可以按任何许可（包括本项目的 MIT）分发。

### Inno Setup 安装程序

- 项目主页：https://jrsoftware.org/isinfo.php
- 安装程序与卸载程序由 Inno Setup 6 生成；Inno Setup License 允许免费分发生成的安装包（https://jrsoftware.org/files/is/license.txt）。
- 简体中文界面文字 `packaging/ChineseSimplified.isl` 来自 Inno Setup 的用户翻译（维护者 Zhenghan Yang），
  见 https://jrsoftware.org/files/istrans/

## 只在构建时使用的工具

以下工具只用于生成安装包，**不包含在安装后的程序中**：

- **PyInstaller**（GPLv2 带例外，见上文）——把 Python 程序打包成 EXE。
- **Pillow**（MIT-CMU License，https://python-pillow.org）——从图片生成多尺寸 `.ico` 应用图标（开发工具 `tools/make_demo_wallpaper.py` 生成演示壁纸时也用到它）。
- **Inno Setup 编译器**（见上文）——编译安装程序；构建脚本会校验其发布者签名后以便携模式放在 `.tools/inno6`。

## 在线服务与可选软件（不随安装包分发）

### MSN 天气（Microsoft）

- 天气小组件默认从 MSN 天气获取数据，与 Windows 任务栏天气使用同一来源；没有位置时由该服务按网络位置估算城市。
- 这是 Microsoft 的在线服务，并非为第三方提供的正式 API，可能随时变化或停止；数据的版权归 Microsoft 及其数据提供方，
  使用受 Microsoft 服务协议约束（https://www.microsoft.com/servicesagreement）。
- 只有桌面上放了天气小组件时才会请求；发送的坐标只保留两位小数（约 1 公里精度）。

### Open-Meteo — 数据以 CC BY 4.0 提供

- 项目主页：https://open-meteo.com
- MSN 天气不可用时改用 Open-Meteo 的天气预报接口；在设置中搜索城市使用 Open-Meteo Geocoding API（地名数据基于 GeoNames，CC BY 4.0）。
- 天气数据许可：Creative Commons Attribution 4.0（https://creativecommons.org/licenses/by/4.0/）。
  小组件的刷新按钮提示中标明“数据来自 MSN 天气 / Open-Meteo”。
- Open-Meteo 的免费接口仅限**非商业用途**；若要把桌屿用于商业产品，请先阅读其条款（https://open-meteo.com/en/terms）。

### Everything（voidtools）

- 项目主页：https://www.voidtools.com
- 可选：如果你已经安装并运行了 Everything，搜索面板会通过它公开的 IPC 消息（`WM_COPYDATA`）查询全盘文件。
- 桌屿**不分发** Everything 或其 SDK 的任何文件；Everything 的使用受 voidtools 的许可约束。

### GitHub

- 应用内更新从 GitHub 仓库 `narabias/DeskIsle` 的 Releases 读取版本信息并下载安装包，使用受 GitHub 服务条款约束。
  可在“设置 → 关于 → 自动检查更新”中关闭自动检查。

## 图标、素材与设计参考

### Tabler Icons — MIT

- 项目主页：https://tabler.io/icons
- 版权：Copyright (c) 2020-2026 Paweł Kuna
- 用途：界面中的全部描边图标。图标路径数据保存在 `deskisle/qml/glyphs.js`，许可全文见 `deskisle/qml/LICENSE-TABLER.txt`
  （安装后位于 `_internal/deskisle/qml/`）。

### 液态玻璃着色器的参考

- `deskisle/qml/shaders/glass.frag` 中的边缘折射模型（越靠近边缘，取样位置越向内偏移，并带轻微色散）参考了
  OverShifted/LiquidGlass（https://github.com/OverShifted/LiquidGlass，MIT，Copyright (c) 2026 Sepehr Kalanaki）的思路；
  着色器代码由本项目独立编写。

### 演示素材

- `deskisle/assets/demo/wallpaper.jpg`（演示壁纸，由 `tools/make_demo_wallpaper.py` 程序生成）与
  `deskisle/assets/demo/aurora.html`（演示用 HTML 动画）均为本项目原创，随项目以 MIT 许可发布。

## 应用图标

`packaging/DeskIsle.ico`、`packaging/DeskIsle.png` 与 `deskisle/assets/ui/app-icon.png`
由 `tools/make_app_icon.py` 从 `packaging/icon-source.jpg`（项目维护者提供的插画）裁切生成。
**该插画的著作权属于原作者，不随本项目的 MIT 许可授权。** 公开发布或商用安装包前，请确认已获得原作者许可；
否则请换成自己拥有版权的图片，再运行 `python tools/make_app_icon.py <图片> --box X0 Y0 X1 Y1` 重新生成图标。
