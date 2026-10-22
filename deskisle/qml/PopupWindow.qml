// Bar panels, confirmation cards and notices live in their own top-level
// windows (App creates one per role on first use): they stay above every
// island - web pages and pinned islands included - and can be dragged by
// their background.  The window is sized to the card plus a margin for the
// shadow; it hides (and frees its graphics resources) after the card faded out.
import QtQuick
import QtQuick.Window

Window {
    id: win
    property string role: "panel"            // panel | confirm | notice
    // GTextField: text fields here take the keyboard with the window itself.
    readonly property bool ownFocus: role !== "notice"
    readonly property var deskLayer: (App.layersRevision, App.layerWindow(role === "panel" ? Desk.panelMonitor : ""))
    readonly property int margin: 44
    readonly property var card: loader.item
    // A confirmation asked while the settings window is in front shows there instead (its sheet).
    readonly property bool wanted: !!card && card.wanted && !(role === "confirm" && App.settingsActive)
    readonly property bool agentRequest: role === "confirm" && Desk.confirmInfo.source === "agent"
    property bool moved: false               // dragged by the user: keep its place until it closes

    flags: Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint | Qt.NoDropShadowWindowHint
           | (role === "notice" ? Qt.WindowDoesNotAcceptFocus : 0)
    color: "transparent"
    title: role === "panel" ? "桌屿面板" : role === "confirm" ? "桌屿确认" : "桌屿通知"
    width: 200
    height: 120

    // Where the card is about: the island whose title appears in the confirm title.
    // Returns a rect in global screen coordinates plus the work area to clamp into, or null.
    function confirmAnchor() {
        var info = Desk.confirmInfo
        if (!info || !info.id) {
            return null
        }
        var title = String(info.title || "")
        if (title.indexOf("预设") >= 0) {
            return null            // a preset, not an island: keep the card under the bar
        }
        var m = title.match(/[“"「『]([^”"」』]+)[”"」』]/)
        if (!m) {
            return null
        }
        // The confirmation usually opens on the primary layer; info.monitor tells us the island's
        // own monitor so the card can be placed next to it even on a secondary screen.
        var layer = null
        var mk = String(info.monitor || "")
        if (mk !== "" && App.layerWindow) {
            layer = App.layerWindow(mk)
        }
        if (!layer || !layer.islandByTitle || !layer.islandByTitle(m[1])) {
            layer = win.deskLayer
        }
        if (!layer || !layer.islandByTitle || !layer.work) {
            return null
        }
        var island = layer.islandByTitle(m[1])
        if (!island) {
            return null
        }
        return { x: layer.x + island.x, y: layer.y + island.y, w: island.width, h: island.height,
                 work: { x: layer.x + layer.work.x, y: layer.y + layer.work.y,
                         w: layer.work.w, h: layer.work.h } }
    }

    function place() {
        var layer = win.deskLayer
        if (!layer || !card) {
            return
        }
        var cw = Math.ceil(card.width), ch = Math.ceil(card.height)
        var w = cw + 2 * margin, h = ch + 2 * margin
        var x = win.x, y = win.y
        if (!moved || !visible) {
            var work = layer.work
            var anchor = role === "confirm" ? confirmAnchor() : null
            if (role === "notice") {
                x = layer.x + work.x + work.w - cw - 18 - margin
                y = layer.y + work.y + work.h - ch - 18 - margin
            } else if (anchor && anchor.work) {
                // Right under the island it is about (above when there is no room below, beside
                // it when neither fits), always inside the work area.  Everything is global here:
                // the island may sit on another monitor than this popup's layer.
                var aw = anchor.work
                var ax = anchor.x + (anchor.w - cw) / 2
                var ay = anchor.y + anchor.h + 12
                if (ay + ch > aw.y + aw.h - 8) {
                    ay = anchor.y - ch - 12
                }
                if (ay < aw.y + 8) {
                    ay = anchor.y
                    ax = anchor.x + anchor.w + 12
                    if (ax + cw > aw.x + aw.w - 8) {
                        ax = anchor.x - cw - 12
                    }
                }
                x = Math.max(aw.x + 8, Math.min(ax, aw.x + aw.w - cw - 8)) - margin
                y = Math.max(aw.y + 8, Math.min(ay, aw.y + aw.h - ch - 8)) - margin
            } else {
                x = layer.x + work.x + (work.w - cw) / 2 - margin
                y = layer.y + layer.panelTop + (role === "confirm" ? 6 : 0) - margin
            }
        } else if (role === "notice") {
            y = win.y + win.height - h       // grows upwards from where it was put
        }
        App.placeWindow(win, Math.round(x), Math.round(y), w, h)
        // The margin around the card is there for the shadow, not for the mouse: left
        // unclipped it swallows clicks aimed at the bar, which sits in that margin.
        App.clipWindowToCard(win, win.margin, win.margin, cw, ch, Theme.radius)
    }
    function openWindow() {
        hideTimer.stop()
        if (!visible) {
            moved = false
        }
        place()
        if (!visible) {
            show()
        }
        raise()
        if (ownFocus && !agentRequest) {
            App.activateWindow(win)
        }
    }
    // Card backgrounds call this on a left press.
    function beginMove() {
        if (startSystemMove()) {
            moved = true
        }
    }

    onWantedChanged: wanted ? openWindow() : hideTimer.restart()
    onDeskLayerChanged: {
        moved = false
        if (visible) {
            place()
        }
    }
    Component.onCompleted: if (wanted) openWindow()
    Timer {
        id: hideTimer
        interval: Theme.ms(260) + 80
        onTriggered: {
            if (!win.wanted) {
                win.hide()
                win.releaseResources()
            }
        }
    }
    Connections {
        target: win.card
        function onWidthChanged() { if (win.visible) win.place() }
        function onHeightChanged() { if (win.visible) win.place() }
    }

    Item {
        id: keys
        anchors.fill: parent
        focus: true
        Keys.onPressed: (event) => {
            if (event.key === Qt.Key_Escape) {
                if (win.role === "panel") {
                    Desk.closePanel()
                } else if (win.role === "confirm" && Desk.confirmInfo.id) {
                    Desk.resolveConfirm(Desk.confirmInfo.id, false)
                }
                event.accepted = true
            }
        }
        Loader {
            id: loader
            x: win.margin
            y: win.margin
            sourceComponent: win.role === "panel" ? panelCard : win.role === "confirm" ? confirmCard : noticeCard
        }
    }
    Component {
        id: panelCard
        PanelHost {
            standalone: true
            deskLayer: win.deskLayer
        }
    }
    Component {
        id: confirmCard
        ConfirmCard {
            standalone: true
            deskLayer: win.deskLayer
        }
    }
    Component {
        id: noticeCard
        NoticeStack {
            standalone: true
            deskLayer: win.deskLayer
        }
    }
}
