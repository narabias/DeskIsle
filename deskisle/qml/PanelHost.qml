// Drop-down panel of the dynamic bar: "new" / "new:web" (NewPanel), "presets",
// "search" and "media".  It lives in its own window (PopupWindow.qml,
// `standalone`), opened under the bar or at the top of another monitor when
// started from that monitor's desktop menu.  Non-modal: the desktop and the
// islands stay usable; Esc, the bar button, a click on the desktop or
// finishing the action closes it.  Drag the card background to move it.
import QtQuick

Item {
    id: host
    property var deskLayer: null
    property var wall: null
    property bool standalone: false        // in PopupWindow: the card sits at (0, 0)
    readonly property string key: deskLayer ? deskLayer.key : ""
    readonly property string kind: standalone ? Desk.panel : (deskLayer && deskLayer.panelHere ? Desk.panel : "")
    readonly property bool open: kind !== ""
    property string shown: ""
    readonly property bool wanted: shown !== ""
    width: standalone ? card.width : implicitWidth
    height: standalone ? card.height : implicitHeight
    readonly property var sources: ({
        "new": "NewPanel.qml", "new:web": "NewPanel.qml", "presets": "PresetsPanel.qml",
        "search": "SearchPanel.qml", "media": "MediaPanel.qml"
    })

    onKindChanged: {
        if (kind !== "") {
            unload.stop()
            shown = kind
        } else {
            unload.restart()
        }
    }
    Component.onCompleted: if (kind !== "") shown = kind
    Timer {
        id: unload
        interval: Theme.ms(240) + 40
        onTriggered: if (!host.open) host.shown = ""
    }

    Item {
        id: card
        readonly property real cw: content.item ? content.item.implicitWidth : 360
        readonly property real ch: content.item ? content.item.implicitHeight : 120
        width: Math.min(cw, host.deskLayer ? host.deskLayer.work.w - 32 : cw)
        height: Math.min(ch, host.deskLayer ? host.deskLayer.work.h - (host.deskLayer.panelTop - host.deskLayer.work.y) - 24 : ch)
        x: host.standalone || !host.deskLayer ? 0 : Math.round(host.deskLayer.work.x + (host.deskLayer.work.w - width) / 2)
        y: host.standalone ? 0 : (host.deskLayer ? host.deskLayer.panelTop : 60)
        visible: opacity > 0.01
        opacity: host.open ? 1 : 0
        scale: host.open ? 1 : 0.92
        transformOrigin: Item.Top
        Behavior on opacity { NumberAnimation { duration: Theme.ms(170) } }
        Behavior on scale { NumberAnimation { duration: Theme.ms(260); easing.type: Easing.OutBack; easing.overshoot: 1.2 } }
        // (A window resizes with its card: no size animation there.)
        Behavior on width { enabled: host.open && !host.standalone; NumberAnimation { duration: Theme.ms(220); easing.type: Easing.OutCubic } }
        Behavior on height { enabled: host.open && !host.standalone; NumberAnimation { duration: Theme.ms(220); easing.type: Easing.OutCubic } }

        MouseArea {
            // The card is solid for the mouse; its background moves the window.
            anchors.fill: parent
            acceptedButtons: Qt.AllButtons
            onPressed: (mouse) => {
                if (mouse.button === Qt.LeftButton && Window.window && Window.window.beginMove) {
                    Window.window.beginMove()
                }
            }
            onWheel: (wheel) => wheel.accepted = true
        }
        Glass {
            anchors.fill: parent
            blurSource: host.wall ? host.wall.blurred : null
            sharpSource: host.wall ? host.wall.sharp : null
            solidFallback: host.standalone || !host.wall || !host.wall.ready
            solidAlpha: host.standalone ? 0.95 : -1
            solidShadow: host.standalone
            backdropOrigin: Qt.point(card.x + (host.deskLayer ? host.deskLayer.inset : 0), card.y + (host.deskLayer ? host.deskLayer.inset : 0))
            backdropSize: Qt.size(host.deskLayer && host.deskLayer.scene ? host.deskLayer.scene.monitorWidth : 1920,
                                  host.deskLayer && host.deskLayer.scene ? host.deskLayer.scene.monitorHeight : 1080)
            radius: Theme.radius
            material: "frosted"
            dark: Theme.dark
            strength: Theme.strength
            shadowSize: 22 * Theme.shadow
            elevation: 1.4
        }
        Loader {
            id: content
            anchors.fill: parent
            clip: true
            source: host.shown !== "" ? host.sources[host.shown] : ""
            onLoaded: item.host = host
        }
    }
}
