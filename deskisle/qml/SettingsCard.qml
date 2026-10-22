// Settings section: caption, rounded card with SettingRow children, optional note.
import QtQuick

Column {
    id: root
    property string title: ""
    property string note: ""
    default property alias rows: body.data
    width: parent ? parent.width : 640
    spacing: 8
    // Settings search can land on a whole card (e.g. 归流规则).
    function flash() {
        cardFlash.restart()
    }

    Text {
        visible: root.title !== ""
        leftPadding: 4
        text: root.title
        color: Theme.textDim
        font.family: Theme.fontFamily
        font.pixelSize: 13
        font.weight: Font.DemiBold
    }
    Rectangle {
        width: parent.width
        height: body.implicitHeight + 8
        radius: 14
        color: Theme.dark ? Qt.rgba(1, 1, 1, 0.055) : Qt.rgba(1, 1, 1, 0.72)
        border.width: 1
        border.color: Theme.hairline
        Rectangle {
            id: cardTint
            anchors.fill: parent
            radius: parent.radius
            color: Theme.accentSoft
            opacity: 0
            SequentialAnimation {
                id: cardFlash
                NumberAnimation { target: cardTint; property: "opacity"; to: 1; duration: 160 }
                PauseAnimation { duration: 900 }
                NumberAnimation { target: cardTint; property: "opacity"; to: 0; duration: 900 }
            }
        }
        Column {
            id: body
            y: 4
            width: parent.width
        }
    }
    Text {
        visible: root.note !== ""
        width: parent.width
        leftPadding: 4
        rightPadding: 4
        wrapMode: Text.Wrap
        text: root.note
        color: Theme.textFaint
        font.family: Theme.fontFamily
        font.pixelSize: 12
    }
}
