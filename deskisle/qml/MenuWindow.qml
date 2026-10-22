// Glass context menu in its own top-level window (every context menu and the
// tray menu).  The window covers the work area of the screen so cascading
// sub-menus can open on either side; a click outside the menus, Esc, or
// another application taking the foreground closes it.
// Entries: {id, text, icon, checked?, enabled, danger, shortcut, children?} or {separator: true}.
import QtQuick
import QtQuick.Window
import QtQuick.Effects

Window {
    id: win
    property var entries: []
    property string context: ""
    property string target: ""
    property var extra: ({})
    property int anchorX: 0
    property int anchorY: 0
    property rect screenRect: Qt.rect(0, 0, 1280, 800)
    // Open menu levels: [{entries, ax, ay, aw, ah, sub}] in window coordinates; ax/ay(/aw/ah) is the
    // anchor point (root) or the rectangle of the parent row (sub-menus).
    property var levels: []
    property int activeLevel: 0
    property bool opened: false

    flags: Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint | Qt.NoDropShadowWindowHint
    color: "transparent"
    title: "桌屿菜单"

    function popup() {
        x = screenRect.x + 1
        y = screenRect.y + 1
        width = Math.max(200, screenRect.width - 2)
        height = Math.max(200, screenRect.height - 2)
        var ax = Math.max(0, Math.min(width - 4, anchorX - x))
        var ay = Math.max(0, Math.min(height - 4, anchorY - y))
        levels = [{ entries: entries, ax: ax, ay: ay, aw: 0, ah: 0, sub: false }]
        activeLevel = 0
        opened = true
        show()
        raise()
        requestActivate()
        keys.forceActiveFocus()
    }
    function dismiss() {
        if (!opened) {
            return
        }
        opened = false
        levels = []
        close()
    }
    function trigger(entry) {
        if (!entry || entry.separator || entry.enabled === false || !entry.id) {
            return
        }
        var ctx = context, tgt = target, ext = extra, id = entry.id
        dismiss()
        Desk.menuAction(ctx, tgt, id, ext)
    }
    function openSub(level, entry, rowRect) {
        var hasSub = !!entry && entry.enabled !== false && !!entry.children && entry.children.length > 0
        var current = levels.length > level + 1 ? levels[level + 1] : null
        if (!hasSub) {
            // Hovering a row without children used to rebuild `levels` on every 170 ms pause, which
            // reset the whole Repeater (and replayed the fade-in).  Only touch it when one is open.
            if (current) {
                levels = levels.slice(0, level + 1)
            }
            return
        }
        if (current && current.parentId === entry.id) {
            return
        }
        var next = levels.slice(0, level + 1)
        next.push({ entries: entry.children, ax: rowRect.x, ay: rowRect.y, aw: rowRect.width, ah: rowRect.height,
                    sub: true, parentId: entry.id })
        levels = next
    }
    function closeFrom(level) {
        if (level <= 0) {
            dismiss()
            return
        }
        levels = levels.slice(0, level)
        activeLevel = level - 1
    }
    onActiveChanged: if (!active && opened) dismiss()
    Connections {
        target: Desk
        function onMenusDismissed() { win.dismiss() }
    }

    // Outside click closes.
    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.AllButtons
        onPressed: win.dismiss()
        onWheel: (wheel) => win.dismiss()
    }

    Item {
        id: keys
        anchors.fill: parent
        focus: true
        Keys.onPressed: (event) => {
            var panel = rep.itemAt(win.activeLevel)
            if (!panel || !panel.level) {
                return
            }
            if (event.key === Qt.Key_Escape) {
                win.closeFrom(win.activeLevel)
            } else if (event.key === Qt.Key_Down) {
                panel.move(1)
            } else if (event.key === Qt.Key_Up) {
                panel.move(-1)
            } else if (event.key === Qt.Key_Right) {
                panel.enterSub()
            } else if (event.key === Qt.Key_Left) {
                if (win.activeLevel > 0) {
                    win.closeFrom(win.activeLevel)
                }
            } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Space) {
                panel.activateCurrent()
            } else {
                return
            }
            event.accepted = true
        }
    }

    // Three fixed panels (root + two levels) so opening or switching a sub-menu never rebuilds the
    // delegates: a rebuilt panel restarted its fade-in from opacity 0, which is what made the menu
    // flicker while moving through the entries.
    Repeater {
        id: rep
        model: 3
        delegate: Item {
            id: panel
            required property int index
            readonly property var level: win.levels[index] !== undefined ? win.levels[index] : null
            readonly property var items: level ? (level.entries || []) : []
            property int current: -1
            readonly property real rowH: 32
            readonly property real sepH: 9
            readonly property real contentH: {
                var h = 0
                for (var i = 0; i < items.length; i++) {
                    h += items[i].separator ? sepH : rowH
                }
                return h
            }
            readonly property bool anyIcon: {
                for (var i = 0; i < items.length; i++) {
                    if (items[i].icon || items[i].checked !== undefined) {
                        return true
                    }
                }
                return false
            }
            readonly property bool anyChildren: {
                for (var i = 0; i < items.length; i++) {
                    if (items[i].children && items[i].children.length > 0) {
                        return true
                    }
                }
                return false
            }
            visible: !!level || opacity > 0.01
            width: level ? Math.round(Math.max(176, Math.min(380, 14 + (anyIcon ? 28 : 0) + textMeasure.width
                              + (shortcutMeasure.width > 0 ? shortcutMeasure.width + 26 : 0) + (anyChildren ? 22 : 0) + 16))) : 1
            height: level ? Math.min(win.height - 8, contentH + 12) : 1
            // Placement: root at the anchor (flip up / left when needed); sub-menus beside the parent row.
            x: {
                if (!level) {
                    return 0
                }
                var w = width
                if (!level.sub) {
                    return Math.max(4, Math.min(level.ax, win.width - w - 4))
                }
                var right = level.ax + level.aw - 4
                if (right + w <= win.width - 4) {
                    return right
                }
                return Math.max(4, level.ax - w + 4)
            }
            y: {
                if (!level) {
                    return 0
                }
                var h = height
                if (!level.sub) {
                    return level.ay + h <= win.height - 4 ? level.ay : Math.max(4, level.ay - h)
                }
                return Math.max(4, Math.min(level.ay - 6, win.height - h - 4))
            }
            z: index

            function selectable(i) {
                var e = items[i]
                return e && !e.separator && e.enabled !== false
            }
            function move(delta) {
                var i = current
                for (var n = 0; n < items.length; n++) {
                    i = (i + delta + items.length) % items.length
                    if (selectable(i)) {
                        current = i
                        return
                    }
                }
            }
            function rowRect(i) {
                var yy = 6
                for (var k = 0; k < i; k++) {
                    yy += items[k].separator ? sepH : rowH
                }
                return Qt.rect(panel.x, panel.y + yy - flick.contentY, panel.width, rowH)
            }
            function enterSub() {
                var e = items[current]
                if (e && e.children && e.children.length > 0 && e.enabled !== false) {
                    win.openSub(index, e, rowRect(current))
                    win.activeLevel = index + 1
                    Qt.callLater(function () {
                        var child = rep.itemAt(index + 1)
                        if (child) {
                            child.move(1)
                        }
                    })
                }
            }
            function activateCurrent() {
                var e = items[current]
                if (!e) {
                    return
                }
                if (e.children && e.children.length > 0) {
                    enterSub()
                } else {
                    win.trigger(e)
                }
            }

            Column {
                id: textMeasure
                visible: false
                Repeater {
                    model: panel.items
                    delegate: Text {
                        required property var modelData
                        text: modelData.text || ""
                        font.family: Theme.fontFamily
                        font.pixelSize: 13
                    }
                }
            }
            Column {
                id: shortcutMeasure
                visible: false
                Repeater {
                    model: panel.items
                    delegate: Text {
                        required property var modelData
                        text: modelData.shortcut || ""
                        font.family: Theme.fontFamily
                        font.pixelSize: 12
                    }
                }
            }

            opacity: level ? 1 : 0
            scale: level ? 1 : 0.96
            transformOrigin: level && level.sub ? Item.Left : Item.Top
            Behavior on opacity { NumberAnimation { duration: Theme.ms(110) } }
            Behavior on scale { NumberAnimation { duration: Theme.ms(150); easing.type: Easing.OutCubic } }

            RectangularShadow {
                anchors.fill: bg
                radius: bg.radius
                blur: 24
                offset.y: 6
                color: Qt.rgba(0, 0, 0, Theme.dark ? 0.5 : 0.22)
            }
            Rectangle {
                id: bg
                anchors.fill: parent
                radius: 14
                color: Theme.dark ? Qt.rgba(0.11, 0.115, 0.13, 0.97) : Qt.rgba(0.985, 0.985, 0.99, 0.97)
                border.width: 1
                border.color: Theme.dark ? Qt.rgba(1, 1, 1, 0.09) : Qt.rgba(0, 0, 0, 0.08)
            }
            MouseArea {
                // Inside the panel: swallow presses (no outside-dismiss).
                anchors.fill: parent
                acceptedButtons: Qt.AllButtons
            }
            Flickable {
                id: flick
                anchors.fill: parent
                anchors.margins: 6
                contentHeight: panel.contentH
                clip: contentHeight > height
                interactive: contentHeight > height
                boundsBehavior: Flickable.StopAtBounds
                Column {
                    width: flick.width
                    Repeater {
                        model: panel.items
                        delegate: Item {
                            id: row
                            required property var modelData
                            required property int index
                            readonly property bool sep: !!modelData.separator
                            readonly property bool enabledRow: !sep && modelData.enabled !== false
                            readonly property bool hasChildren: !!modelData.children && modelData.children.length > 0
                            readonly property bool open: win.levels.length > panel.index + 1
                                                         && win.levels[panel.index + 1].parentId === modelData.id
                            readonly property bool highlighted: panel.current === index || open
                            width: flick.width
                            height: sep ? panel.sepH : panel.rowH

                            Rectangle {
                                visible: row.sep
                                anchors.verticalCenter: parent.verticalCenter
                                x: 8
                                width: parent.width - 16
                                height: 1
                                color: Theme.hairline
                            }
                            Rectangle {
                                visible: !row.sep
                                anchors.fill: parent
                                radius: 8
                                color: row.highlighted && row.enabledRow
                                       ? (row.modelData.danger ? Qt.rgba(Theme.danger.r, Theme.danger.g, Theme.danger.b, 0.16) : Theme.accentSoft)
                                       : "transparent"
                            }
                            Item {
                                visible: !row.sep && panel.anyIcon
                                x: 8
                                width: 18
                                height: parent.height
                                Glyph {
                                    anchors.centerIn: parent
                                    name: row.modelData.checked === true ? "check" : (row.modelData.icon || "")
                                    visible: name !== ""
                                    size: 16
                                    color: row.modelData.danger ? Theme.danger
                                           : (row.modelData.checked === true ? Theme.accent : Theme.textDim)
                                }
                            }
                            Text {
                                visible: !row.sep
                                x: panel.anyIcon ? 36 : 12
                                anchors.verticalCenter: parent.verticalCenter
                                width: parent.width - x - (shortcut.visible ? shortcut.implicitWidth + 18 : 0) - (row.hasChildren ? 26 : 10)
                                text: row.modelData.text || ""
                                elide: Text.ElideRight
                                color: row.modelData.danger ? Theme.danger : Theme.text
                                opacity: row.enabledRow ? 1 : 0.4
                                font.family: Theme.fontFamily
                                font.pixelSize: 13
                                font.weight: row.modelData.checked === true ? Font.DemiBold : Font.Normal
                            }
                            Text {
                                id: shortcut
                                visible: !row.sep && !!row.modelData.shortcut
                                anchors.right: parent.right
                                anchors.rightMargin: row.hasChildren ? 26 : 10
                                anchors.verticalCenter: parent.verticalCenter
                                text: row.modelData.shortcut || ""
                                color: Theme.textFaint
                                font.family: Theme.fontFamily
                                font.pixelSize: 12
                            }
                            Glyph {
                                visible: row.hasChildren
                                anchors.right: parent.right
                                anchors.rightMargin: 6
                                anchors.verticalCenter: parent.verticalCenter
                                name: "chevron-right"
                                size: 14
                                color: Theme.textDim
                            }
                            Timer {
                                id: hoverOpen
                                interval: 170
                                onTriggered: {
                                    if (panel.current === row.index) {
                                        win.openSub(panel.index, row.hasChildren ? row.modelData : null,
                                                    panel.rowRect(row.index))
                                    }
                                }
                            }
                            MouseArea {
                                anchors.fill: parent
                                enabled: !row.sep
                                hoverEnabled: true
                                onEntered: {
                                    if (row.enabledRow) {
                                        panel.current = row.index
                                    }
                                    win.activeLevel = panel.index
                                    hoverOpen.restart()
                                }
                                onClicked: {
                                    if (!row.enabledRow) {
                                        return
                                    }
                                    if (row.hasChildren) {
                                        win.openSub(panel.index, row.modelData, panel.rowRect(row.index))
                                    } else {
                                        win.trigger(row.modelData)
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
