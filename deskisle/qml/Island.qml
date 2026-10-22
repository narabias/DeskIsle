// One island: glass card with a header (files / web) or a floating grip
// (widgets), a body, resize edges and the capsule (pill) form.
// Geometry comes from IslandProxy (window-local px); gestures are reported to
// Desk in board coordinates and the arranger moves everything (make-way).
import QtQuick
import QtQuick.Effects

Item {
    id: island
    property var proxy: null
    property var scene: null
    property var wall: null
    property bool standalone: false      // PinnedIsland window (no wallpaper sampling)
    property real standaloneMargin: 0

    readonly property string uid: proxy ? proxy.uid : ""
    readonly property string kind: proxy ? proxy.kind : "files"
    readonly property string monitorKey: scene ? scene.key_ : ""
    readonly property bool collapsed: proxy ? proxy.collapsed : false
    readonly property bool locked: proxy ? proxy.locked : false
    readonly property bool deskHidden: Desk.hidden && !!proxy && !proxy.excludeFromHide
    readonly property bool hovered: hoverWatch.hovered
    // Hover preview of a capsule: expanded in place, purely visual, so the layout keeps the pill
    // positions and nothing below it is pushed away (the real peek used to re-slot the island).
    property bool hoverPeek: false
    readonly property bool capsuled: !!proxy && proxy.capsule && !proxy.peek && !hoverPeek
                                     && !dragging && !resizing && editor === ""
    readonly property bool showHeader: kind !== "widget"
    readonly property real headerH: 44
    readonly property real radius: Math.min(Theme.radius, Math.min(width, height) / 2)
    readonly property var webView: (kind === "web" || isHtmlWidget) && typeof WebHost !== "undefined" && WebHost
                                   ? WebHost.view(uid) : null
    readonly property bool isHtmlWidget: kind === "widget" && !!proxy && proxy.widget.indexOf("custom:") === 0
                                         && typeof Custom !== "undefined" && Custom
                                         && (Custom.revision >= 0) && Custom.widgetInfo(proxy.widget).type === "html"
    property bool dragging: false
    property bool resizing: false
    property string editor: ""           // "" | rename | webUrl | addTab | renameTab:<id>
    property rect webHole: Qt.rect(0, 0, 0, 0)
    property real appear: 1

    z: (proxy ? proxy.z : 0) + (dragging ? 100000 : (hoverPeek ? 60000 : 0))
    visible: !!proxy && (standalone || !proxy.pinned) && opacity > 0.01
    opacity: deskHidden ? 0 : appear
    Behavior on opacity { NumberAnimation { duration: Theme.ms(220); easing.type: Easing.OutCubic } }
    transformOrigin: Item.Top
    scale: deskHidden ? 0.94 : (dragging ? 1.012 : 1)
    Behavior on scale { NumberAnimation { duration: Theme.ms(dragging ? 120 : 200); easing.type: Easing.OutCubic } }

    // Geometry ---------------------------------------------------------------------------------------
    function syncGeometry(animate) {
        if (!proxy) {
            return
        }
        var tx = standalone ? standaloneMargin : proxy.x
        var ty = standalone ? standaloneMargin : proxy.y
        var mode = proxy.motion
        geo.stop()
        if (animate && mode === "slide" && Theme.ms(300) > 0) {
            ax.to = tx; ay.to = ty; aw.to = proxy.width; ah.to = proxy.height
            geo.start()
        } else {
            x = tx; y = ty; width = proxy.width; height = proxy.height
            if (animate && mode === "fade") {
                fadeIn.restart()
            }
        }
    }
    Component.onCompleted: syncGeometry(false)
    onStandaloneMarginChanged: syncGeometry(false)
    Connections {
        target: island.proxy
        function onGeometryChanged() { island.syncGeometry(true) }
        function onFlash(what) { island.flash(what) }
    }
    // A dropped island snaps into its slot quickly; make-way moves of the others stay calmer.
    property bool dropSnap: false
    Timer { id: dropSnapTimer; interval: 450; onTriggered: island.dropSnap = false }
    readonly property int geoMs: Theme.ms(dropSnap ? 170 : 300)
    ParallelAnimation {
        id: geo
        NumberAnimation { id: ax; target: island; property: "x"; duration: island.geoMs; easing.type: Easing.OutCubic }
        NumberAnimation { id: ay; target: island; property: "y"; duration: island.geoMs; easing.type: Easing.OutCubic }
        NumberAnimation { id: aw; target: island; property: "width"; duration: island.geoMs; easing.type: Easing.OutCubic }
        NumberAnimation { id: ah; target: island; property: "height"; duration: island.geoMs; easing.type: Easing.OutCubic }
    }
    SequentialAnimation {
        id: fadeIn
        NumberAnimation { target: island; property: "appear"; to: 0; duration: Theme.ms(90) }
        NumberAnimation { target: island; property: "appear"; to: 1; duration: Theme.ms(260); easing.type: Easing.OutCubic }
    }
    SequentialAnimation {
        id: appearAnim
        ParallelAnimation {
            NumberAnimation { target: island; property: "appear"; from: 0; to: 1; duration: Theme.ms(320); easing.type: Easing.OutCubic }
            NumberAnimation { target: shell; property: "scale"; from: 0.9; to: 1; duration: Theme.ms(420); easing.type: Easing.OutBack; easing.overshoot: 1.3 }
        }
    }

    // Flash: inline editors / highlights requested from menus, search and agents -------------------
    function flash(what) {
        if (what === "appear") {
            appearAnim.restart()
        } else if (what === "rename" || what === "webUrl" || what === "addTab") {
            if (collapsed && what !== "rename") {
                Desk.act(uid, "collapse", { value: false })
            }
            editor = what
        } else if (what === "locate" || what.indexOf("locate:") === 0) {
            pulse.restart()
            if (what.indexOf("locate:") === 0 && bodyLoader.item && bodyLoader.item.reveal) {
                bodyLoader.item.reveal(what.substring(7))
            }
        } else if (what === "reload") {
            if (webView) {
                webView.retry()
            } else if (bodyLoader.item && bodyLoader.item.reload) {
                bodyLoader.item.reload()
            }
        }
    }
    function closeEditor() {
        editor = ""
        Desk.wantKeyboard(false, monitorKey)
    }

    // Gestures ---------------------------------------------------------------------------------------
    property point pressGlobal: Qt.point(0, 0)
    property point pressBoard: Qt.point(0, 0)
    property point pressCursor: Qt.point(0, 0)
    property bool armed: false
    function boardOrigin() {
        // Board position of this island's (0, 0).
        return Qt.point(proxy.x + (scene ? scene.originX : 0), proxy.y + (scene ? scene.originY : 0))
    }
    function movePress(area, mouse) {
        var g = area.mapToGlobal(mouse.x, mouse.y)
        var local = area.mapToItem(island, mouse.x, mouse.y)
        pressGlobal = Qt.point(g.x, g.y)
        pressBoard = boardOrigin()
        pressCursor = Qt.point(pressBoard.x + local.x, pressBoard.y + local.y)
        armed = true
        Desk.act(uid, "raise", {})
        Desk.closePanel()
    }
    function moveDrag(area, mouse) {
        if (!armed) {
            return
        }
        var g = area.mapToGlobal(mouse.x, mouse.y)
        var dx = g.x - pressGlobal.x
        var dy = g.y - pressGlobal.y
        if (!dragging) {
            if (Math.abs(dx) + Math.abs(dy) < 4 || locked) {
                return
            }
            dragging = true
            Desk.dragBegin(uid)
        }
        Desk.dragMove(uid, pressBoard.x + dx, pressBoard.y + dy, pressCursor.x + dx, pressCursor.y + dy)
    }
    function moveRelease() {
        armed = false
        if (dragging) {
            dropSnap = true
            dropSnapTimer.restart()
            dragging = false
            Desk.dragEnd(uid)
        }
    }
    function openMenu(area, mouse) {
        if (area && mouse) {
            var g = area.mapToGlobal(mouse.x, mouse.y)
            App.popupMenuAt("island", uid, {}, Math.round(g.x), Math.round(g.y))
        } else {
            App.popupMenu("island", uid, {})
        }
    }
    function openMenuBelow(item) {
        var g = item.mapToGlobal(0, item.height + 4)
        App.popupMenuAt("island", uid, {}, Math.round(g.x), Math.round(g.y))
    }

    // Shell (glass + content) -------------------------------------------------------------------------
    readonly property real pillH: 38
    readonly property real pillW: Math.min(width, pillRow.implicitWidth + 30)
    Item {
        id: shell
        width: island.capsuled ? island.pillW : island.width
        height: island.capsuled ? island.pillH : island.height
        Behavior on width { enabled: morph.running; NumberAnimation { duration: Theme.ms(260); easing.type: Easing.OutCubic } }
        Behavior on height { enabled: morph.running; NumberAnimation { duration: Theme.ms(260); easing.type: Easing.OutCubic } }
        Timer { id: morph; interval: 300 }
        Connections {
            target: island
            function onCapsuledChanged() { morph.restart() }
        }

        // Hovering the pill opens the preview after 胶囊悬停预览; leaving collapses it again.
        HoverHandler {
            id: hoverWatch
            onHoveredChanged: {
                if (!island.proxy || !island.proxy.capsule) {
                    peekTimer.stop()
                    island.hoverPeek = false
                } else if (hovered) {
                    peekTimer.restart()
                } else {
                    peekTimer.stop()
                    island.hoverPeek = false
                }
            }
        }
        Timer {
            id: peekTimer
            readonly property int delay: Number(Desk.prefs.capsule_peek_ms) || 0
            interval: Math.max(1, delay)
            onTriggered: {
                if (delay > 0 && hoverWatch.hovered && island.proxy && island.proxy.capsule) {
                    island.hoverPeek = true
                }
            }
        }

        Glass {
            id: glass
            anchors.fill: parent
            blurSource: island.wall ? island.wall.blurred : null
            sharpSource: island.wall ? island.wall.sharp : null
            solidFallback: island.standalone || !island.wall || !island.wall.ready
            backdropOrigin: Qt.point(island.x + (island.scene ? island.scene.inset : 0),
                                     island.y + (island.scene ? island.scene.inset : 0))
            backdropSize: Qt.size(island.scene ? island.scene.monitorWidth : 1920,
                                  island.scene ? island.scene.monitorHeight : 1080)
            radius: island.capsuled ? island.pillH / 2 : island.radius
            material: island.proxy ? island.proxy.material : "frosted"
            dark: Theme.dark
            strength: Theme.strength
            shadowSize: 16 * Theme.shadow
            elevation: island.dragging ? 1.7 : (island.hovered ? 1.15 : 1.0)
            hover: island.hovered ? 1 : 0
            Behavior on hover { NumberAnimation { duration: Theme.ms(180) } }
            hole: island.capsuled ? Qt.rect(0, 0, 0, 0) : island.webHole
            holeRadius: 12
            tint: Theme.accent
            tintStrength: island.proxy && island.proxy.hint === "swap" ? 0.22 : 0
        }

        // Background media (image / GIF / video) with feathered edges.
        Loader {
            anchors.fill: parent
            active: !!island.proxy && island.proxy.mediaPath !== "" && !island.capsuled
            visible: active
            source: "IslandMedia.qml"
            onLoaded: {
                item.island = island
            }
        }

        Item {
            id: content
            anchors.fill: parent
            visible: opacity > 0.01
            opacity: island.capsuled ? 0 : 1
            Behavior on opacity { NumberAnimation { duration: Theme.ms(160) } }
            clip: island.capsuled || morph.running

            // Widgets have no header: wherever the widget itself does not take the mouse, a
            // right click opens the island menu (delete, size...) and a left drag moves it.
            MouseArea {
                id: widgetCatch
                anchors.fill: parent
                enabled: island.kind === "widget" && !island.capsuled
                acceptedButtons: Qt.LeftButton | Qt.RightButton
                onPressed: (mouse) => { if (mouse.button === Qt.LeftButton) island.movePress(widgetCatch, mouse) }
                onPositionChanged: (mouse) => island.moveDrag(widgetCatch, mouse)
                onReleased: island.moveRelease()
                onCanceled: island.moveRelease()
                onClicked: (mouse) => { if (mouse.button === Qt.RightButton) island.openMenu(widgetCatch, mouse) }
            }

            IslandHeader {
                id: header
                visible: island.showHeader
                island: island
                width: parent.width
                height: island.headerH
            }

            Loader {
                id: bodyLoader
                anchors.fill: parent
                anchors.topMargin: island.showHeader ? island.headerH : 0
                active: !island.collapsed || !island.showHeader
                visible: !island.collapsed && !(island.kind === "widget" && island.height < 120)
                opacity: island.collapsed ? 0 : 1
                Behavior on opacity { NumberAnimation { duration: Theme.ms(160) } }
                source: island.kind === "web" ? "WebBody.qml"
                      : island.kind === "widget" ? "WidgetBody.qml" : "FilesBody.qml"
                onLoaded: item.island = island
            }

            // Folded widgets have no header: show a compact, always-visible summary instead of an
            // empty glass bar (weather / now playing / todo).
            Loader {
                anchors.fill: parent
                active: island.kind === "widget" && !island.capsuled && (island.collapsed || island.height < 120)
                visible: active
                source: "CollapsedSummary.qml"
                onLoaded: item.island = island
            }

            WidgetGrip {
                visible: island.kind === "widget"
                island: island
                width: parent.width
            }
        }

        // Capsule (pill) face.
        Item {
            id: pill
            anchors.fill: parent
            visible: opacity > 0.01
            opacity: island.capsuled ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: Theme.ms(160) } }
            Row {
                id: pillRow
                anchors.left: parent.left
                anchors.leftMargin: 15
                anchors.verticalCenter: parent.verticalCenter
                spacing: 8
                Glyph {
                    anchors.verticalCenter: parent.verticalCenter
                    name: header.kindIcon
                    size: 16
                    color: Theme.accent
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: island.proxy ? island.proxy.title : ""
                    color: Theme.text
                    font.family: Theme.fontFamily
                    font.pixelSize: 13
                    font.weight: Font.DemiBold
                    elide: Text.ElideRight
                    width: Math.min(implicitWidth, Math.max(40, island.width - 70))
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    visible: text !== ""
                    text: header.countText
                    color: Theme.textFaint
                    font.family: Theme.fontFamily
                    font.pixelSize: 12
                }
            }
            MouseArea {
                anchors.fill: parent
                enabled: island.capsuled
                acceptedButtons: Qt.LeftButton | Qt.RightButton
                cursorShape: Qt.PointingHandCursor
                onPressed: (mouse) => { if (mouse.button === Qt.LeftButton) island.movePress(this, mouse) }
                onPositionChanged: (mouse) => island.moveDrag(this, mouse)
                onReleased: island.moveRelease()
                onCanceled: island.moveRelease()
                onClicked: (mouse) => {
                    if (mouse.button === Qt.RightButton) {
                        island.openMenu(this, mouse)
                    }
                }
                onDoubleClicked: Desk.act(island.uid, "capsule", { value: false })
            }
        }

        // Swap / make-way hints and the locate pulse.
        Rectangle {
            anchors.fill: parent
            radius: glass.radius
            color: "transparent"
            border.width: 2
            border.color: Theme.accent
            opacity: island.proxy && island.proxy.hint === "swap" ? 0.9 : 0
            Behavior on opacity { NumberAnimation { duration: Theme.ms(140) } }
            Rectangle {
                anchors.centerIn: parent
                visible: parent.opacity > 0.5
                width: swapText.implicitWidth + 26
                height: 30
                radius: 15
                color: Theme.accent
                Text {
                    id: swapText
                    anchors.centerIn: parent
                    text: "停留片刻即可交换位置"
                    color: Theme.onAccent
                    font.family: Theme.fontFamily
                    font.pixelSize: 12
                    font.weight: Font.DemiBold
                }
            }
        }
        Canvas {
            id: hatch
            anchors.fill: parent
            visible: opacity > 0.01
            opacity: island.proxy && island.proxy.hint === "hatch" ? 0.55 : 0
            Behavior on opacity { NumberAnimation { duration: Theme.ms(140) } }
            property color ink: Theme.dark ? Qt.rgba(1, 1, 1, 0.22) : Qt.rgba(0, 0, 0, 0.16)
            onInkChanged: requestPaint()
            onWidthChanged: requestPaint()
            onHeightChanged: requestPaint()
            onPaint: {
                var ctx = getContext("2d")
                ctx.reset()
                var r = glass.radius
                ctx.beginPath()
                ctx.roundedRect(0, 0, width, height, r, r)
                ctx.clip()
                ctx.strokeStyle = ink
                ctx.lineWidth = 2
                for (var i = -height; i < width; i += 12) {
                    ctx.beginPath()
                    ctx.moveTo(i, height)
                    ctx.lineTo(i + height, 0)
                    ctx.stroke()
                }
            }
        }
        Rectangle {
            id: pulseRing
            anchors.fill: parent
            anchors.margins: -4
            radius: glass.radius + 4
            color: "transparent"
            border.width: 3
            border.color: Theme.accent
            opacity: 0
            SequentialAnimation {
                id: pulse
                loops: 3
                NumberAnimation { target: pulseRing; property: "opacity"; to: 1; duration: Theme.ms(180) }
                NumberAnimation { target: pulseRing; property: "opacity"; to: 0; duration: Theme.ms(420) }
            }
        }
    }

    // Resize edges ------------------------------------------------------------------------------------
    property point resizeGlobal: Qt.point(0, 0)
    function resizePress(area, mouse, edge) {
        var g = area.mapToGlobal(mouse.x, mouse.y)
        resizeGlobal = Qt.point(g.x, g.y)
        resizing = true
        Desk.act(uid, "raise", {})
        Desk.resizeBegin(uid, edge)
    }
    function resizeDrag(area, mouse) {
        if (!resizing) {
            return
        }
        var g = area.mapToGlobal(mouse.x, mouse.y)
        Desk.resizeMove(uid, g.x - resizeGlobal.x, g.y - resizeGlobal.y)
    }
    function resizeRelease() {
        if (resizing) {
            resizing = false
            Desk.resizeEnd(uid)
        }
    }
    Repeater {
        model: island.locked || island.capsuled || !island.proxy ? [] : (island.collapsed ? ["left", "right"]
               : ["left", "right", "bottom", "bottom-left", "bottom-right"])
        delegate: MouseArea {
            required property string modelData
            readonly property bool l: modelData.indexOf("left") >= 0
            readonly property bool r: modelData.indexOf("right") >= 0
            readonly property bool b: modelData.indexOf("bottom") >= 0
            x: l ? -5 : (r ? island.width - 7 : 14)
            y: b ? island.height - 7 : 16
            width: l || r ? 12 : island.width - 28
            height: b ? 12 : island.height - 30
            z: 50
            hoverEnabled: true
            preventStealing: true
            cursorShape: (l && b) ? Qt.SizeBDiagCursor : (r && b) ? Qt.SizeFDiagCursor
                         : (l || r) ? Qt.SizeHorCursor : Qt.SizeVerCursor
            onPressed: (mouse) => island.resizePress(this, mouse, modelData)
            onPositionChanged: (mouse) => island.resizeDrag(this, mouse)
            onReleased: island.resizeRelease()
            onCanceled: island.resizeRelease()
        }
    }
}
