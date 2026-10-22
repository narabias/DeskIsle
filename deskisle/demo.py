"""Demo / screenshot mode (``python main.py --demo``).

Builds a sample desktop in a temporary folder: a few files and folders, and
a layout with file islands, a file view, a web island and every built-in
widget.  Nothing outside the demo folder is read or changed.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from .models import AppState, IslandState, ItemRef, PageState, Preferences, TabState

ASSETS = Path(__file__).resolve().parent / "assets"
SAMPLE_FILES = {
    "工作": ["季度报告.docx", "预算表.xlsx", "产品路线图.pptx", "会议纪要.md", "合同扫描.pdf"],
    "设计": ["首页草图.png", "配色方案.svg", "图标集.fig", "海报定稿.psd"],
    "项目资料": ["需求说明.docx", "接口文档.pdf", "测试报告.xlsx", "进度.txt"],
    "照片": ["海边.jpg", "山顶日出.jpg", "猫咪.png"],
    "散放": ["随手记.txt", "下载的安装包.zip", "截图 2025-06-01.png"],
}


def _touch(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(text or path.stem, encoding="utf-8")


def sample_folder(root: Path) -> Path:
    base = root / "示例桌面"
    if base.exists():
        return base
    for group, names in SAMPLE_FILES.items():
        folder = base / group if group in ("项目资料", "照片") else base
        for name in names:
            _touch(folder / name, "DeskIsle demo file: " + name)
    (base / "旅行计划").mkdir(parents=True, exist_ok=True)
    (base / "学习笔记").mkdir(parents=True, exist_ok=True)
    return base


def demo_state(root: Path) -> AppState:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    base = sample_folder(root)
    os.environ.setdefault("DESKISLE_DEMO_FILES", str(base))
    html = root / "aurora.html"
    if not html.exists() and (ASSETS / "demo" / "aurora.html").is_file():
        shutil.copy2(ASSETS / "demo" / "aurora.html", html)

    def refs(names, folder=base):
        return [ItemRef(path=str(folder / n)) for n in names]

    def files_island(title, names, x, y, w, h, **kw):
        tab = TabState(title="全部", items=refs(names), sort_mode="manual")
        return IslandState(title=title, x=x, y=y, width=w, height=h, tabs=[tab], active_tab_id=tab.id, **kw)

    work = files_island("工作文档", SAMPLE_FILES["工作"], 24, 96, 380, 250)
    second = TabState(title="设计", items=refs(SAMPLE_FILES["设计"]), sort_mode="manual")
    work.tabs.append(second)
    folders = files_island("常用文件夹", [], 24, 372, 380, 210)
    folders.tabs[0].items = [ItemRef(path=str(base / "项目资料")), ItemRef(path=str(base / "照片")),
                             ItemRef(path=str(base / "旅行计划")), ItemRef(path=str(base / "学习笔记"))]
    portal_tab = TabState(title="项目资料", portal_path=str(base / "项目资料"), sort_mode="name")
    portal = IslandState(title="文件视窗 · 项目资料", x=24, y=608, width=380, height=220, tabs=[portal_tab],
                         active_tab_id=portal_tab.id, material="clear")
    clock = IslandState(title="时钟", kind="widget", widget="clock", x=430, y=96, width=340, height=200,
                        tabs=[TabState(title="全部")], widget_config={"style": "digital"})
    weather = IslandState(title="天气", kind="widget", widget="weather", x=796, y=96, width=360, height=232,
                          tabs=[TabState(title="全部")])
    media = IslandState(title="正在播放", kind="widget", widget="media", x=430, y=322, width=360, height=176,
                        tabs=[TabState(title="全部")])
    todo = IslandState(title="待办", kind="widget", widget="todo", x=1182, y=96, width=300, height=330,
                       tabs=[TabState(title="全部")])
    web = IslandState(title="极光 · 本地 HTML", kind="web", x=816, y=354, width=440, height=300,
                      web_url=html.resolve().as_uri() if html.exists() else "about:blank", html_path=str(html),
                      tabs=[TabState(title="全部")], web_toolbar=False)
    capsule = files_island("胶囊 · 照片", SAMPLE_FILES["照片"], 1182, 452, 300, 220, capsule=True)
    capsule.tabs[0].items = refs(SAMPLE_FILES["照片"], base / "照片")
    main = PageState(title="工作台", monitor_key="demo", monitor_label="演示显示器",
                     islands=[work, folders, portal, clock, weather, media, todo, web, capsule])
    calm = PageState(title="专注", monitor_key="demo", monitor_label="演示显示器",
                     islands=[IslandState(title="时钟", kind="widget", widget="clock", x=600, y=260, width=400,
                                          height=220, tabs=[TabState(title="全部")],
                                          widget_config={"style": "analog"})])
    prefs = Preferences(onboarding_done=True, first_arrange_done=True, hide_native_icons=True,
                        island_material="liquid", wallpaper_mode="static", theme_mode="dark")
    state = AppState(version=3, pages=[main, calm], current_page_id=main.id, current_pages={"demo": main.id},
                     loose_items=refs(SAMPLE_FILES["散放"]), preferences=prefs)
    return state


__all__ = ["demo_state", "sample_folder"]
