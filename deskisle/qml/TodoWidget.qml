// Todo widget: items live in the island's widget config (so they travel with
// snapshots and exports).  Click the circle to finish, double-click to edit,
// drag the handle to reorder; "@明天 18:00" style suffixes or the calendar
// button set a due date.  2.0.1: finished / deleted rows fold away smoothly,
// finished items are tucked behind "已完成 N", due dates show on the clock
// widget's calendar and remind at their time (date-only items at 09:00).
import QtQuick

Item {
    id: todo
    property var island: null
    readonly property string uid: island ? island.uid : ""
    readonly property var all: (Todo.revision, island && island.proxy ? island.proxy.widgetConfig : null,
                                uid !== "" ? Todo.list(uid) : [])
    property bool showDone: false
    readonly property var items: {
        var open = [], done = []
        for (var i = 0; i < all.length; i++) {
            var it = all[i]
            it.idx = i
            if (it.done) {
                done.push(it)
            } else {
                open.push(it)
            }
        }
        return showDone ? open.concat(done) : open
    }
    readonly property int openCount: {
        var n = 0
        for (var i = 0; i < all.length; i++) {
            if (!all[i].done) {
                n++
            }
        }
        return n
    }
    readonly property int doneCount: all.length - openCount
    property string editing: ""
    property var leaving: ({})              // id -> "done" | "remove" (row folding away)

    function leave(id, kind) {
        var next = Object.assign({}, leaving)
        next[id] = kind
        leaving = next
    }
    function commit(id) {
        // Called after the fold animation (deferred: the model reset destroys the row).
        Qt.callLater(todo.commitNow, id)
    }
    function commitNow(id) {
        var kind = leaving[id]
        if (kind === "done") {
            for (var i = 0; i < all.length; i++) {
                if (all[i].id === id && !all[i].done) {
                    Todo.toggle(uid, id)
                }
            }
        } else if (kind === "remove") {
            Todo.remove(uid, id)
        }
        var next = Object.assign({}, leaving)
        delete next[id]
        leaving = next
    }
    function pickDate(item) {
        var d = item.due || ""
        sheet.itemId = item.id
        sheet.itemText = item.text
        sheet.hadDue = d !== ""
        sheet.date = d.slice(0, 10)
        sheet.time = d.length > 10 ? d.slice(11, 16) : ""
        sheet.anchor = sheet.date !== "" ? new Date(sheet.date + "T00:00") : new Date()
        sheetCal.offset = 0
        sheet.open = true
    }

    // Title ---------------------------------------------------------------------------------------------
    Item {
        id: head
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.leftMargin: 18
        anchors.rightMargin: 12
        anchors.topMargin: 12
        height: 26
        Row {
            anchors.verticalCenter: parent.verticalCenter
            spacing: 8
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: todo.island && todo.island.proxy ? todo.island.proxy.title : "待办"
                color: Theme.text
                font.family: Theme.fontFamily
                font.pixelSize: 15
                font.weight: Font.DemiBold
            }
            Rectangle {
                anchors.verticalCenter: parent.verticalCenter
                visible: todo.openCount > 0
                width: countText.implicitWidth + 12
                height: 18
                radius: 9
                color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.18)
                Text {
                    id: countText
                    anchors.centerIn: parent
                    text: todo.openCount
                    color: Theme.accent
                    font.family: Theme.fontFamily
                    font.pixelSize: 11
                    font.weight: Font.Bold
                }
            }
        }
        Row {
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: 2
            GButton {
                visible: todo.showDone && todo.doneCount > 0
                text: "清除"
                kind: "ghost"
                compact: true
                tip: "删除全部已完成的待办"
                onClicked: Todo.clearDone(todo.uid)
            }
            GButton {
                visible: todo.doneCount > 0
                text: "已完成 " + todo.doneCount
                icon: todo.showDone ? "chevron-up" : "chevron-down"
                kind: "ghost"
                compact: true
                tip: todo.showDone ? "收起已完成" : "显示已完成"
                onClicked: todo.showDone = !todo.showDone
            }
        }
    }

    // List ----------------------------------------------------------------------------------------------
    ListView {
        id: list
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: head.bottom
        anchors.bottom: adder.top
        anchors.topMargin: 6
        anchors.bottomMargin: 8
        anchors.leftMargin: 8
        anchors.rightMargin: 8
        clip: true
        spacing: 1
        model: todo.items
        boundsBehavior: Flickable.StopAtBounds
        property int dragFrom: -1
        property int dragTo: -1
        delegate: Item {
            id: row
            required property var modelData
            required property int index
            readonly property string leaving: todo.leaving[modelData.id] || ""
            readonly property bool done: !!modelData.done || leaving === "done"
            readonly property bool hot: rowHover.hovered && leaving === ""
            readonly property real fullH: Math.max(34, label.implicitHeight + 14)
            property real fold: 1
            width: list.width
            height: fullH * fold
            clip: fold < 1

            onLeavingChanged: if (leaving !== "") foldAway.restart()
            Component.onCompleted: {
                if (leaving !== "") {
                    foldAway.restart()       // the list was rebuilt mid-animation
                }
                if (todo.editing === modelData.id) {
                    editLoader.active = true
                }
            }
            SequentialAnimation {
                id: foldAway
                // A finished item first shows its tick, then folds; a deleted one slides out.
                PauseAnimation { duration: row.leaving === "done" ? Theme.ms(280) : 0 }
                ParallelAnimation {
                    NumberAnimation { target: row; property: "fold"; to: 0; duration: Theme.ms(260); easing.type: Easing.InOutCubic }
                    NumberAnimation { target: body; property: "opacity"; to: 0; duration: Theme.ms(200) }
                    NumberAnimation { target: body; property: "x"; to: row.leaving === "remove" ? 28 : 0; duration: Theme.ms(260); easing.type: Easing.InCubic }
                }
                ScriptAction { script: todo.commit(row.modelData.id) }
            }

            HoverHandler { id: rowHover }
            Item {
                id: body
                width: parent.width
                height: row.fullH
                Rectangle {
                    anchors.fill: parent
                    radius: 9
                    color: list.dragTo === row.index && list.dragFrom !== row.index ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.16)
                         : (row.hot ? Theme.hover : "transparent")
                }
                // Drag handle (reorder).
                Glyph {
                    id: handle
                    anchors.left: parent.left
                    anchors.leftMargin: 2
                    anchors.verticalCenter: parent.verticalCenter
                    name: "grip-horizontal"
                    size: 12
                    rotation: 90
                    color: Theme.textFaint
                    opacity: row.hot && !row.modelData.done ? 0.9 : 0
                    MouseArea {
                        anchors.fill: parent
                        anchors.margins: -4
                        enabled: !row.modelData.done
                        cursorShape: Qt.SizeVerCursor
                        preventStealing: true
                        onPressed: list.dragFrom = row.index
                        onPositionChanged: (mouse) => {
                            var p = mapToItem(list.contentItem, mouse.x, mouse.y)
                            list.dragTo = Math.max(0, Math.min(todo.openCount - 1, list.indexAt(10, p.y)))
                        }
                        onReleased: {
                            var from = list.dragFrom, to = list.dragTo
                            if (from >= 0 && to >= 0 && from !== to && from < todo.items.length && to < todo.items.length) {
                                Todo.move(todo.uid, todo.items[from].idx, todo.items[to].idx)
                            }
                            list.dragFrom = -1
                            list.dragTo = -1
                        }
                    }
                }
                // Check circle.
                Rectangle {
                    id: check
                    anchors.left: handle.right
                    anchors.leftMargin: 4
                    anchors.verticalCenter: parent.verticalCenter
                    width: 20
                    height: 20
                    radius: 10
                    color: row.done ? Theme.accent : "transparent"
                    border.width: row.done ? 0 : 1.5
                    border.color: checkMouse.containsMouse ? Theme.accent : Theme.textFaint
                    scale: row.leaving === "done" ? 1.12 : 1
                    Behavior on color { ColorAnimation { duration: Theme.ms(140) } }
                    Behavior on scale { NumberAnimation { duration: Theme.ms(160); easing.type: Easing.OutBack } }
                    Glyph {
                        anchors.centerIn: parent
                        visible: row.done
                        name: "check"
                        size: 13
                        stroke: 2.4
                        color: Theme.onAccent
                    }
                    MouseArea {
                        id: checkMouse
                        anchors.fill: parent
                        anchors.margins: -4
                        hoverEnabled: true
                        enabled: row.leaving === ""
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            if (row.modelData.done) {
                                Todo.toggle(todo.uid, row.modelData.id)
                            } else {
                                todo.leave(row.modelData.id, "done")
                            }
                        }
                    }
                }
                Text {
                    id: label
                    visible: todo.editing !== row.modelData.id
                    anchors.left: check.right
                    anchors.leftMargin: 10
                    anchors.right: due.visible ? due.left : (tools.visible ? tools.left : parent.right)
                    anchors.rightMargin: 6
                    anchors.verticalCenter: parent.verticalCenter
                    text: row.modelData.text
                    color: row.done ? Theme.textFaint : Theme.text
                    Behavior on color { ColorAnimation { duration: Theme.ms(140) } }
                    font.family: Theme.fontFamily
                    font.pixelSize: 13
                    font.strikeout: row.done
                    wrapMode: Text.Wrap
                    maximumLineCount: 3
                    elide: Text.ElideRight
                    MouseArea {
                        anchors.fill: parent
                        onDoubleClicked: {
                            todo.editing = row.modelData.id
                            editLoader.active = true
                        }
                    }
                }
                Loader {
                    id: editLoader
                    active: false
                    anchors.left: check.right
                    anchors.leftMargin: 6
                    anchors.right: parent.right
                    anchors.rightMargin: 4
                    anchors.verticalCenter: parent.verticalCenter
                    sourceComponent: GTextField {
                        height: 30
                        fontSize: 13
                        monitorKey: todo.island ? todo.island.monitorKey : ""
                        clearButton: false
                        selectOnFocus: true
                        Component.onCompleted: {
                            text = row.modelData.text
                            focusField()
                        }
                        function finish(save) {
                            if (save && text.trim() !== "") {
                                Todo.edit(todo.uid, row.modelData.id, text)
                            }
                            todo.editing = ""
                            release()
                            editLoader.active = false
                        }
                        onAccepted: finish(true)
                        onEscaped: finish(false)
                        input.onActiveFocusChanged: if (!input.activeFocus && editLoader.active) finish(true)
                    }
                }
                // Due chip: click to change the date.
                Rectangle {
                    id: due
                    visible: !!row.modelData.dueText && todo.editing !== row.modelData.id
                    anchors.right: tools.visible ? tools.left : parent.right
                    anchors.rightMargin: 4
                    anchors.verticalCenter: parent.verticalCenter
                    width: dueText.implicitWidth + 12
                    height: 18
                    radius: 9
                    color: row.modelData.overdue ? Qt.rgba(Theme.danger.r, Theme.danger.g, Theme.danger.b, 0.16)
                         : dueMouse.containsMouse ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.18)
                         : (Theme.dark ? Qt.rgba(1, 1, 1, 0.07) : Qt.rgba(0, 0, 0, 0.05))
                    Text {
                        id: dueText
                        anchors.centerIn: parent
                        text: row.modelData.dueText || ""
                        color: row.modelData.overdue ? Theme.danger : Theme.textDim
                        font.family: Theme.fontFamily
                        font.pixelSize: 10
                    }
                    MouseArea {
                        id: dueMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: todo.pickDate(row.modelData)
                    }
                }
                Row {
                    id: tools
                    visible: row.hot && todo.editing !== row.modelData.id
                    anchors.right: parent.right
                    anchors.rightMargin: 2
                    anchors.verticalCenter: parent.verticalCenter
                    IconButton {
                        visible: !row.modelData.dueText && !row.modelData.done
                        size: 24
                        iconSize: 13
                        icon: "calendar"
                        tip: "设置日期与提醒"
                        color: Theme.textDim
                        onClicked: todo.pickDate(row.modelData)
                    }
                    IconButton {
                        size: 24
                        iconSize: 13
                        icon: "x"
                        tip: "删除"
                        color: Theme.textDim
                        onClicked: todo.leave(row.modelData.id, "remove")
                    }
                }
            }
        }
        displaced: Transition {
            NumberAnimation { properties: "y"; duration: Theme.ms(180); easing.type: Easing.OutCubic }
        }
    }

    // Empty state.
    Column {
        visible: todo.items.length === 0
        anchors.centerIn: list
        spacing: 6
        Glyph {
            anchors.horizontalCenter: parent.horizontalCenter
            name: "circle-check"
            size: 28
            color: Theme.textFaint
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: todo.doneCount > 0 ? "全部完成" : "今天没有待办"
            color: Theme.textFaint
            font.family: Theme.fontFamily
            font.pixelSize: 12
        }
    }

    // Add field ------------------------------------------------------------------------------------------
    GTextField {
        id: adder
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.leftMargin: 12
        anchors.rightMargin: 12
        anchors.bottomMargin: 12
        height: 34
        icon: "plus"
        fontSize: 13
        placeholder: "添加待办，可写 “@明天 18:00”"
        monitorKey: todo.island ? todo.island.monitorKey : ""
        onAccepted: {
            if (text.trim() !== "") {
                Todo.add(todo.uid, text)
                text = ""
            }
        }
        onEscaped: {
            text = ""
            release()
        }
    }

    // Date sheet (calendar + reminder time) --------------------------------------------------------------
    Item {
        id: sheet
        property bool open: false
        property string itemId: ""
        property string itemText: ""
        property bool hadDue: false
        property string date: ""
        property string time: ""
        property date anchor: new Date()
        readonly property var times: ["", "09:00", "12:00", "18:00", "21:00"]
        function apply() {
            var d = date
            if (d === "" && time !== "") {
                d = Qt.formatDate(new Date(), "yyyy-MM-dd")
            }
            if (d !== "") {
                Todo.setDue(todo.uid, itemId, time !== "" ? d + "T" + time : d)
            }
            open = false
        }
        anchors.fill: parent
        z: 20
        visible: opacity > 0.01
        opacity: open ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: Theme.ms(160) } }
        MouseArea {
            // Modal inside the widget: eat clicks, wheel and drags.
            anchors.fill: parent
            acceptedButtons: Qt.AllButtons
            onWheel: (wheel) => wheel.accepted = true
        }
        Rectangle {
            anchors.fill: parent
            radius: todo.island ? todo.island.radius : 14
            color: Theme.dark ? Qt.rgba(0.10, 0.11, 0.13, 1) : Qt.rgba(0.97, 0.97, 0.98, 1)
        }
        Flickable {
            anchors.fill: parent
            anchors.margins: 12
            contentHeight: sheetCol.implicitHeight
            interactive: contentHeight > height
            boundsBehavior: Flickable.StopAtBounds
            clip: true
            Column {
                id: sheetCol
                width: parent.width
                spacing: 8
                Item {
                    width: parent.width
                    height: 24
                    Text {
                        anchors.left: parent.left
                        anchors.right: closeBtn.left
                        anchors.rightMargin: 6
                        anchors.verticalCenter: parent.verticalCenter
                        text: "日期与提醒 · " + sheet.itemText
                        elide: Text.ElideRight
                        color: Theme.text
                        font.family: Theme.fontFamily
                        font.pixelSize: 13
                        font.weight: Font.DemiBold
                    }
                    IconButton {
                        id: closeBtn
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        size: 24
                        iconSize: 13
                        icon: "x"
                        tip: "取消"
                        onClicked: sheet.open = false
                    }
                }
                MonthCalendar {
                    id: sheetCal
                    width: parent.width
                    height: implicitHeight
                    minCellH: 22
                    divider: false
                    pickable: true
                    showLunar: false
                    anchorDate: sheet.anchor
                    selected: sheet.date
                    marks: Todo.dueMap
                    onPicked: (date) => sheet.date = date
                }
                Flow {
                    width: parent.width
                    spacing: 5
                    Repeater {
                        model: sheet.times
                        delegate: Rectangle {
                            required property string modelData
                            readonly property bool on: sheet.time === modelData
                            width: chip.implicitWidth + 14
                            height: 24
                            radius: 12
                            color: on ? Theme.accent : (chipMouse.containsMouse ? Theme.hover
                                   : (Theme.dark ? Qt.rgba(1, 1, 1, 0.07) : Qt.rgba(0, 0, 0, 0.05)))
                            Text {
                                id: chip
                                anchors.centerIn: parent
                                text: modelData === "" ? "全天" : modelData
                                color: parent.on ? Theme.onAccent : Theme.text
                                font.family: Theme.fontFamily
                                font.pixelSize: 11
                            }
                            MouseArea {
                                id: chipMouse
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: sheet.time = modelData
                            }
                            Tip {
                                text: modelData === "" ? "不设具体时间：当天 9:00 提醒" : "当天 " + modelData + " 提醒"
                                shown: chipMouse.containsMouse
                            }
                        }
                    }
                }
                Item {
                    width: parent.width
                    height: 30
                    GButton {
                        anchors.left: parent.left
                        anchors.verticalCenter: parent.verticalCenter
                        visible: sheet.hadDue
                        text: "清除日期"
                        kind: "ghost"
                        compact: true
                        onClicked: {
                            Todo.setDue(todo.uid, sheet.itemId, "")
                            sheet.open = false
                        }
                    }
                    Row {
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 6
                        GButton {
                            text: "取消"
                            kind: "ghost"
                            compact: true
                            onClicked: sheet.open = false
                        }
                        GButton {
                            text: "确定"
                            kind: "accent"
                            compact: true
                            onClicked: sheet.apply()
                        }
                    }
                }
            }
        }
    }
}
