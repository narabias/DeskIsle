// Small tooltip bubble.  It lives in the window's content item so clipped
// parents (island bodies, lists) never cut it off.
import QtQuick

Item {
    id: root
    property string text: ""
    property bool shown: false
    property Item anchorItem: parent
    property int delay: 600
    width: 0
    height: 0

    onShownChanged: {
        if (shown && text !== "") {
            timer.restart()
        } else {
            timer.stop()
            bubble.open = false
        }
    }
    Timer {
        id: timer
        interval: root.delay
        onTriggered: bubble.place()
    }

    Rectangle {
        id: bubble
        property bool open: false
        parent: root.Window.contentItem ? root.Window.contentItem : root
        z: 100000
        visible: opacity > 0.01
        opacity: open ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: Theme.ms(120) } }
        width: label.implicitWidth + 18
        height: label.implicitHeight + 10
        radius: 8
        color: Theme.dark ? Qt.rgba(0.10, 0.11, 0.13, 0.96) : Qt.rgba(0.99, 0.99, 1.0, 0.97)
        border.width: 1
        border.color: Theme.hairline

        function place() {
            if (!root.anchorItem || !parent || !root.shown) {
                return
            }
            var p = root.anchorItem.mapToItem(parent, root.anchorItem.width / 2, 0)
            var below = root.anchorItem.mapToItem(parent, 0, root.anchorItem.height).y
            var nx = Math.round(p.x - width / 2)
            var ny = Math.round(p.y - height - 6)
            if (ny < 4) {
                ny = Math.round(below + 6)
            }
            x = Math.max(4, Math.min(parent.width - width - 4, nx))
            y = ny
            open = true
        }

        Text {
            id: label
            anchors.centerIn: parent
            text: root.text
            color: Theme.text
            font.family: Theme.fontFamily
            font.pixelSize: 12
        }
    }
}
