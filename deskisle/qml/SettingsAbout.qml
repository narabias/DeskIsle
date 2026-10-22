// Settings · 关于: version and updates, data location, logs, open-source parts.
import QtQuick

Column {
    id: page
    property var win: null
    property int tick: 0
    readonly property var upd: (tick, App.updateInfo())
    width: parent ? parent.width : 640
    spacing: 22

    Connections {
        target: App
        function onInfoChanged() { page.tick++ }
    }

    // ---- hero ------------------------------------------------------------------------
    Item {
        width: parent.width
        height: 104
        Rectangle {
            anchors.fill: parent
            radius: 16
            color: Theme.dark ? Qt.rgba(1, 1, 1, 0.055) : Qt.rgba(1, 1, 1, 0.72)
            border.width: 1
            border.color: Theme.hairline
        }
        Image {
            id: logo
            x: 22
            anchors.verticalCenter: parent.verticalCenter
            width: 64
            height: 64
            source: "../assets/ui/app-icon.png"
            sourceSize: Qt.size(128, 128)
            mipmap: true
        }
        Column {
            x: logo.x + logo.width + 18
            anchors.verticalCenter: parent.verticalCenter
            spacing: 4
            Row {
                spacing: 10
                Text {
                    text: "桌屿 DeskIsle"
                    color: Theme.text
                    font.family: Theme.fontFamily
                    font.pixelSize: 22
                    font.weight: Font.DemiBold
                }
                Rectangle {
                    anchors.verticalCenter: parent.verticalCenter
                    width: verText.implicitWidth + 16
                    height: 22
                    radius: 11
                    color: Theme.accentSoft
                    Text {
                        id: verText
                        anchors.centerIn: parent
                        text: "版本 " + Desk.version
                        color: Theme.accent
                        font.family: Theme.fontFamily
                        font.pixelSize: 12
                        font.weight: Font.DemiBold
                    }
                }
            }
            Text {
                text: "把凌乱桌面整理成你的工作岛。"
                color: Theme.textDim
                font.family: Theme.fontFamily
                font.pixelSize: 13
            }
        }
        GButton {
            anchors.right: parent.right
            anchors.rightMargin: 22
            anchors.verticalCenter: parent.verticalCenter
            text: "项目主页"
            icon: "brand-github"
            compact: true
            onClicked: Qt.openUrlExternally(App.homepage())
        }
    }

    // ---- 更新 ------------------------------------------------------------------------
    SettingsCard {
        title: "更新"
        note: "更新只替换程序文件。收纳岛布局、归流规则、小组件与设置保存在数据目录中，安装前还会自动保存一份布局快照。"
        SettingRow {
            title: "软件更新"
            description: page.upd.checking ? "正在检查更新…"
                       : page.upd.downloading ? "正在下载更新" + (page.upd.progress >= 0 ? "（" + page.upd.progress + "%）" : "") + "…"
                       : page.upd.available ? "发现新版本 " + page.upd.version + (page.upd.title ? " · " + page.upd.title : "")
                       : "当前版本 " + page.upd.current + " 已是最新" + (page.upd.lastCheck ? "（上次检查：" + page.upd.lastCheck + "）" : "")
            GButton {
                visible: !page.upd.available
                text: page.upd.checking ? "正在检查…" : "检查更新"
                icon: "refresh"
                compact: true
                enabled: !page.upd.checking
                onClicked: App.checkUpdates()
            }
            GButton {
                visible: page.upd.available
                text: page.upd.downloading ? "正在下载…" : (page.upd.canInstall ? "下载并安装" : "前往下载")
                icon: "download"
                kind: "accent"
                compact: true
                enabled: !page.upd.downloading
                onClicked: {
                    if (page.upd.canInstall) {
                        App.installUpdate()
                    } else {
                        Qt.openUrlExternally(App.homepage() + "/releases")
                    }
                }
            }
        }
        Item {
            visible: page.upd.available && !!page.upd.notes
            width: parent.width
            height: visible ? Math.min(notes.implicitHeight, 220) + 28 : 0
            Rectangle {
                x: 16
                y: 4
                width: parent.width - 32
                height: parent.height - 16
                radius: 10
                clip: true
                color: Theme.dark ? Qt.rgba(0, 0, 0, 0.20) : Qt.rgba(0, 0, 0, 0.035)
                Flickable {
                    anchors.fill: parent
                    anchors.margins: 12
                    contentHeight: notes.implicitHeight
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    Text {
                        id: notes
                        width: parent.width
                        wrapMode: Text.Wrap
                        textFormat: Text.MarkdownText
                        text: page.upd.notes || ""
                        color: Theme.textDim
                        font.family: Theme.fontFamily
                        font.pixelSize: 12
                        onLinkActivated: (link) => Qt.openUrlExternally(link)
                    }
                }
            }
        }
        SettingRow {
            title: "自动检查更新"
            description: "每天最多检查一次 GitHub 上的正式版本；发现新版本时只提醒，不会自动安装。"
            pref: "auto_check_updates"
            kind: "switch"
        }
    }

    // ---- 数据 ------------------------------------------------------------------------
    SettingsCard {
        title: "数据与隐私"
        note: "桌屿采用本地优先设计：收纳岛只保存文件引用，整理、移动或删除收纳岛都不会移动、重命名或删除原文件。除天气与检查更新外，不会联网。"
        SettingRow {
            title: "数据目录"
            description: App.dataDir()
            GButton {
                text: "打开"
                icon: "folder-open"
                compact: true
                onClicked: Desk.openItem(App.dataDir())
            }
        }
        SettingRow {
            title: "运行日志"
            description: "遇到问题时，可以附上日志一起反馈。"
            GButton {
                text: "打开日志"
                icon: "file"
                compact: true
                onClicked: App.noticeAction("open-log")
            }
        }
        SettingRow {
            visible: App.docPath("manual") !== ""
            title: "使用说明"
            description: "功能介绍、常见问题与快捷键一览。"
            GButton {
                text: "打开"
                icon: "external-link"
                compact: true
                onClicked: Desk.openItem(App.docPath("manual"))
            }
        }
        SettingRow {
            visible: App.docPath("changelog") !== ""
            title: "更新日志"
            description: "每个版本的新功能、改动与修复。"
            GButton {
                text: "打开"
                icon: "external-link"
                compact: true
                onClicked: Desk.openItem(App.docPath("changelog"))
            }
        }
    }

    // ---- 开源组件 ----------------------------------------------------------------------
    SettingsCard {
        title: "开源组件"
        note: "感谢这些项目。完整的许可证文本见程序目录中的 THIRD-PARTY-NOTICES.md。"
        Repeater {
            model: [
                { name: "Qt 6 · PySide6", what: "界面与图形渲染", license: "LGPL-3.0" },
                { name: "Tabler Icons", what: "界面图标", license: "MIT" },
                { name: "lunar-python", what: "农历、节气与节日", license: "MIT" },
                { name: "pywinrt", what: "媒体会话与 Windows 定位", license: "MIT" },
                { name: "pywin32", what: "Windows 外壳集成", license: "PSF-2.0" },
                { name: "Microsoft Edge WebView2", what: "网页收纳岛（系统组件）", license: "Microsoft" },
                { name: "Everything", what: "文件搜索（可选，调用你已安装的 Everything）", license: "voidtools" },
                { name: "MSN 天气 · Open-Meteo", what: "天气数据", license: "CC BY 4.0（Open-Meteo）" }
            ]
            delegate: Item {
                id: lib
                required property var modelData
                required property int index
                width: parent ? parent.width : 600
                height: 46
                Rectangle {
                    visible: lib.index > 0
                    x: 16
                    width: parent.width - 32
                    height: 1
                    color: Theme.hairline
                }
                Text {
                    id: libName
                    x: 16
                    anchors.verticalCenter: parent.verticalCenter
                    text: lib.modelData.name
                    color: Theme.text
                    font.family: Theme.fontFamily
                    font.pixelSize: 13
                }
                Text {
                    anchors.left: libName.right
                    anchors.leftMargin: 10
                    anchors.right: licenseText.left
                    anchors.rightMargin: 10
                    anchors.verticalCenter: parent.verticalCenter
                    elide: Text.ElideRight
                    text: lib.modelData.what
                    color: Theme.textDim
                    font.family: Theme.fontFamily
                    font.pixelSize: 12
                }
                Text {
                    id: licenseText
                    anchors.right: parent.right
                    anchors.rightMargin: 16
                    anchors.verticalCenter: parent.verticalCenter
                    text: lib.modelData.license
                    color: Theme.textFaint
                    font.family: Theme.fontFamily
                    font.pixelSize: 12
                }
            }
        }
        SettingRow {
            title: "第三方声明"
            description: "所有组件的版权与许可说明。"
            GButton {
                text: "查看"
                icon: "file"
                compact: true
                enabled: App.docPath("notices") !== ""
                onClicked: Desk.openItem(App.docPath("notices"))
            }
        }
    }

    Text {
        width: parent.width
        horizontalAlignment: Text.AlignHCenter
        text: "桌屿 DeskIsle · 独立原创实现 · Python + Qt Quick"
        color: Theme.textFaint
        font.family: Theme.fontFamily
        font.pixelSize: 11
    }
}
