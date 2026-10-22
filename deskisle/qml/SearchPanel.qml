// Search panel (D): islands and icons on the desktop (every preset) and files
// on the computer through Everything (built-in index as a fallback).
// ↑/↓ choose, Enter opens, Ctrl+Enter shows the file in Explorer, Esc closes.
import QtQuick

Item {
    id: panel
    property var host: null
    readonly property string key: host ? host.key : ""
    property int current: -1
    implicitWidth: 620
    implicitHeight: 18 + field.height + 10 + (hasQuery ? Math.min(list.contentHeight, 420) + 8 : hints.implicitHeight + 6) + footer.height + 14
    readonly property bool hasQuery: field.text.trim() !== ""

    readonly property var rows: {
        var out = []
        var d = Search.deskResults
        var f = Search.fileResults
        if (d.length > 0) {
            out.push({ header: "桌面上", note: "" })
            for (var i = 0; i < d.length; i++) {
                out.push(d[i])
            }
        }
        if (f.length > 0) {
            out.push({ header: "电脑中的文件", note: Search.engine === "everything" ? "Everything" : "内置索引" })
            for (var j = 0; j < f.length; j++) {
                out.push(f[j])
            }
        }
        return out
    }
    onRowsChanged: current = firstRow()

    function firstRow() {
        for (var i = 0; i < rows.length; i++) {
            if (!rows[i].header) {
                return i
            }
        }
        return -1
    }
    function step(delta) {
        var i = current
        for (var n = 0; n < rows.length; n++) {
            i += delta
            if (i < 0 || i >= rows.length) {
                return
            }
            if (!rows[i].header) {
                current = i
                list.positionViewAtIndex(i, ListView.Contain)
                return
            }
        }
    }
    function activate(row, reveal) {
        if (!row || row.header) {
            return
        }
        if (row.kind === "island") {
            Search.locate(row.uid, row.pageId, "")
        } else if (reveal) {
            Search.reveal(row.path)
        } else {
            Search.open(row.path)
        }
        Desk.closePanel()
    }

    Component.onCompleted: {
        Search.warmUp()
        if (Search.query !== "") {
            field.text = Search.query
        }
        Qt.callLater(field.focusField)
    }

    GTextField {
        id: field
        x: 18
        y: 18
        width: parent.width - 36
        height: 42
        implicitHeight: 42
        fontSize: 16
        icon: "search"
        placeholder: "搜索岛屿、桌面图标和电脑里的文件"
        monitorKey: panel.key
        selectOnFocus: true
        onEdited: Search.search(text)
        onAccepted: panel.activate(panel.rows[panel.current], (lastModifiers & Qt.ControlModifier) !== 0)
        onEscaped: Desk.closePanel()
        onUpPressed: panel.step(-1)
        onDownPressed: panel.step(1)
        onTabPressed: panel.step(1)
    }

    // Results ------------------------------------------------------------------------------------------------
    ListView {
        id: list
        visible: panel.hasQuery
        x: 10
        anchors.top: field.bottom
        anchors.topMargin: 10
        width: parent.width - 20
        height: Math.min(contentHeight, 420)
        clip: true
        model: panel.rows
        boundsBehavior: Flickable.StopAtBounds
        delegate: Loader {
            id: rowLoader
            required property var modelData
            required property int index
            width: list.width
            sourceComponent: modelData.header ? headerRow : resultRow
            Component {
                id: headerRow
                Item {
                    height: 30
                    Row {
                        x: 10
                        anchors.bottom: parent.bottom
                        anchors.bottomMargin: 6
                        spacing: 8
                        Text {
                            text: rowLoader.modelData.header
                            color: Theme.textFaint
                            font.family: Theme.fontFamily
                            font.pixelSize: 12
                            font.weight: Font.DemiBold
                        }
                        Rectangle {
                            visible: rowLoader.modelData.note !== ""
                            anchors.verticalCenter: parent.verticalCenter
                            height: 18
                            width: noteText.implicitWidth + 12
                            radius: 9
                            color: Theme.accentSoft
                            Text {
                                id: noteText
                                anchors.centerIn: parent
                                text: rowLoader.modelData.note
                                color: Theme.accent
                                font.family: Theme.fontFamily
                                font.pixelSize: 10
                                font.weight: Font.DemiBold
                            }
                        }
                    }
                }
            }
            Component {
                id: resultRow
                Item {
                    id: r
                    readonly property var row: rowLoader.modelData
                    readonly property bool selected: panel.current === rowLoader.index
                    height: 46
                    Rectangle {
                        anchors.fill: parent
                        radius: Theme.smallRadius
                        color: r.selected ? Theme.accentSoft : (ra.containsMouse ? Theme.hover : "transparent")
                    }
                    Item {
                        id: iconBox
                        x: 10
                        anchors.verticalCenter: parent.verticalCenter
                        width: 30
                        height: 30
                        Image {
                            anchors.fill: parent
                            visible: r.row.icon !== ""
                            source: r.row.icon
                            sourceSize: Qt.size(64, 64)
                            asynchronous: true
                            fillMode: Image.PreserveAspectFit
                        }
                        Rectangle {
                            anchors.fill: parent
                            visible: r.row.icon === ""
                            radius: 9
                            color: Theme.accentSoft
                            Glyph {
                                anchors.centerIn: parent
                                name: r.row.glyph || "box"
                                size: 17
                                color: Theme.accent
                            }
                        }
                    }
                    Column {
                        anchors.left: iconBox.right
                        anchors.leftMargin: 12
                        anchors.right: actions.left
                        anchors.rightMargin: 8
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 1
                        Text {
                            width: parent.width
                            text: r.row.name
                            color: Theme.text
                            elide: Text.ElideRight
                            font.family: Theme.fontFamily
                            font.pixelSize: 14
                            font.weight: Font.Medium
                        }
                        Text {
                            width: parent.width
                            text: r.row.kind === "island" ? "岛屿 · " + r.row.folder : r.row.folder
                            color: Theme.textDim
                            elide: Text.ElideMiddle
                            font.family: Theme.fontFamily
                            font.pixelSize: 11
                        }
                    }
                    MouseArea {
                        id: ra
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onEntered: panel.current = rowLoader.index
                        onClicked: panel.activate(r.row, false)
                    }
                    Row {
                        id: actions
                        anchors.right: parent.right
                        anchors.rightMargin: 8
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 2
                        opacity: r.selected || ra.containsMouse ? 1 : 0
                        IconButton {
                            visible: r.row.uid !== "" && r.row.kind === "item"
                            icon: "map-pin"
                            tip: "在岛上定位"
                            size: 28
                            iconSize: 15
                            onClicked: {
                                Search.locate(r.row.uid, r.row.pageId, r.row.path)
                                Desk.closePanel()
                            }
                        }
                        IconButton {
                            visible: r.row.path !== ""
                            icon: "folder-open"
                            tip: "在资源管理器中显示  Ctrl+Enter"
                            size: 28
                            iconSize: 15
                            onClicked: panel.activate(r.row, true)
                        }
                        IconButton {
                            visible: r.row.path !== ""
                            icon: "copy"
                            tip: "复制路径"
                            size: 28
                            iconSize: 15
                            onClicked: Search.copyPath(r.row.path)
                        }
                    }
                }
            }
        }
    }

    // Hints (empty query) ---------------------------------------------------------------------------------
    Column {
        id: hints
        visible: !panel.hasQuery
        x: 22
        anchors.top: field.bottom
        anchors.topMargin: 14
        width: parent.width - 44
        spacing: 8
        Repeater {
            model: [
                { i: "box", t: "岛屿和桌面图标：包括其他预设里的，回车直接定位或打开" },
                { i: "search", t: "电脑里的文件：已安装 Everything 时即时搜索全盘，否则使用内置索引" },
                { i: "keyboard", t: "↑ ↓ 选择 · Enter 打开 · Ctrl+Enter 在资源管理器中显示 · Ctrl+Alt+F 随时唤出" }
            ]
            delegate: Row {
                required property var modelData
                spacing: 10
                Glyph { name: modelData.i; size: 15; color: Theme.textFaint; anchors.verticalCenter: parent.verticalCenter }
                Text {
                    text: modelData.t
                    color: Theme.textDim
                    font.family: Theme.fontFamily
                    font.pixelSize: 12
                    anchors.verticalCenter: parent.verticalCenter
                }
            }
        }
    }

    // Footer -----------------------------------------------------------------------------------------------
    Item {
        id: footer
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 12
        x: 22
        width: parent.width - 44
        height: 18
        Row {
            spacing: 8
            anchors.verticalCenter: parent.verticalCenter
            Rectangle {
                width: 8
                height: 8
                radius: 4
                anchors.verticalCenter: parent.verticalCenter
                color: Search.busy ? Theme.accent : (Search.engine === "everything" ? "#3BC47A" : Theme.textFaint)
                SequentialAnimation on opacity {
                    running: Search.busy
                    loops: Animation.Infinite
                    alwaysRunToEnd: true
                    NumberAnimation { to: 0.25; duration: 420 }
                    NumberAnimation { to: 1; duration: 420 }
                }
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: Search.status !== "" ? Search.status
                      : (Search.engine === "everything" ? "Everything 已连接" : "输入后开始搜索")
                color: Theme.textFaint
                font.family: Theme.fontFamily
                font.pixelSize: 11
            }
        }
    }
}
