// Text (+ optional icon) button.  kind: accent | tonal | ghost | danger
import QtQuick

Item {
    id: root
    property string text: ""
    property string icon: ""
    property string kind: "tonal"
    property string tip: ""
    property bool compact: false
    readonly property bool hovered: area.containsMouse
    signal clicked()

    implicitHeight: compact ? 28 : 34
    implicitWidth: row.implicitWidth + (compact ? 22 : 30)
    height: implicitHeight
    width: implicitWidth
    opacity: enabled ? 1 : 0.4

    readonly property color base: kind === "accent" ? Theme.accent
                                : kind === "danger" ? Theme.danger
                                : kind === "ghost" ? "transparent"
                                : (Theme.dark ? Qt.rgba(1, 1, 1, 0.10) : Qt.rgba(0, 0, 0, 0.06))
    readonly property color fg: kind === "accent" ? Theme.onAccent
                              : kind === "danger" ? "#FFFFFF" : Theme.text

    Rectangle {
        anchors.fill: parent
        radius: height / 2
        color: root.base
        Rectangle {
            anchors.fill: parent
            radius: parent.radius
            color: root.kind === "accent" || root.kind === "danger"
                   ? Qt.rgba(1, 1, 1, area.pressed ? 0.10 : (area.containsMouse ? 0.16 : 0))
                   : (area.pressed ? Theme.pressed : (area.containsMouse ? Theme.hover : "transparent"))
            Behavior on color { ColorAnimation { duration: Theme.ms(110) } }
        }
        border.width: root.kind === "tonal" ? 1 : 0
        border.color: Theme.hairline
    }
    Row {
        id: row
        anchors.centerIn: parent
        spacing: 7
        Glyph {
            visible: root.icon !== ""
            anchors.verticalCenter: parent.verticalCenter
            name: root.icon
            size: root.compact ? 14 : 16
            color: root.fg
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: root.text
            visible: text !== ""
            color: root.fg
            font.family: Theme.fontFamily
            font.pixelSize: root.compact ? 12 : 13
            font.weight: root.kind === "accent" ? Font.DemiBold : Font.Medium
        }
    }
    scale: area.pressed ? 0.97 : 1
    Behavior on scale { NumberAnimation { duration: Theme.ms(90) } }
    MouseArea {
        id: area
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.clicked()
    }
    Tip {
        text: root.tip
        shown: area.containsMouse
    }
}
