// Settings · 桌面: desktop icons + auto-sort rules, arrangement and layout
// memory, snapshots, waking DeskIsle up, start-up and performance.
import QtQuick

Column {
    id: page
    property var win: null
    readonly property var p: Desk.prefs
    property var snapshots: []
    property bool allSnapshots: false
    property var hotkeys: []
    width: parent ? parent.width : 640
    spacing: 22

    function reloadSnapshots() {
        snapshots = Desk.snapshotList()
    }
    Component.onCompleted: {
        reloadSnapshots()
        hotkeys = App.hotkeyTable()
        memRefresh.start()
    }
    Connections {
        target: Desk
        function onSnapshotsChanged() { page.reloadSnapshots() }
        function onStateReplaced() { page.reloadSnapshots() }
    }

    component KeyCap: Rectangle {
        property string text: ""
        width: capText.implicitWidth + 14
        height: 24
        radius: 6
        color: Theme.dark ? Qt.rgba(1, 1, 1, 0.08) : "#FFFFFF"
        border.width: 1
        border.color: Theme.hairline
        Rectangle {
            // key "depth"
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 2
            radius: 6
            color: Theme.hairline
        }
        Text {
            id: capText
            anchors.centerIn: parent
            text: parent.text
            color: Theme.text
            font.family: Theme.fontFamily
            font.pixelSize: 12
        }
    }

    // ---- 桌面图标 --------------------------------------------------------------------
    SettingsCard {
        title: "桌面图标"
        SettingRow {
            title: "由桌屿显示桌面图标"
            description: "隐藏 Windows 原生桌面图标，改由桌屿统一显示与排列；退出桌屿时自动恢复。"
            pref: "hide_native_icons"
            kind: "switch"
        }
        SettingRow {
            title: "自动归流"
            description: "桌面上新出现的文件按下面的“归流规则”放进对应的收纳岛。"
            pref: "auto_organize"
            kind: "switch"
        }
        SettingRow {
            title: "使用 Everything 搜索"
            description: "已安装并运行 Everything 时，搜索面板直接查询它的索引，秒出全盘结果；否则使用桌屿的内置索引。"
                         + (Search.engine === "everything" ? " 当前：Everything。"
                            : Search.engine === "local" ? " 当前：内置索引。" : "")
            pref: "everything_search"
            kind: "switch"
        }
    }

    RulesEditor {}

    // ---- 排布 ------------------------------------------------------------------------
    SettingsCard {
        title: "排布"
        note: "同一台显示器上的收纳岛任何时候都不会重叠。拖动标题栏移动，停在另一个收纳岛上片刻可交换位置；拖动边缘缩放时，旁边的收纳岛会自动让出空间。"
        SettingRow {
            title: "吸附到网格"
            description: "移动和缩放收纳岛时对齐到网格。"
            pref: "snap_to_grid"
            kind: "switch"
        }
        SettingRow {
            visible: !!page.p.snap_to_grid
            title: "网格尺寸"
            pref: "grid_size"
            kind: "slider"
            from: 4
            to: 32
            step: 1
            unit: " px"
        }
        SettingRow {
            title: "收纳岛间距"
            description: "收纳岛之间以及与屏幕边缘至少保持的距离。"
            pref: "layout_gap"
            kind: "slider"
            from: 4
            to: 48
            step: 1
            unit: " px"
        }
        SettingRow {
            title: "按显示器组合记忆布局"
            description: "每一种显示器组合（例如笔记本单屏、接上扩展屏、投影）各自记住一套布局，插拔后自动恢复。"
            pref: "layout_memory"
            kind: "switch"
        }
        SettingRow {
            title: "重新连接等待"
            description: "显示器短暂断开（休眠唤醒、切换输入源）时，先等待这段时间再重新排布。"
            pref: "replug_grace_s"
            kind: "slider"
            from: 0
            to: 60
            step: 1
            unit: " 秒"
        }
    }

    // ---- 布局快照 ----------------------------------------------------------------------
    SettingsCard {
        title: "布局快照"
        note: "快照保存所有显示器上的收纳岛、标签与预设；恢复前会自动备份当前布局。导出的布局文件可以在另一台电脑上导入。"
        SettingRow {
            title: "布局快照"
            description: page.snapshots.length ? "共 " + page.snapshots.length + " 个快照。" : "还没有快照。"
            GButton {
                text: "保存快照"
                icon: "device-floppy"
                kind: "accent"
                compact: true
                onClicked: Desk.action("snapshot.save", {})
            }
            GButton {
                text: "导出…"
                icon: "upload"
                compact: true
                onClicked: Desk.action("layout.export", {})
            }
            GButton {
                text: "导入…"
                icon: "download"
                compact: true
                onClicked: Desk.action("layout.import", {})
            }
        }
        Repeater {
            model: page.allSnapshots ? page.snapshots : page.snapshots.slice(0, 6)
            delegate: Item {
                id: snap
                required property var modelData
                width: parent ? parent.width : 600
                height: 50
                Rectangle {
                    x: 16
                    width: parent.width - 32
                    height: 1
                    color: Theme.hairline
                }
                Glyph {
                    x: 18
                    anchors.verticalCenter: parent.verticalCenter
                    name: "history"
                    size: 17
                    color: Theme.textDim
                }
                Column {
                    x: 48
                    anchors.verticalCenter: parent.verticalCenter
                    width: parent.width - x - 170
                    spacing: 2
                    Text {
                        width: parent.width
                        elide: Text.ElideMiddle
                        text: snap.modelData.name
                        color: Theme.text
                        font.family: Theme.fontFamily
                        font.pixelSize: 13
                    }
                    Text {
                        text: snap.modelData.time
                        color: Theme.textFaint
                        font.family: Theme.fontFamily
                        font.pixelSize: 11
                    }
                }
                Row {
                    anchors.right: parent.right
                    anchors.rightMargin: 16
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 6
                    GButton {
                        text: "恢复"
                        compact: true
                        onClicked: Desk.action("snapshot.restore:" + snap.modelData.path, {})
                    }
                    IconButton {
                        anchors.verticalCenter: parent.verticalCenter
                        icon: "trash"
                        tip: "删除这个快照"
                        size: 30
                        iconSize: 16
                        onClicked: Desk.action("snapshot.delete:" + snap.modelData.path, {})
                    }
                }
            }
        }
        Item {
            visible: page.snapshots.length > 6
            width: parent ? parent.width : 600
            height: 40
            GButton {
                anchors.centerIn: parent
                text: page.allSnapshots ? "收起" : "显示全部 " + page.snapshots.length + " 个"
                kind: "ghost"
                compact: true
                onClicked: page.allSnapshots = !page.allSnapshots
            }
        }
    }

    // ---- 唤醒与快捷键 --------------------------------------------------------------------
    SettingsCard {
        title: "唤醒与快捷键"
        SettingRow {
            title: "双击桌面空白处"
            description: "隐藏或唤回全部收纳岛。"
            pref: "wake_double_click"
            kind: "switch"
        }
        SettingRow {
            title: "胶囊悬停预览"
            description: "鼠标停在收拢成胶囊的收纳岛上这么久后，临时展开预览；移开即收回。"
            pref: "capsule_peek_ms"
            kind: "slider"
            from: 0
            to: 2000
            step: 20
            unit: " 毫秒"
        }
        SettingRow {
            title: "全局快捷键"
            description: "在任何程序中都能使用下面的组合键。"
            pref: "hotkeys_enabled"
            kind: "switch"
        }
        Column {
            visible: !!page.p.hotkeys_enabled && page.hotkeys.length > 0
            width: parent.width
            bottomPadding: 10
            Repeater {
                model: page.hotkeys
                delegate: Item {
                    id: hk
                    required property var modelData
                    width: parent ? parent.width : 600
                    height: 36
                    Text {
                        x: 32
                        anchors.verticalCenter: parent.verticalCenter
                        text: hk.modelData.label
                        color: Theme.textDim
                        font.family: Theme.fontFamily
                        font.pixelSize: 13
                    }
                    Row {
                        anchors.right: parent.right
                        anchors.rightMargin: 16
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 4
                        Repeater {
                            model: String(hk.modelData.keys).split("+")
                            delegate: KeyCap {
                                required property var modelData
                                text: modelData
                            }
                        }
                    }
                }
            }
        }
        SettingRow {
            title: "守护桌面层"
            description: "收纳岛被其他程序隐藏或盖住时自动恢复；桌屿意外退出时自动重启，并恢复原生桌面图标。"
            pref: "watchdog"
            kind: "switch"
        }
    }

    // ---- 启动与性能 ----------------------------------------------------------------------
    SettingsCard {
        title: "启动与性能"
        SettingRow {
            title: "开机自动启动"
            description: "登录 Windows 后自动启动桌屿。"
            pref: "start_with_windows"
            kind: "switch"
        }
        SettingRow {
            title: "无人观看时暂停"
            description: "全屏或最大化的窗口挡住桌面、锁屏或隐藏收纳岛时，暂停视频、网页、动画与动态壁纸读取。"
            pref: "smart_pause"
            kind: "switch"
        }
        SettingRow {
            title: "视频帧率上限"
            description: "收纳岛中视频与 HTML 动画的最高帧率；24 帧已足够流畅。"
            pref: "media_fps"
            kind: "slider"
            from: 5
            to: 60
            step: 1
            unit: " 帧"
        }
        SettingRow {
            title: "空闲时释放内存"
            description: "启动完成、关闭设置或隐藏收纳岛后，把暂时用不到的内存还给系统；再次使用时按需载回。"
            pref: "idle_trim"
            kind: "switch"
        }
        SettingRow {
            id: memRow
            title: "当前内存占用"
            description: page.memText
            GButton {
                text: "立即释放"
                icon: "bolt"
                compact: true
                onClicked: { App.trimMemoryNow(); memRefresh.restart() }
            }
            IconButton {
                anchors.verticalCenter: parent.verticalCenter
                icon: "refresh"
                tip: "刷新"
                size: 30
                iconSize: 16
                onClicked: page.memText = App.memoryText()
            }
        }
        SettingRow {
            title: "网页显示方式"
            description: page.p.web_hosting === "composition"
                         ? "合成（实验）：网页与玻璃、动画融合，但可能无法直接点击或输入；遇到问题请改回自动。"
                         : page.p.web_hosting === "windowed"
                           ? "窗口：网页放在独立的子窗口中，可直接交互、兼容性最好，但不参与玻璃效果。"
                           : "自动：默认用窗口模式，可直接点击、滚动和输入；只有能放到玻璃下层时才使用合成。"
            pref: "web_hosting"
            kind: "segmented"
            options: [
                { value: "auto", text: "自动" },
                { value: "composition", text: "合成（实验）" },
                { value: "windowed", text: "窗口" }
            ]
        }
    }

    property string memText: "正在统计…"
    Timer {
        id: memRefresh
        interval: 700
        onTriggered: page.memText = App.memoryText()
    }
}
