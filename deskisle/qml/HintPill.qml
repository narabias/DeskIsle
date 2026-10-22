// Small floating pill (focus layer, clean desk feedback) with an optional action.
import QtQuick
import QtQuick.Effects

Item {
    id: root
    property bool shown: false
    property string icon: ""
    property string text: ""
    property string action: ""
    signal triggered()

    width: row.implicitWidth + 28
    height: 36
    visible: opacity > 0.01
    opacity: shown ? 1 : 0
    Behavior on opacity { NumberAnimation { duration: Theme.ms(200) } }
    transform: Translate {
        y: root.shown ? 0 : 12
        Behavior on y { NumberAnimation { duration: Theme.ms(260); easing.type: Easing.OutCubic } }
    }

    RectangularShadow {
        anchors.fill: bg
        radius: bg.radius
        blur: 18
        offset.y: 4
        color: Qt.rgba(0, 0, 0, 0.35)
    }
    Rectangle {
        id: bg
        anchors.fill: parent
        radius: height / 2
        color: "#E6101114"
        border.width: 1
        border.color: Qt.rgba(1, 1, 1, 0.08)
    }
    Row {
        id: row
        anchors.centerIn: parent
        spacing: 9
        Glyph {
            anchors.verticalCenter: parent.verticalCenter
            visible: root.icon !== ""
            name: root.icon
            size: 16
            color: "#F3F4F6"
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: root.text
            color: "#F3F4F6"
            font.family: Theme.fontFamily
            font.pixelSize: 13
        }
        Rectangle {
            anchors.verticalCenter: parent.verticalCenter
            visible: root.action !== ""
            width: actText.implicitWidth + 18
            height: 24
            radius: 12
            color: actArea.containsMouse ? Qt.lighter(Theme.accent, 1.12) : Theme.accent
            Text {
                id: actText
                anchors.centerIn: parent
                text: root.action
                color: Theme.onAccent
                font.family: Theme.fontFamily
                font.pixelSize: 12
                font.weight: Font.DemiBold
            }
            MouseArea {
                id: actArea
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.triggered()
            }
        }
    }
}
