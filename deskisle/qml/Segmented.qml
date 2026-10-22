// Segmented control: options = [{value, text, icon?}], emits picked(value).
import QtQuick

Item {
    id: root
    property var options: []
    property var current
    property bool compact: false
    signal picked(var value)

    implicitHeight: compact ? 28 : 32
    implicitWidth: row.implicitWidth + 6
    height: implicitHeight
    width: implicitWidth
    opacity: enabled ? 1 : 0.4

    readonly property int currentIndex: {
        for (var i = 0; i < options.length; ++i) {
            if (options[i].value === current) {
                return i
            }
        }
        return -1
    }

    Rectangle {
        anchors.fill: parent
        radius: height / 2
        color: Theme.dark ? Qt.rgba(1, 1, 1, 0.08) : Qt.rgba(0, 0, 0, 0.05)
        border.width: 1
        border.color: Theme.hairline
    }
    Rectangle {
        id: thumb
        // rep.count: re-evaluate once the delegates exist (itemAt() is not notifiable).
        readonly property Item target: root.currentIndex >= 0 && rep.count > root.currentIndex
                                       ? rep.itemAt(root.currentIndex) : null
        visible: target !== null
        x: target ? target.x + 3 : 3
        width: target ? target.width : 0
        y: 3
        height: root.height - 6
        radius: height / 2
        color: Theme.accent
        Behavior on x { NumberAnimation { duration: Theme.ms(200); easing.type: Easing.OutCubic } }
        Behavior on width { NumberAnimation { duration: Theme.ms(200); easing.type: Easing.OutCubic } }
    }
    Row {
        id: row
        x: 3
        y: 3
        height: root.height - 6
        Repeater {
            id: rep
            model: root.options
            delegate: Item {
                required property var modelData
                required property int index
                readonly property bool on: index === root.currentIndex
                height: row.height
                width: inner.implicitWidth + (root.compact ? 18 : 24)
                Row {
                    id: inner
                    anchors.centerIn: parent
                    spacing: 5
                    Glyph {
                        visible: !!modelData.icon
                        name: modelData.icon || ""
                        size: 14
                        anchors.verticalCenter: parent.verticalCenter
                        color: on ? Theme.onAccent : Theme.text
                    }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: modelData.text
                        color: on ? Theme.onAccent : Theme.text
                        font.family: Theme.fontFamily
                        font.pixelSize: root.compact ? 12 : 13
                        font.weight: on ? Font.DemiBold : Font.Normal
                    }
                }
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: if (!on) root.picked(modelData.value)
                }
            }
        }
    }
}
