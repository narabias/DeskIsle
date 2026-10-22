// Floating handle for widget islands (which have no header).  It is a slim grabber on the top
// edge - no title pill, no buttons - so it never covers the widget's own header (city / update
// time / refresh) or the compact summary's text and controls.  Right click anywhere on the
// widget opens the island menu; double click the grabber renames it.
import QtQuick

Item {
    id: grip
    property var island: null
    height: 30
    readonly property bool shown: island && (island.hovered || island.dragging) && !island.capsuled
    opacity: shown ? 1 : 0
    visible: opacity > 0.01
    Behavior on opacity { NumberAnimation { duration: Theme.ms(160) } }

    Rectangle {
        id: handle
        anchors.horizontalCenter: parent.horizontalCenter
        y: 3
        width: 34
        height: 5
        radius: 2.5
        color: Theme.dark ? Qt.rgba(1, 1, 1, 0.55) : Qt.rgba(0, 0, 0, 0.32)
        MouseArea {
            id: area
            anchors.fill: parent
            anchors.margins: -9
            acceptedButtons: Qt.LeftButton | Qt.RightButton
            cursorShape: Qt.SizeAllCursor
            onPressed: (mouse) => { if (mouse.button === Qt.LeftButton) island.movePress(area, mouse) }
            onPositionChanged: (mouse) => island.moveDrag(area, mouse)
            onReleased: island.moveRelease()
            onCanceled: island.moveRelease()
            onClicked: (mouse) => { if (mouse.button === Qt.RightButton) island.openMenu(area, mouse) }
            onDoubleClicked: island.editor = "rename"
        }
    }
    // Rename editor for widgets (they have no header).
    Loader {
        anchors.horizontalCenter: parent.horizontalCenter
        y: 4
        width: Math.min(220, grip.width - 60)
        height: 28
        active: island && island.editor === "rename"
        visible: active
        sourceComponent: GTextField {
            text: island.proxy ? island.proxy.title : ""
            placeholder: "小组件名称"
            fontSize: 12
            selectOnFocus: true
            monitorKey: island.monitorKey
            height: 28
            onAccepted: {
                var t = text.trim()
                if (t !== "") Desk.act(island.uid, "rename", { title: t })
                island.closeEditor()
            }
            onEscaped: island.closeEditor()
            Component.onCompleted: focusField()
            Connections {
                target: input
                function onActiveFocusChanged() {
                    if (!input.activeFocus && island.editor === "rename") island.closeEditor()
                }
            }
        }
    }
}
