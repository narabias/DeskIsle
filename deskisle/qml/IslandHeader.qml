// Island header: kind glyph, title (double-click renames), tab chips, item
// count and the hover buttons.  Dragging the header moves the island.
import QtQuick

Item {
    id: header
    property var island: null
    readonly property var proxy: island ? island.proxy : null
    readonly property string uid: island ? island.uid : ""
    readonly property string kind: island ? island.kind : "files"
    readonly property var tabs: proxy ? proxy.tabs : []
    readonly property var activeTab: {
        var list = tabs
        for (var i = 0; i < list.length; i++) {
            if (proxy && list[i].id === proxy.activeTab) {
                return list[i]
            }
        }
        return list.length ? list[0] : null
    }
    readonly property bool portalTab: !!activeTab && !!activeTab.portal
    readonly property int itemCount: proxy && proxy.itemsModel ? proxy.itemsModel.count : 0
    readonly property string kindIcon: kind === "web" ? "world"
                                     : kind === "widget" ? widgetIcon(proxy ? proxy.widget : "")
                                     : (portalTab ? "folder-open" : "folder")
    readonly property string countText: kind === "files" ? (itemCount > 0 ? itemCount + " 项" : "")
                                      : kind === "web" ? (proxy && proxy.web.loading ? "加载中" : "") : ""
    readonly property bool hot: island && (island.hovered || island.editor !== "")
    readonly property string editor: island ? island.editor : ""
    readonly property bool busyEditing: editor !== ""

    function widgetIcon(id) {
        if (id === "clock") return "clock"
        if (id === "weather") return "cloud"
        if (id === "media") return "music"
        if (id === "todo") return "checklist"
        return "puzzle"
    }
    function tabTitle(tab) {
        return tab ? (tab.title || "标签") : ""
    }

    // Drag / menu surface ------------------------------------------------------------------------------
    MouseArea {
        id: surface
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        hoverEnabled: false
        onPressed: (mouse) => {
            if (mouse.button === Qt.LeftButton) {
                island.movePress(surface, mouse)
            }
        }
        onPositionChanged: (mouse) => island.moveDrag(surface, mouse)
        onReleased: island.moveRelease()
        onCanceled: island.moveRelease()
        onClicked: (mouse) => {
            if (mouse.button === Qt.RightButton) {
                island.openMenu(surface, mouse)
            }
        }
        onDoubleClicked: (mouse) => {
            if (mouse.button === Qt.LeftButton && !header.busyEditing) {
                Desk.act(header.uid, "collapse", { value: !island.collapsed })
            }
        }
    }

    // Left: glyph + title (+ count) ---------------------------------------------------------------------
    Row {
        id: left
        anchors.left: parent.left
        anchors.leftMargin: 14
        anchors.verticalCenter: parent.verticalCenter
        spacing: 8
        visible: header.editor !== "rename" && header.editor !== "webUrl"
        Glyph {
            anchors.verticalCenter: parent.verticalCenter
            name: header.kindIcon
            size: 16
            color: Theme.accent
        }
        Item {
            width: titleText.width
            height: titleText.implicitHeight
            anchors.verticalCenter: parent.verticalCenter
            Text {
                id: titleText
                text: header.proxy ? header.proxy.title : ""
                color: Theme.text
                font.family: Theme.fontFamily
                font.pixelSize: 14
                font.weight: Font.DemiBold
                elide: Text.ElideRight
                width: Math.min(implicitWidth, Math.max(36, header.width - 140 - tabStrip.width))
            }
            MouseArea {
                anchors.fill: parent
                acceptedButtons: Qt.LeftButton | Qt.RightButton
                onPressed: (mouse) => { if (mouse.button === Qt.LeftButton) island.movePress(this, mouse) }
                onPositionChanged: (mouse) => island.moveDrag(this, mouse)
                onReleased: island.moveRelease()
                onCanceled: island.moveRelease()
                onClicked: (mouse) => { if (mouse.button === Qt.RightButton) island.openMenu(this, mouse) }
                onDoubleClicked: (mouse) => { if (mouse.button === Qt.LeftButton) island.editor = "rename" }
            }
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            visible: text !== "" && header.tabs.length <= 1
            text: header.countText
            color: Theme.textFaint
            font.family: Theme.fontFamily
            font.pixelSize: 12
        }
    }

    // Tabs ------------------------------------------------------------------------------------------
    Item {
        id: tabStrip
        anchors.left: left.right
        anchors.leftMargin: 10
        anchors.verticalCenter: parent.verticalCenter
        height: 26
        visible: header.kind === "files" && (header.tabs.length > 1 || header.editor === "addTab"
                                             || header.editor.indexOf("renameTab:") === 0)
                 && header.editor !== "rename"
        width: visible ? Math.min(chips.implicitWidth, Math.max(0, header.width - left.width - 120)) : 0
        clip: true
        Row {
            id: chips
            spacing: 4
            Repeater {
                model: header.tabs
                delegate: Rectangle {
                    id: chip
                    required property var modelData
                    required property int index
                    readonly property bool on: header.proxy && modelData.id === header.proxy.activeTab
                    readonly property bool renaming: header.editor === "renameTab:" + modelData.id
                    width: renaming ? 120 : chipText.implicitWidth + 18 + (countLabel.visible ? countLabel.width + 4 : 0)
                    height: 26
                    radius: 13
                    color: on ? Theme.accentSoft : (chipArea.containsMouse || chipDrop.containsDrag ? Theme.hover : "transparent")
                    border.width: chipDrop.containsDrag ? 1.5 : 0
                    border.color: Theme.accent
                    Behavior on color { ColorAnimation { duration: Theme.ms(120) } }
                    Row {
                        anchors.centerIn: parent
                        spacing: 4
                        visible: !chip.renaming
                        Text {
                            id: chipText
                            anchors.verticalCenter: parent.verticalCenter
                            text: header.tabTitle(chip.modelData)
                            color: chip.on ? Theme.accent : Theme.textDim
                            font.family: Theme.fontFamily
                            font.pixelSize: 12
                            font.weight: chip.on ? Font.DemiBold : Font.Normal
                        }
                        Text {
                            id: countLabel
                            anchors.verticalCenter: parent.verticalCenter
                            visible: !chip.modelData.portal && chip.modelData.count > 0
                            text: chip.modelData.count
                            color: Theme.textFaint
                            font.family: Theme.fontFamily
                            font.pixelSize: 11
                        }
                    }
                    MouseArea {
                        id: chipArea
                        anchors.fill: parent
                        hoverEnabled: true
                        visible: !chip.renaming
                        acceptedButtons: Qt.LeftButton | Qt.RightButton | Qt.MiddleButton
                        onClicked: (mouse) => {
                            if (mouse.button === Qt.LeftButton) {
                                Desk.act(header.uid, "tab", { id: chip.modelData.id })
                            } else if (mouse.button === Qt.MiddleButton) {
                                Desk.act(header.uid, "closeTab", { id: chip.modelData.id })
                            } else {
                                Desk.act(header.uid, "tab", { id: chip.modelData.id })
                                island.openMenu(chipArea, mouse)
                            }
                        }
                        onDoubleClicked: (mouse) => {
                            if (mouse.button === Qt.LeftButton) {
                                island.editor = "renameTab:" + chip.modelData.id
                            }
                        }
                    }
                    DropArea {
                        id: chipDrop
                        anchors.fill: parent
                        onEntered: (drag) => {
                            if (!(drag.hasUrls || drag.formats.indexOf("application/x-deskisle-items") >= 0)) {
                                drag.accepted = false
                                return
                            }
                            hoverSwitch.restart()
                        }
                        onExited: hoverSwitch.stop()
                        onDropped: (drop) => {
                            hoverSwitch.stop()
                            var text = drop.formats.indexOf("application/x-deskisle-items") >= 0
                                     ? drop.getDataAsString("application/x-deskisle-items") : ""
                            if (Desk.dropItems("island:" + header.uid + ":" + chip.modelData.id, -1, text, drop.urls)) {
                                drop.accept(Qt.MoveAction)
                            }
                        }
                        Timer {
                            id: hoverSwitch
                            interval: 650
                            onTriggered: Desk.act(header.uid, "tab", { id: chip.modelData.id })
                        }
                    }
                    Loader {
                        anchors.fill: parent
                        active: chip.renaming
                        sourceComponent: GTextField {
                            text: header.tabTitle(chip.modelData)
                            fontSize: 12
                            clearButton: false
                            selectOnFocus: true
                            monitorKey: island.monitorKey
                            height: 26
                            onAccepted: {
                                var t = text.trim()
                                if (t !== "") {
                                    Desk.act(header.uid, "renameTab", { id: chip.modelData.id, title: t })
                                }
                                island.closeEditor()
                            }
                            onEscaped: island.closeEditor()
                            Component.onCompleted: focusField()
                            Connections {
                                target: input
                                function onActiveFocusChanged() {
                                    if (!input.activeFocus && chip.renaming) island.closeEditor()
                                }
                            }
                        }
                    }
                }
            }
            Loader {
                active: header.editor === "addTab"
                visible: active
                height: 26
                width: active ? 130 : 0
                sourceComponent: GTextField {
                    placeholder: "新标签名称"
                    fontSize: 12
                    clearButton: false
                    monitorKey: island.monitorKey
                    height: 26
                    onAccepted: {
                        var t = text.trim()
                        Desk.act(header.uid, "addTab", { title: t })
                        island.closeEditor()
                    }
                    onEscaped: island.closeEditor()
                    Component.onCompleted: focusField()
                    Connections {
                        target: input
                        function onActiveFocusChanged() {
                            if (!input.activeFocus && header.editor === "addTab") island.closeEditor()
                        }
                    }
                }
            }
        }
    }

    // Inline editors: rename / web url ---------------------------------------------------------------
    Loader {
        anchors.left: parent.left
        anchors.right: buttons.left
        anchors.leftMargin: 12
        anchors.rightMargin: 6
        anchors.verticalCenter: parent.verticalCenter
        height: 30
        active: header.editor === "rename" || header.editor === "webUrl"
        visible: active
        sourceComponent: GTextField {
            readonly property bool urlMode: header.editor === "webUrl"
            text: urlMode ? (header.proxy ? header.proxy.webUrl : "") : (header.proxy ? header.proxy.title : "")
            placeholder: urlMode ? "输入网址，回车打开" : "收纳岛名称"
            icon: urlMode ? "world" : "pencil"
            fontSize: 13
            selectOnFocus: true
            monitorKey: island.monitorKey
            height: 30
            onAccepted: {
                var t = text.trim()
                if (urlMode) {
                    if (t !== "") Desk.act(header.uid, "web.url", { url: t })
                } else if (t !== "") {
                    Desk.act(header.uid, "rename", { title: t })
                }
                island.closeEditor()
            }
            onEscaped: island.closeEditor()
            Component.onCompleted: focusField()
            Connections {
                target: input
                function onActiveFocusChanged() {
                    if (!input.activeFocus && (header.editor === "rename" || header.editor === "webUrl")) {
                        island.closeEditor()
                    }
                }
            }
        }
    }

    // Right: hover buttons -----------------------------------------------------------------------------
    Row {
        id: buttons
        anchors.right: parent.right
        anchors.rightMargin: 8
        anchors.verticalCenter: parent.verticalCenter
        spacing: 2
        opacity: header.hot ? 1 : 0.45
        Behavior on opacity { NumberAnimation { duration: Theme.ms(140) } }
        IconButton {
            visible: header.kind === "files" && header.hot && !header.portalTab
            icon: "plus"
            tip: "新建标签"
            size: 28
            iconSize: 16
            onClicked: island.editor = "addTab"
        }
        IconButton {
            visible: header.kind === "files" && header.hot && header.portalTab
            icon: "arrow-up"
            tip: "上一级"
            size: 28
            iconSize: 16
            enabled: header.proxy && header.proxy.portalCanUp
            opacity: enabled ? 1 : 0.35
            onClicked: Desk.act(header.uid, "portalUp", {})
        }
        IconButton {
            visible: header.kind === "web" && header.hot
            icon: header.proxy && header.proxy.web.loading ? "x" : "refresh"
            tip: header.proxy && header.proxy.web.loading ? "停止" : "刷新"
            size: 28
            iconSize: 16
            onClicked: Desk.act(header.uid, header.proxy && header.proxy.web.loading ? "web.stop" : "web.reload", {})
        }
        IconButton {
            visible: header.kind === "web" && header.hot
            icon: "external-link"
            tip: "在浏览器中打开"
            size: 28
            iconSize: 16
            onClicked: Desk.act(header.uid, "web.external", {})
        }
        IconButton {
            icon: island && island.collapsed ? "chevron-down" : "chevron-up"
            tip: island && island.collapsed ? "展开" : "收起"
            size: 28
            iconSize: 16
            onClicked: Desk.act(header.uid, "collapse", { value: !island.collapsed })
        }
        IconButton {
            id: menuButton
            icon: "dots"
            tip: "更多"
            size: 28
            iconSize: 16
            onClicked: island.openMenuBelow(menuButton)
        }
    }

    // Lock / pin markers.
    Row {
        anchors.right: buttons.left
        anchors.rightMargin: 4
        anchors.verticalCenter: parent.verticalCenter
        spacing: 4
        visible: !header.busyEditing
        Glyph { visible: island && island.locked; name: "lock"; size: 13; color: Theme.textFaint; anchors.verticalCenter: parent.verticalCenter }
        Glyph { visible: header.proxy && header.proxy.pinned; name: "pin"; size: 13; color: Theme.textFaint; anchors.verticalCenter: parent.verticalCenter }
        Glyph { visible: header.proxy && header.proxy.excludeFromHide; name: "eye"; size: 13; color: Theme.textFaint; anchors.verticalCenter: parent.verticalCenter }
    }

    // Hairline under the header (only when a body is shown).
    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.leftMargin: 12
        anchors.rightMargin: 12
        height: 1
        color: Theme.hairline
        opacity: island && !island.collapsed ? 0.9 : 0
        Behavior on opacity { NumberAnimation { duration: Theme.ms(140) } }
    }
}
