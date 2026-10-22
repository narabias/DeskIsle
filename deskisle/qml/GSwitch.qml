// On/off switch.  Controlled: emits toggled(newValue); the owner updates `checked`.
import QtQuick

Item {
    id: root
    property bool checked: false
    signal toggled(bool value)
    implicitWidth: 42
    implicitHeight: 24
    width: implicitWidth
    height: implicitHeight
    opacity: enabled ? 1 : 0.4

    Rectangle {
        anchors.fill: parent
        radius: height / 2
        color: root.checked ? Theme.accent : (Theme.dark ? Qt.rgba(1, 1, 1, 0.16) : Qt.rgba(0, 0, 0, 0.14))
        Behavior on color { ColorAnimation { duration: Theme.ms(160) } }
        Rectangle {
            id: knob
            width: 18
            height: 18
            radius: 9
            y: 3
            x: root.checked ? parent.width - width - 3 : 3
            color: root.checked ? Theme.onAccent : (Theme.dark ? "#E9EDF2" : "#FFFFFF")
            Behavior on x { NumberAnimation { duration: Theme.ms(180); easing.type: Easing.OutCubic } }
            scale: area.pressed ? 0.9 : 1
            Behavior on scale { NumberAnimation { duration: Theme.ms(90) } }
        }
    }
    MouseArea {
        id: area
        anchors.fill: parent
        anchors.margins: -4
        cursorShape: Qt.PointingHandCursor
        onClicked: root.toggled(!root.checked)
    }
}
