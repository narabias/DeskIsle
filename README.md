# 桌屿 DeskIsle

把凌乱桌面整理成你的工作岛。DeskIsle 是一个本地优先的 Windows 桌面整理器，使用 Python + PySide6 编写。

> 普通“收纳岛”只保存文件引用，不移动、重命名或删除原文件。

## 主要功能

- 可移动、缩放、锁定、收拢的桌面收纳岛
- 文件/文件夹/快捷方式拖放与图标网格
- 文件视窗：将任意文件夹实时映射到桌面
- 一个收纳岛内使用多个标签页
- 按扩展名、名称和项目类型自动归流
- 场景页、快速清屏、聚焦层、搜索
- 布局快照、导入导出和自动持久化
- 系统托盘、全局快捷键、多显示器边界修正

### 1.2 新增

- 类 iOS 的界面与动效：收拢/展开、图标缩放、菜单与对话框都使用统一的缓动曲线，可在设置中“减弱动态效果”
- 收纳岛材质：**简易透明 / 毛玻璃 / 液体玻璃**，可设全局默认，也可每个岛单独设置
- 背景图片/视频：显示在玻璃之上、图标之下，视频自动循环，支持不透明度与内缘羽化；收拢后仍显示背景
- 自定义收纳岛名称与色调；收拢后的胶囊标题与数量徽标自动适配
- 全局字体：从系统字体中选择，或导入 `.ttf/.otf` 字体文件，并可调整字号
- HTML 动画岛：持续播放本地 HTML 文件中的动画（默认离线）
- 固定网页岛：把网页固定在桌面，保留登录状态，支持导航栏、自动刷新、页面缩放
- 任意收纳岛可“窗口置顶”
- 被窗口遮挡时自动暂停视频与动画，可限制背景视频帧率
- 应用内更新：从 GitHub `narabias/DeskIsle` 检查新版本，下载后校验 SHA-256 再安装；不会修改你的布局与设置

## 运行

```powershell
python main.py
```

本机没有 PySide6 时：

```powershell
python -m pip install -r requirements.txt
```

开发/演示窗口（不挂接 Windows 桌面）：

```powershell
python main.py --demo
```

## 快捷键

- `Ctrl+Alt+Space`：打开/关闭聚焦层
- `Ctrl+Alt+H`：显示/隐藏全部收纳岛
- `Ctrl+Alt+Left / Right`：切换场景页
- `Esc`：退出聚焦层

## 测试

```powershell
python -m unittest discover -s tests -v
```

单元测试不会启动 Chromium：测试会自动设置 `DESKISLE_DISABLE_WEBENGINE=1`，HTML/网页岛显示占位内容。

## 数据位置

默认保存在 `%LOCALAPPDATA%\DeskIsle`。可使用 `DESKISLE_DATA_DIR` 指定独立测试目录。

| 位置 | 内容 |
| --- | --- |
| `state.json`、`state.json.bak`、`snapshots/` | 布局、设置与快照 |
| `media/` | 导入的背景图片/视频副本（200 MB 以内会复制，更大的文件直接引用原路径）；不再被任何布局或快照引用的副本会在启动时清理 |
| `fonts/` | 导入的字体文件副本 |
| `web/` | 固定网页岛的登录状态（Cookie）与缓存 |
| `update.json` | 更新检查记录（上次检查时间、已跳过的版本） |

更新程序只读写 `update.json`，安装新版本时不会改动布局与设置；卸载时同样会保留这个目录。

## 隐私

DeskIsle 不包含任何遥测或使用统计。所有布局数据只保存在本机 `%LOCALAPPDATA%\DeskIsle`，不会上传到任何地方。

只有下列情况会联网：

- **检查更新**：大约每 20 小时最多一次，请求 `api.github.com` 读取 `narabias/DeskIsle` 的最新发布信息；
  可在“设置 → 更新”中关闭自动检查。只有你点击“下载并安装”后才会从 GitHub 下载安装包。
- **固定网页岛**：访问你填写的网址，和普通浏览器一样。
- **HTML 动画岛**：默认禁止联网，只能读取本地文件；需要时可在该岛菜单中勾选“允许页面联网”。

普通收纳岛只记录文件路径引用，**从不移动、重命名或删除**被引用的文件。
真实的文件复制仅发生在文件视窗，且执行前会明确确认。

## 项目结构

```
main.py                 程序入口、命令行参数、全局异常处理
deskisle/
  models.py             数据模型与序列化
  storage.py            原子写入、备份、快照、导入导出
  rules.py              归流规则引擎
  board.py              桌面主窗口、工具条、散放区、托盘
  island.py             收纳岛、标签页、文件视窗
  items.py              图标网格与拖放
  dialogs.py            各类设置对话框
  widgets.py            玻璃菜单、开关、分段控件等通用控件
  motion.py             统一的动画时长与缓动曲线
  backdrop.py           壁纸取样与简易透明/毛玻璃/液体玻璃材质绘制
  media.py              背景图片/视频（循环播放、羽化、遮挡时暂停）
  html_view.py          HTML 动画岛与固定网页岛（Qt WebEngine）
  updater.py            GitHub 更新检查、下载与 SHA-256 校验
  native_win.py         Win32 桌面挂接、热键、开机启动（平台隔离）
  shell_menu.py         Explorer 原生右键菜单（独立进程）
  shell_context.py      IContextMenu2/3 的 ctypes 绑定
  selftest.py           打包后 EXE 自检
  theme.py              配色、字体与应用样式表
  assets/               图标、界面素材与演示用 HTML 动画
packaging/              PyInstaller spec 与 Inno Setup 脚本
tools/                  构建、渲染、诊断脚本
tests/                  单元测试与 UI 冒烟测试
docs/                   使用说明、打包说明、功能调研
```

## 构建安装包

```powershell
# 双击 build-release.bat，或：
powershell -File tools/build_release.ps1 -NoOpen
```

脚本会自动安装依赖、运行测试、用 PyInstaller 打包、编译 Inno Setup 安装程序，
并在最后用 `--self-test` 验证真实 EXE。首次构建需要联网下载 Inno Setup。

产物：`dist/installer/DeskIsle-Setup-<版本>-x64.exe` 及同名 `.sha256` 校验文件。

发布到 GitHub Release 后，已安装的桌屿才能通过应用内更新找到新版本，步骤见
[docs/打包说明.md](docs/打包说明.md)。

## 许可

本项目代码以 **MIT 许可**发布，见 [LICENSE](LICENSE)。

打包产物包含 PySide6/Qt（LGPLv3）等第三方组件，详见
[THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)。

