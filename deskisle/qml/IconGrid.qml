// Icon collection shared by file islands (GridView: scrolls, shows a drop gap)
// and the loose desktop icons ("free" mode: positions px/py come from the
// engine's column-major desktop layout).  One overlay MouseArea handles hover,
// selection (click, Ctrl, Shift, rubber band), native drag-out
// (Desk.startDrag -> other islands, the desktop or Explorer), double-click,
// context menus, wheel scrolling and Ctrl+wheel icon size.
import QtQuick

Item {
    id: root
    property var island: null              // Island.qml; null on the desktop
    property var model: null               // ItemsModel
    property string container: ""          // "island:<uid>:<tab>" | "loose"
    property bool free: false              // desktop mode (absolute positions)
    property bool portal: false            // folder view: drops move files into the folder
    property bool onDesktop: free
    property bool acceptDrops: true
    property string emptyText: ""
    property string emptyIcon: "folder"
    property int iconSize: model ? model.iconSize : 48
    readonly property int cellW: iconSize + 44
    readonly property int cellH: iconSize + (iconSize <= 32 ? 34 : 50)
    readonly property int columns: Math.max(1, Math.floor((width - 8) / cellW))
    readonly property int count: model ? model.count : 0
    readonly property string mime: "application/x-deskisle-items"
    property bool dragging: false          // our own drag is running (QDrag.exec)
    readonly property bool dropHover: dropArea.containsDrag
    readonly property alias view: grid
    signal activated(string path)
    signal blankMenu(real gx, real gy)
    signal blankDoubleClicked(real gx, real gy)
    signal blankPressed()

    // Helpers ----------------------------------------------------------------------------------------
    function reveal(path) {
        if (!model) {
            return
        }
        var row = model.rowOf(path)
        if (row < 0) {
            return
        }
        model.select(row, false, false)
        if (!free) {
            grid.positionViewAtIndex(row, GridView.Contain)
        }
    }
    function itemAt(row) {
        return free ? rep.itemAt(row) : grid.itemAtIndex(row)
    }
    function rowTotal() {
        return free ? rep.count : grid.count
    }
    function rowAt(x, y) {
        if (!model) {
            return -1
        }
        if (free) {
            for (var i = rep.count - 1; i >= 0; i--) {
                var it = rep.itemAt(i)
                if (it && !it.placeholder && x >= it.x + 4 && x <= it.x + it.width - 4
                        && y >= it.y && y <= it.y + Math.max(it.height, it.plateBottom)) {
                    return i
                }
            }
            return -1
        }
        var p = root.mapToItem(grid.contentItem, x, y)
        if (p.x < 0 || p.x >= grid.width) {
            return -1
        }
        var row = grid.indexAt(p.x, p.y)
        return row >= 0 && model.pathAt(row) !== "" ? row : -1
    }
    function cellRect(i) {
        if (free) {
            var it = rep.itemAt(i)
            return it ? Qt.rect(it.x, it.y, it.width, it.height) : Qt.rect(-1000, -1000, 0, 0)
        }
        var col = i % columns
        var r = Math.floor(i / columns)
        var p = grid.contentItem.mapToItem(root, col * cellW, r * cellH)
        return Qt.rect(p.x, p.y, cellW, cellH)
    }
    function rowsIn(r) {
        var rows = []
        var n = rowTotal()
        for (var i = 0; i < n; i++) {
            var c = cellRect(i)
            var cx = c.x + 10, cy = c.y + 4, cw = c.width - 20, ch = c.height - 8
            if (cx < r.x + r.width && cx + cw > r.x && cy < r.y + r.height && cy + ch > r.y) {
                rows.push(i)
            }
        }
        return rows
    }
    function selectedRows() {
        var rows = []
        var n = rowTotal()
        for (var i = 0; i < n; i++) {
            if (model.isSelected(i)) {
                rows.push(i)
            }
        }
        return rows
    }
    function gridDropIndex(x, y) {
        var p = root.mapToItem(grid.contentItem, x, y)
        var col = Math.max(0, Math.min(columns - 1, Math.floor(p.x / cellW)))
        var r = Math.max(0, Math.floor(p.y / cellH))
        var row = r * columns + col
        if (p.x - col * cellW > cellW / 2) {
            row += 1
        }
        row = Math.max(0, Math.min(grid.count, row))
        return model.realIndex(row)
    }
    function freeDropIndex(x, y) {
        // Nearest loose icon: drop before it (above) or after it (below) - column-major order.
        var best = -1
        var bestD = 1e9
        for (var i = 0; i < rep.count; i++) {
            var it = rep.itemAt(i)
            if (!it) {
                continue
            }
            var d = Math.abs(it.x + it.width / 2 - x) + Math.abs(it.y + it.height / 2 - y)
            if (d < bestD) {
                bestD = d
                best = i
            }
        }
        if (best < 0 || bestD > cellW * 1.4) {
            return { index: -1, item: null, after: false }
        }
        var b = rep.itemAt(best)
        var after = y > b.y + b.height / 2
        return { index: after ? best + 1 : best, item: b, after: after }
    }
    function pickAction(drag, ours) {
        var want = ours ? Qt.MoveAction : (portal ? Qt.CopyAction : Qt.LinkAction)
        if (drag.supportedActions & want) {
            return want
        }
        return drag.proposedAction
    }

    // Empty state ------------------------------------------------------------------------------------
    Column {
        anchors.centerIn: parent
        spacing: 8
        visible: !root.free && root.count === 0 && root.emptyText !== "" && !dropArea.containsDrag
        opacity: 0.85
        Glyph {
            anchors.horizontalCenter: parent.horizontalCenter
            name: root.emptyIcon
            size: 26
            stroke: 1.4
            color: Theme.textFaint
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            width: Math.min(implicitWidth, root.width - 24)
            text: root.emptyText
            color: Theme.textFaint
            font.family: Theme.fontFamily
            font.pixelSize: 12
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap
        }
    }

    // Grid mode --------------------------------------------------------------------------------------
    GridView {
        id: grid
        visible: !root.free
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.topMargin: 4
        anchors.bottomMargin: 2
        anchors.horizontalCenter: parent.horizontalCenter
        width: root.columns * root.cellW
        cellWidth: root.cellW
        cellHeight: root.cellH
        model: root.free ? null : root.model
        clip: true
        interactive: false
        boundsBehavior: Flickable.StopAtBounds
        cacheBuffer: 240
        add: Transition {
            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.ms(180) }
            NumberAnimation { property: "scale"; from: 0.7; to: 1; duration: Theme.ms(220); easing.type: Easing.OutBack }
        }
        displaced: Transition {
            NumberAnimation { properties: "x,y"; duration: Theme.ms(220); easing.type: Easing.OutCubic }
            NumberAnimation { properties: "opacity,scale"; to: 1; duration: Theme.ms(120) }
        }
        move: Transition {
            NumberAnimation { properties: "x,y"; duration: Theme.ms(240); easing.type: Easing.OutCubic }
        }
        delegate: IconTile {
            required property int index
            required path
            required name
            required icon
            required isDir
            required available
            required pinned
            required selected
            required placeholder
            required match
            width: root.cellW
            height: root.cellH
            iconSize: root.iconSize
            onDesktop: root.onDesktop
            hovered: overlay.hoverIndex === index && !root.dragging
            dimmed: root.dragging && selected
            z: hovered || selected ? 2 : 1
        }
        NumberAnimation {
            id: scrollAnim
            target: grid
            property: "contentY"
            duration: Theme.ms(160)
            easing.type: Easing.OutCubic
        }
    }

    // Scroll indicator.
    Rectangle {
        visible: !root.free && grid.contentHeight > grid.height + 2
        anchors.right: parent.right
        anchors.rightMargin: 3
        y: grid.y + grid.visibleArea.yPosition * grid.height
        width: 4
        height: Math.max(24, grid.visibleArea.heightRatio * grid.height)
        radius: 2
        color: Theme.textFaint
        opacity: overlay.containsMouse || scrollAnim.running ? 0.7 : 0.25
        Behavior on opacity { NumberAnimation { duration: Theme.ms(200) } }
    }

    // Free (desktop) mode ------------------------------------------------------------------------------
    Item {
        id: freeLayer
        anchors.fill: parent
        visible: root.free
        Repeater {
            id: rep
            model: root.free ? root.model : null
            delegate: IconTile {
                id: looseTile
                required property int index
                required property real px
                required property real py
                required path
                required name
                required icon
                required isDir
                required available
                required pinned
                required selected
                required placeholder
                required match
                visible: !placeholder
                x: px
                y: py
                width: root.cellW
                height: root.cellH
                iconSize: root.iconSize
                onDesktop: root.onDesktop
                hovered: overlay.hoverIndex === index && !root.dragging
                dimmed: root.dragging && selected
                z: hovered || selected ? 2 : 1
                Behavior on x { NumberAnimation { duration: Theme.ms(260); easing.type: Easing.OutCubic } }
                Behavior on y { NumberAnimation { duration: Theme.ms(260); easing.type: Easing.OutCubic } }
            }
        }
        // Insertion marker for drops between loose icons.
        Rectangle {
            id: freeMarker
            visible: false
            width: 4
            height: root.cellH - 16
            radius: 2
            color: Theme.accent
        }
    }

    // Rubber band.
    Rectangle {
        visible: overlay.banding && (overlay.band.width > 3 || overlay.band.height > 3)
        x: overlay.band.x
        y: overlay.band.y
        width: overlay.band.width
        height: overlay.band.height
        radius: 4
        color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.16)
        border.width: 1
        border.color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.75)
        z: 10
    }

    // Interaction --------------------------------------------------------------------------------------
    MouseArea {
        id: overlay
        anchors.fill: parent
        z: 5
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        hoverEnabled: true
        property int hoverIndex: -1
        property int pressIndex: -1
        property point pressPos: Qt.point(0, 0)
        property bool deferSelect: false
        property bool dragArmed: false
        property bool banding: false
        property rect band: Qt.rect(0, 0, 0, 0)
        property var bandBase: []

        function reset() {
            pressIndex = -1
            deferSelect = false
            dragArmed = false
            banding = false
        }
        function startDrag() {
            var paths = root.model.dragPaths(pressIndex)
            reset()
            if (paths.length === 0) {
                return
            }
            hoverIndex = -1
            root.dragging = true
            Desk.startDrag(root.container, paths, root.iconSize)     // nested loop until the drop
            root.dragging = false
            // QDrag took the mouse grab: toggling enabled makes the area forget the press.
            overlay.enabled = false
            overlay.enabled = true
        }

        onPressed: (mouse) => {
            if (Desk.panel !== "") {
                Desk.closePanel()
            }
            if (!root.model) {
                return
            }
            var i = root.rowAt(mouse.x, mouse.y)
            pressPos = Qt.point(mouse.x, mouse.y)
            pressIndex = i
            deferSelect = false
            dragArmed = false
            if (mouse.button === Qt.RightButton) {
                if (i >= 0 && !root.model.isSelected(i)) {
                    root.model.select(i, false, false)
                }
                return
            }
            var ctrl = (mouse.modifiers & Qt.ControlModifier) !== 0
            var shift = (mouse.modifiers & Qt.ShiftModifier) !== 0
            if (i >= 0) {
                if (ctrl) {
                    root.model.select(i, true, false)
                } else if (shift) {
                    root.model.select(i, false, true)
                } else if (root.model.isSelected(i) && root.model.selectedCount > 1) {
                    deferSelect = true
                } else {
                    root.model.select(i, false, false)
                }
                dragArmed = root.model.isSelected(i)
            } else {
                root.blankPressed()
                if (!ctrl) {
                    root.model.clearSelection()
                }
                bandBase = ctrl ? root.selectedRows() : []
                band = Qt.rect(mouse.x, mouse.y, 0, 0)
                banding = true
            }
        }
        onPositionChanged: (mouse) => {
            if (!pressed) {
                hoverIndex = root.rowAt(mouse.x, mouse.y)
                return
            }
            if (dragArmed && pressIndex >= 0) {
                if (Math.abs(mouse.x - pressPos.x) + Math.abs(mouse.y - pressPos.y) > 6) {
                    startDrag()
                }
                return
            }
            if (banding) {
                var x0 = Math.min(pressPos.x, mouse.x)
                var y0 = Math.min(pressPos.y, mouse.y)
                band = Qt.rect(x0, y0, Math.abs(mouse.x - pressPos.x), Math.abs(mouse.y - pressPos.y))
                var rows = root.rowsIn(band)
                for (var k = 0; k < bandBase.length; k++) {
                    if (rows.indexOf(bandBase[k]) < 0) {
                        rows.push(bandBase[k])
                    }
                }
                root.model.selectRows(rows)
            }
        }
        onReleased: (mouse) => {
            if (deferSelect && pressIndex >= 0) {
                root.model.select(pressIndex, false, false)
            }
            reset()
        }
        onCanceled: reset()
        onExited: hoverIndex = -1
        onClicked: (mouse) => {
            if (mouse.button !== Qt.RightButton || !root.model) {
                return
            }
            var g = mapToGlobal(mouse.x, mouse.y)
            var i = root.rowAt(mouse.x, mouse.y)
            if (i >= 0) {
                var it = root.itemAt(i)
                App.popupMenuAt("item", root.container,
                                { paths: root.model.selectedPaths(), available: it ? it.available : true },
                                Math.round(g.x), Math.round(g.y))
            } else {
                root.blankMenu(Math.round(g.x), Math.round(g.y))
            }
        }
        onDoubleClicked: (mouse) => {
            if (mouse.button !== Qt.LeftButton || !root.model) {
                return
            }
            var i = root.rowAt(mouse.x, mouse.y)
            if (i >= 0) {
                root.activated(root.model.pathAt(i))
            } else {
                var g = mapToGlobal(mouse.x, mouse.y)
                root.blankDoubleClicked(Math.round(g.x), Math.round(g.y))
            }
        }
        onWheel: (wheel) => {
            if ((wheel.modifiers & Qt.ControlModifier) && root.island) {
                Desk.act(root.island.uid, "iconSize", { delta: wheel.angleDelta.y })
                return
            }
            if (root.free) {
                wheel.accepted = false
                return
            }
            var minY = grid.originY
            var maxY = grid.originY + Math.max(0, grid.contentHeight - grid.height)
            var step = wheel.pixelDelta.y !== 0 ? wheel.pixelDelta.y : wheel.angleDelta.y / 120 * root.cellH
            var base = scrollAnim.running ? scrollAnim.to : grid.contentY
            var target = Math.max(minY, Math.min(maxY, base - step))
            if (Math.abs(target - grid.contentY) < 0.5 && !scrollAnim.running) {
                wheel.accepted = false
                return
            }
            scrollAnim.stop()
            scrollAnim.to = target
            scrollAnim.start()
        }
    }

    // Drops ------------------------------------------------------------------------------------------
    DropArea {
        id: dropArea
        anchors.fill: parent
        enabled: root.acceptDrops && !!root.model
        property int incoming: 1
        property bool ours: false
        property int scrollDir: 0

        function update(x, y) {
            if (root.free) {
                var hit = root.freeDropIndex(x, y)
                if (hit.item) {
                    freeMarker.x = hit.item.x + (hit.after ? hit.item.width / 2 - 20 : hit.item.width / 2 - 20)
                    freeMarker.y = hit.after ? hit.item.y + hit.item.height - 3 : hit.item.y - 3
                    freeMarker.width = 40
                    freeMarker.height = 4
                    freeMarker.visible = true
                } else {
                    freeMarker.visible = false
                }
                return
            }
            if (!root.portal) {
                root.model.setGap(root.gridDropIndex(x, y), Math.min(incoming, 3))
            }
            scrollDir = y < 30 ? -1 : (y > height - 30 ? 1 : 0)
        }
        onEntered: (drag) => {
            var hasOurs = drag.formats.indexOf(root.mime) >= 0
            if (!hasOurs && !drag.hasUrls) {
                drag.accepted = false
                return
            }
            ours = hasOurs
            incoming = 1
            if (hasOurs) {
                try {
                    incoming = Math.max(1, JSON.parse(drag.getDataAsString(root.mime)).paths.length)
                } catch (e) {
                    incoming = 1
                }
            } else if (drag.urls) {
                incoming = Math.max(1, drag.urls.length)
            }
            drag.accept(root.pickAction(drag, hasOurs))
            update(drag.x, drag.y)
        }
        onPositionChanged: (drag) => {
            drag.accept(root.pickAction(drag, ours))
            update(drag.x, drag.y)
        }
        onExited: {
            scrollDir = 0
            freeMarker.visible = false
            if (root.model) {
                root.model.clearGap()
            }
        }
        onDropped: (drop) => {
            scrollDir = 0
            freeMarker.visible = false
            var text = drop.formats.indexOf(root.mime) >= 0 ? drop.getDataAsString(root.mime) : ""
            var urls = []
            if (text === "" && drop.hasUrls) {
                for (var i = 0; i < drop.urls.length; i++) {
                    urls.push(drop.urls[i].toString())
                }
            }
            var index = -1
            if (root.free) {
                index = root.freeDropIndex(drop.x, drop.y).index
            } else if (!root.portal) {
                index = root.model.gapIndex()
                if (index < 0) {
                    index = root.gridDropIndex(drop.x, drop.y)
                }
            }
            root.model.clearGap()
            if (Desk.dropItems(root.container, index, text, urls)) {
                drop.accept(root.pickAction(drop, text !== ""))
            } else {
                drop.accepted = false
            }
        }
        Timer {
            interval: 30
            repeat: true
            running: dropArea.containsDrag && dropArea.scrollDir !== 0 && !root.free
            onTriggered: {
                var minY = grid.originY
                var maxY = grid.originY + Math.max(0, grid.contentHeight - grid.height)
                grid.contentY = Math.max(minY, Math.min(maxY, grid.contentY + dropArea.scrollDir * 10))
            }
        }
    }

    // Drop feedback: glow border + a hint pill.
    Rectangle {
        visible: dropArea.containsDrag && !root.free
        anchors.fill: parent
        anchors.margins: 3
        radius: Theme.smallRadius + 2
        color: "transparent"
        border.width: 2
        border.color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.55)
        z: 8
    }
    Rectangle {
        visible: dropArea.containsDrag && !root.free && (root.portal || !dropArea.ours)
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 10
        width: hintText.implicitWidth + 24
        height: 26
        radius: 13
        color: Theme.accent
        z: 9
        Text {
            id: hintText
            anchors.centerIn: parent
            text: root.portal ? "移入此文件夹" : "添加到此岛（不移动原文件）"
            color: Theme.onAccent
            font.family: Theme.fontFamily
            font.pixelSize: 12
            font.weight: Font.DemiBold
        }
    }
}
