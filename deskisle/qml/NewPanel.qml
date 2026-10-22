// "+" panel: new islands and widgets, plus the web address form ("new:web").
import QtQuick

Item {
    id: panel
    property var host: null
    readonly property string key: host ? host.key : ""
    readonly property bool web: !!host && host.kind === "new:web"
    readonly property var customWidgets: Custom.revision >= 0 ? Custom.widgetList : []
    implicitWidth: 584
    implicitHeight: (web ? webForm.implicitHeight : grid.implicitHeight) + 36

    function create(name, args) {
        var a = args || {}
        a.monitor = key
        Desk.closePanel()
        // Creating the island closes this panel, which destroys the tile whose click
        // handler we are still inside ("Object destroyed while one of its QML signal
        // handlers is in progress").  Defer to the next event loop turn instead.
        Qt.callLater(function() { Desk.action(name, a) })
    }
    function openWeb() {
        Desk.openPanel("new:web", key, "")
    }
    function submitUrl() {
        var url = urlField.text.trim()
        if (url === "") {
            urlField.focusField()
            return
        }
        Desk.action("new.webUrl", { url: url, monitor: key })
    }
    onWebChanged: if (web) Qt.callLater(urlField.focusField)
    Component.onCompleted: if (web) Qt.callLater(urlField.focusField)

    component Tile: Item {
        id: tile
        property string icon: ""
        property string title: ""
        property string subtitle: ""
        property bool dashed: false
        signal activated()
        width: 268
        height: 62
        Rectangle {
            anchors.fill: parent
            radius: Theme.smallRadius
            color: area.pressed ? Theme.pressed : (area.containsMouse ? Theme.hover : "transparent")
            Behavior on color { ColorAnimation { duration: Theme.ms(110) } }
        }
        DashedRect {
            anchors.fill: parent
            visible: tile.dashed
            radius: Theme.smallRadius
            stroke: Theme.hairline
            strokeWidth: 1.2
        }
        Rectangle {
            id: badge
            x: 10
            anchors.verticalCenter: parent.verticalCenter
            width: 40
            height: 40
            radius: 12
            color: Theme.accentSoft
            Glyph {
                anchors.centerIn: parent
                name: tile.icon
                size: 20
                color: Theme.accent
            }
        }
        Column {
            anchors.left: badge.right
            anchors.leftMargin: 12
            anchors.right: parent.right
            anchors.rightMargin: 10
            anchors.verticalCenter: parent.verticalCenter
            spacing: 2
            Text {
                width: parent.width
                text: tile.title
                color: Theme.text
                elide: Text.ElideRight
                font.family: Theme.fontFamily
                font.pixelSize: 14
                font.weight: Font.DemiBold
            }
            Text {
                width: parent.width
                visible: text !== ""
                text: tile.subtitle
                color: Theme.textDim
                elide: Text.ElideRight
                font.family: Theme.fontFamily
                font.pixelSize: 12
            }
        }
        scale: area.pressed ? 0.98 : 1
        Behavior on scale { NumberAnimation { duration: Theme.ms(90) } }
        MouseArea {
            id: area
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: tile.activated()
        }
    }

    component SectionTitle: Text {
        color: Theme.textFaint
        font.family: Theme.fontFamily
        font.pixelSize: 12
        font.weight: Font.DemiBold
        font.letterSpacing: 0.6
    }

    // Grid of things to create ------------------------------------------------------------------------
    Column {
        id: grid
        visible: !panel.web
        x: 18
        y: 18
        width: parent.width - 36
        spacing: 10
        Row {
            spacing: 8
            Glyph { name: "plus"; size: 18; color: Theme.accent; anchors.verticalCenter: parent.verticalCenter }
            Text {
                text: "新建"
                color: Theme.text
                font.family: Theme.fontFamily
                font.pixelSize: 16
                font.weight: Font.Bold
                anchors.verticalCenter: parent.verticalCenter
            }
        }
        SectionTitle { text: "岛屿" }
        Grid {
            columns: 2
            columnSpacing: 12
            rowSpacing: 4
            Tile { icon: "box"; title: "收纳岛"; subtitle: "收纳桌面图标，可分多个标签页"; onActivated: panel.create("new.files") }
            Tile { icon: "folder"; title: "文件视窗"; subtitle: "实时显示一个文件夹的内容"; onActivated: panel.create("new.portal") }
            Tile { icon: "world"; title: "网页"; subtitle: "把一个网站固定在桌面上"; onActivated: panel.openWeb() }
            Tile { icon: "code"; title: "本地 HTML 动画"; subtitle: "HTML 动画、小工具或看板"; onActivated: panel.create("new.html") }
        }
        SectionTitle { text: "小组件" }
        Grid {
            columns: 2
            columnSpacing: 12
            rowSpacing: 4
            Tile { icon: "clock"; title: "时钟"; subtitle: "数字、指针或翻页样式，含农历"; onActivated: panel.create("new.widget.clock") }
            Tile { icon: "cloud"; title: "天气"; subtitle: "自动定位，实时天气与预报"; onActivated: panel.create("new.widget.weather") }
            Tile { icon: "music"; title: "正在播放"; subtitle: "控制系统中正在播放的媒体"; onActivated: panel.create("new.widget.media") }
            Tile { icon: "checklist"; title: "待办"; subtitle: "轻量清单，支持拖动排序"; onActivated: panel.create("new.widget.todo") }
            Repeater {
                model: panel.customWidgets
                delegate: Tile {
                    required property var modelData
                    icon: modelData.type === "qml" ? "sparkles" : "puzzle"
                    title: modelData.name
                    subtitle: modelData.description || (modelData.type === "qml" ? "自定义 QML 小组件" : "自定义网页小组件")
                    onActivated: panel.create("new.widget.custom:" + modelData.id)
                }
            }
            Tile {
                icon: "puzzle"
                title: "自定义小组件…"
                subtitle: "用 HTML 或 QML 编写，AI 也能帮你写"
                dashed: true
                onActivated: {
                    Desk.closePanel()
                    // Same reason as create(): do not tear this tile down from inside
                    // its own click handler.
                    Qt.callLater(function() { Desk.openSettings("widgets:自定义文件夹") })
                }
            }
        }
    }

    // Web address form ------------------------------------------------------------------------------------
    Column {
        id: webForm
        visible: panel.web
        x: 18
        y: 18
        width: parent.width - 36
        spacing: 12
        Row {
            spacing: 6
            IconButton {
                anchors.verticalCenter: parent.verticalCenter
                icon: "arrow-left"
                tip: "返回"
                size: 28
                onClicked: Desk.openPanel("new", panel.key, "")
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: "固定一个网页"
                color: Theme.text
                font.family: Theme.fontFamily
                font.pixelSize: 16
                font.weight: Font.Bold
            }
        }
        Row {
            width: parent.width
            spacing: 10
            GTextField {
                id: urlField
                width: parent.width - goButton.width - 10
                icon: "link"
                placeholder: "输入网址，例如 bilibili.com"
                monitorKey: panel.key
                onAccepted: panel.submitUrl()
                onEscaped: Desk.closePanel()
            }
            GButton {
                id: goButton
                anchors.verticalCenter: parent.verticalCenter
                text: "固定到桌面"
                kind: "accent"
                icon: "pin"
                onClicked: panel.submitUrl()
            }
        }
        Text {
            text: "常用"
            color: Theme.textFaint
            font.family: Theme.fontFamily
            font.pixelSize: 12
            font.weight: Font.DemiBold
        }
        Flow {
            width: parent.width
            spacing: 8
            Repeater {
                model: [
                    { t: "哔哩哔哩", u: "https://www.bilibili.com" },
                    { t: "知乎", u: "https://www.zhihu.com" },
                    { t: "微博热搜", u: "https://s.weibo.com/top/summary" },
                    { t: "GitHub", u: "https://github.com" },
                    { t: "日历 (Outlook)", u: "https://outlook.live.com/calendar" },
                    { t: "Notion", u: "https://www.notion.so" }
                ]
                delegate: GButton {
                    required property var modelData
                    compact: true
                    text: modelData.t
                    onClicked: {
                        urlField.text = modelData.u
                        panel.submitUrl()
                    }
                }
            }
        }
        Text {
            width: parent.width
            wrapMode: Text.Wrap
            text: "网页岛像浏览器一样可以直接操作；登录状态会被记住。被全屏程序挡住时自动暂停渲染。"
            color: Theme.textDim
            font.family: Theme.fontFamily
            font.pixelSize: 12
        }
    }
}
