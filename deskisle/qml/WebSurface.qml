// Page area of a web island or an HTML widget.
// Native pages: a WebView2 child window (the usual case - native input, drawn
// above the Qt content of its area) or a composition visual.  This item reports
// the page's window geometry; a composition page *below* the Qt scene also
// needs the island glass to punch a hole and gets its pointer input forwarded
// from here.  A page drawn above Qt is hidden while its island is dragged or
// resized (a child window lags behind the Qt frame and would jitter).
// Non-Windows development builds use QtWebEngine ("qml" mode); without any
// engine a placeholder card offers the system browser instead.
import QtQuick

Item {
    id: surface
    property var island: null
    property real cornerRadius: 12
    readonly property var view: island ? island.webView : null
    readonly property string mode: view ? view.modeName : "pending"
    readonly property bool nativePage: !!view && view.native
    readonly property bool holePage: !!view && view.hole
    readonly property bool pageAbove: !!view && view.above
    readonly property var win: Window.window
    readonly property bool shownState: visible && width > 4 && height > 4 && !!island && island.visible
                                       && !island.capsuled && !island.collapsed && !island.deskHidden
                                       && island.opacity > 0.6
                                       && !(pageAbove && (island.dragging || island.resizing))
    property var last: []

    function attachNow() {
        if (!view || !win) {
            return
        }
        view.attach(win)
        last = []
        sync()
        view.setShown(shownState)
    }
    function sync() {
        if (!view || !win) {
            return
        }
        var p0 = surface.mapToItem(null, 0, 0)
        var p1 = surface.mapToItem(null, width, height)
        var g = [Math.round(p0.x), Math.round(p0.y), Math.round(p1.x - p0.x), Math.round(p1.y - p0.y), cornerRadius]
        if (last.length !== 5 || g[0] !== last[0] || g[1] !== last[1] || g[2] !== last[2] || g[3] !== last[3]
                || g[4] !== last[4]) {
            last = g
            view.setGeometry(g[0], g[1], g[2], g[3], g[4])
        }
        if (island) {
            var q = surface.mapToItem(island, 0, 0)
            var hole = holePage && shownState ? Qt.rect(q.x, q.y, width, height) : Qt.rect(0, 0, 0, 0)
            if (hole.x !== island.webHole.x || hole.y !== island.webHole.y || hole.width !== island.webHole.width
                    || hole.height !== island.webHole.height) {
                island.webHole = hole
            }
        }
    }

    // A child timer instead of Qt.callLater: it dies with the surface, so a deleted
    // island never runs a queued attach on a half-destroyed object.
    Timer {
        id: attachTimer
        interval: 0
        onTriggered: surface.attachNow()
    }
    Component.onCompleted: attachTimer.restart()
    Component.onDestruction: {
        attachTimer.stop()
        if (view) {
            view.detach()
        }
    }
    onWinChanged: attachTimer.restart()
    onViewChanged: attachTimer.restart()
    onShownStateChanged: {
        if (view) {
            view.setShown(shownState)
        }
        sync()
    }
    onNativePageChanged: sync()
    onHolePageChanged: sync()
    // Windowed page clicked: let the layer window take the keyboard, then give the focus back
    // to the page (activating the window focuses the Qt window itself).
    Connections {
        target: surface.view
        function onPageFocused() {
            if (surface.mode !== "windowed" || Desk.keyboard) {
                return
            }
            Desk.closePanel()
            Desk.wantKeyboard(true, surface.island ? surface.island.monitorKey : "")
            refocus.restart()
        }
    }
    Timer {
        id: refocus
        interval: 40
        onTriggered: if (surface.view) surface.view.focusPage()
    }
    onModeChanged: sync()
    onWidthChanged: sync()
    onHeightChanged: sync()
    onXChanged: sync()
    onYChanged: sync()
    Connections {
        target: surface.island
        function onXChanged() { surface.sync() }
        function onYChanged() { surface.sync() }
        function onWidthChanged() { surface.sync() }
        function onHeightChanged() { surface.sync() }
        function onScaleChanged() { surface.sync() }
    }
    Timer {
        // Safety net for layout changes of intermediate parents (toolbar, grip...).
        interval: 400
        repeat: true
        running: surface.shownState && surface.nativePage
        onTriggered: surface.sync()
    }

    // Composition mode: pointer input goes to the page through the host.
    MouseArea {
        id: input
        anchors.fill: parent
        enabled: surface.mode === "composition"
        visible: enabled
        hoverEnabled: true
        preventStealing: true
        acceptedButtons: Qt.AllButtons
        cursorShape: surface.view ? surface.view.cursor : Qt.ArrowCursor
        function send(kind, mouse, button, delta) {
            surface.view.mouse(kind, mouse.x, mouse.y, button, mouse.buttons, mouse.modifiers, delta)
        }
        onPressed: (mouse) => {
            Desk.closePanel()
            Desk.wantKeyboard(true, surface.island ? surface.island.monitorKey : "")
            surface.view.focusPage()
            send("press", mouse, mouse.button, 0)
        }
        onReleased: (mouse) => send("release", mouse, mouse.button, 0)
        onPositionChanged: (mouse) => send("move", mouse, 0, 0)
        onExited: surface.view.mouse("leave", 0, 0, 0, 0, 0, 0)
        onWheel: (wheel) => {
            if (wheel.angleDelta.y !== 0) {
                surface.view.mouse("wheel", wheel.x, wheel.y, 0, wheel.buttons, wheel.modifiers, wheel.angleDelta.y)
            }
            if (wheel.angleDelta.x !== 0) {
                surface.view.mouse("hwheel", wheel.x, wheel.y, 0, wheel.buttons, wheel.modifiers, -wheel.angleDelta.x)
            }
        }
    }

    // Development engine (QtWebEngine) ----------------------------------------------------------------
    Loader {
        id: engine
        anchors.fill: parent
        active: surface.mode === "qml"
        source: "WebEngineSurface.qml"
        onLoaded: {
            item.view = Qt.binding(function() { return surface.view })
            item.island = surface.island
        }
    }

    // Pending: the engine is starting.
    Column {
        anchors.centerIn: parent
        spacing: 10
        visible: surface.mode === "pending"
        Glyph {
            id: spinner
            anchors.horizontalCenter: parent.horizontalCenter
            name: "refresh"
            size: 22
            color: Theme.textDim
            RotationAnimation on rotation {
                running: spinner.visible && Theme.ms(1000) > 0
                from: 0
                to: 360
                duration: 1000
                loops: Animation.Infinite
            }
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: "正在启动网页引擎…"
            color: Theme.textDim
            font.family: Theme.fontFamily
            font.pixelSize: 12
        }
    }

    // Placeholder: no engine here (or it failed) - offer the browser.
    Rectangle {
        anchors.centerIn: parent
        visible: surface.mode === "placeholder"
        width: Math.min(parent.width - 24, 340)
        height: card.implicitHeight + 32
        radius: Theme.smallRadius + 4
        color: Theme.dark ? Qt.rgba(1, 1, 1, 0.05) : Qt.rgba(0, 0, 0, 0.035)
        border.width: 1
        border.color: Theme.hairline
        Column {
            id: card
            anchors.centerIn: parent
            width: parent.width - 32
            spacing: 10
            Glyph {
                anchors.horizontalCenter: parent.horizontalCenter
                name: "world"
                size: 26
                color: Theme.accent
            }
            Text {
                width: parent.width
                text: surface.view ? surface.view.messageText : ""
                color: Theme.textDim
                font.family: Theme.fontFamily
                font.pixelSize: 12
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                lineHeight: 1.15
            }
            Flow {
                anchors.horizontalCenter: parent.horizontalCenter
                width: Math.min(parent.width, implicitWidth)
                spacing: 8
                GButton {
                    text: "用浏览器打开"
                    icon: "external-link"
                    kind: "tonal"
                    compact: true
                    onClicked: surface.view.openExternal()
                }
                GButton {
                    visible: !!surface.view && surface.view.linkUrl !== ""
                    text: "获取 WebView2"
                    icon: "download"
                    kind: "ghost"
                    compact: true
                    onClicked: Qt.openUrlExternally(surface.view.linkUrl)
                }
                GButton {
                    text: "重试"
                    icon: "refresh"
                    kind: "ghost"
                    compact: true
                    onClicked: surface.view.retry()
                }
            }
        }
    }
}
