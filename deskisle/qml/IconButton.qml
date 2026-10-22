// Round icon-only button with hover state and tooltip.
import QtQuick

Item {
    id: root
    property string icon: ""
    property string tip: ""
    property real size: 30
    property real iconSize: 17
    property bool checked: false
    property bool danger: false
    property bool filled: false
    property bool flat: false
    property color color: danger ? Theme.danger : (checked ? Theme.accent : Theme.text)
    property color hoverColor: Theme.hover
    readonly property bool hovered: area.containsMouse
    readonly property bool down: area.pressed
    signal clicked(var mouse)

    width: size
    height: size
    opacity: enabled ? 1 : 0.38

    Rectangle {
        anchors.fill: parent
        radius: height / 2
        color: area.pressed ? Theme.pressed
             : (area.containsMouse ? root.hoverColor
             : (root.checked && !root.flat ? Theme.accentSoft : "transparent"))
        Behavior on color { ColorAnimation { duration: Theme.ms(110) } }
    }
    Glyph {
        anchors.centerIn: parent
        name: root.icon
        size: root.iconSize
        color: root.color
        filled: root.filled
        scale: area.pressed ? 0.9 : 1
        Behavior on scale { NumberAnimation { duration: Theme.ms(90) } }
    }
    MouseArea {
        id: area
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: (mouse) => root.clicked(mouse)
    }
    Tip {
        text: root.tip
        shown: area.containsMouse && !area.pressed
    }
}
