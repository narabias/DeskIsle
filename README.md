# 桌屿 DeskIsle

把凌乱桌面整理成你的工作岛。DeskIsle 是一个本地优先的 Windows 桌面整理器，使用 Python + PySide6 编写。

> 本项目是独立原创实现，不包含 Stardock Fences 的代码、商标或素材。普通“收纳岛”只保存文件引用，不移动、重命名或删除原文件。

## 主要功能

- 可移动、缩放、锁定、收拢的桌面收纳岛
- 文件/文件夹/快捷方式拖放与图标网格
- 文件视窗：将任意文件夹实时映射到桌面
- 一个收纳岛内使用多个标签页
- 按扩展名、名称和项目类型自动归流
- 场景页、快速清屏、聚焦层、搜索
- 布局快照、导入导出和自动持久化
- 系统托盘、全局快捷键、多显示器边界修正

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

## 数据位置

默认保存在 `%LOCALAPPDATA%\DeskIsle`。可使用 `DESKISLE_DATA_DIR` 指定独立测试目录。

## 隐私

DeskIsle **完全离线运行**，不包含任何网络请求、遥测、使用统计或自动更新。
所有布局数据只保存在本机 `%LOCALAPPDATA%\DeskIsle`，不会上传到任何地方。

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
  native_win.py         Win32 桌面挂接、热键、开机启动（平台隔离）
  shell_menu.py         Explorer 原生右键菜单（独立进程）
  shell_context.py      IContextMenu2/3 的 ctypes 绑定
  selftest.py           打包后 EXE 自检
  theme.py              配色与应用样式表
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

产物：`dist/installer/DeskIsle-Setup-<版本>-x64.exe`

## 许可

本项目代码以 **MIT 许可**发布，见 [LICENSE](LICENSE)。

打包产物包含 PySide6/Qt（LGPLv3）等第三方组件，详见
[THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)。

