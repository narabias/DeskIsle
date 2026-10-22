// Horizontal slider.  `moved` fires while dragging, `committed` on release.
import QtQuick

Item {
    id: root
    property real from: 0
    property real to: 1
    property real value: 0
    property real stepSize: 0
    property bool live: false
    property color fill: Theme.accent
    readonly property bool dragging: area.pressed
    property real shown: dragging ? dragValue : value
    property real dragValue: value
    signal moved(real value)
    signal committed(real value)

    implicitWidth: 220
    implicitHeight: 24
    height: implicitHeight
    opacity: enabled ? 1 : 0.4

    function valueAt(px) {
        var t = Math.max(0, Math.min(1, (px - 9) / Math.max(1, width - 18)))
        var v = from + t * (to - from)
        if (stepSize > 0) {
            v = Math.round((v - from) / stepSize) * stepSize + from
        }
        return Math.max(Math.min(from, to), Math.min(Math.max(from, to), v))
    }
    readonly property real ratio: to === from ? 0 : (shown - from) / (to - from)

    Rectangle {
        id: track
        x: 9
        width: parent.width - 18
        height: 4
        radius: 2
        anchors.verticalCenter: parent.verticalCenter
        color: Theme.dark ? Qt.rgba(1, 1, 1, 0.16) : Qt.rgba(0, 0, 0, 0.12)
        Rectangle {
            width: Math.max(0, Math.min(1, root.ratio)) * parent.width
            height: parent.height
            radius: 2
            color: root.fill
        }
    }
    Rectangle {
        width: 18
        height: 18
        radius: 9
        anchors.verticalCenter: parent.verticalCenter
        x: Math.max(0, Math.min(1, root.ratio)) * (root.width - 18)
        color: "#FFFFFF"
        border.width: 1
        border.color: Qt.rgba(0, 0, 0, 0.12)
        scale: area.pressed ? 1.12 : (area.containsMouse ? 1.05 : 1)
        Behavior on scale { NumberAnimation { duration: Theme.ms(100) } }
    }
    MouseArea {
        id: area
        anchors.fill: parent
        anchors.topMargin: -6
        anchors.bottomMargin: -6
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        preventStealing: true
        onPressed: (mouse) => { root.dragValue = root.valueAt(mouse.x); root.moved(root.dragValue) }
        onPositionChanged: (mouse) => {
            if (pressed) {
                root.dragValue = root.valueAt(mouse.x)
                root.moved(root.dragValue)
            }
        }
        onReleased: root.committed(root.dragValue)
        onWheel: (wheel) => {
            var step = root.stepSize > 0 ? root.stepSize : (root.to - root.from) / 20
            var v = Math.max(Math.min(root.from, root.to), Math.min(Math.max(root.from, root.to),
                             root.value + (wheel.angleDelta.y > 0 ? step : -step)))
            root.moved(v)
            root.committed(v)
        }
    }
}
