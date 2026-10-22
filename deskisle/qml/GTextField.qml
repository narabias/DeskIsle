// Single line text field.  Layer windows never take the foreground on their
// own (WS_EX_NOACTIVATE), so the field asks Desk for keyboard focus first;
// popup windows (ownFocus) and the settings window take it themselves.
import QtQuick

Item {
    id: root
    property alias text: input.text
    property alias input: input
    property string placeholder: ""
    property string icon: ""
    property bool layerWindow: !(Window.window && Window.window.ownFocus === true)
    property string monitorKey: ""
    property bool clearButton: true
    property bool selectOnFocus: false
    property real fontSize: 14
    property int maximumLength: 512
    property int lastModifiers: 0          // modifiers of the last Return / Enter press
    signal accepted()
    signal escaped()
    signal edited()
    signal upPressed()
    signal downPressed()
    signal tabPressed()

    implicitHeight: 36
    implicitWidth: 240
    height: implicitHeight

    function focusField() {
        if (root.layerWindow && typeof Desk !== "undefined" && Desk) {
            Desk.wantKeyboard(true, root.monitorKey)
        }
        input.forceActiveFocus()
        if (root.selectOnFocus) {
            input.selectAll()
        }
    }
    function release() {
        input.focus = false
        if (root.layerWindow && typeof Desk !== "undefined" && Desk) {
            Desk.wantKeyboard(false, root.monitorKey)
        }
    }

    Rectangle {
        anchors.fill: parent
        radius: Math.min(height / 2, Theme.smallRadius)
        color: Theme.dark ? Qt.rgba(1, 1, 1, input.activeFocus ? 0.10 : 0.07)
                          : Qt.rgba(0, 0, 0, input.activeFocus ? 0.04 : 0.05)
        border.width: input.activeFocus ? 1.5 : 1
        border.color: input.activeFocus ? Theme.accent : Theme.hairline
        Behavior on border.color { ColorAnimation { duration: Theme.ms(120) } }
    }
    Glyph {
        id: lead
        visible: root.icon !== ""
        anchors.left: parent.left
        anchors.leftMargin: 11
        anchors.verticalCenter: parent.verticalCenter
        name: root.icon
        size: 16
        color: Theme.textDim
    }
    TextInput {
        id: input
        anchors.left: lead.visible ? lead.right : parent.left
        anchors.leftMargin: lead.visible ? 8 : 12
        anchors.right: clear.visible ? clear.left : parent.right
        anchors.rightMargin: clear.visible ? 2 : 12
        anchors.verticalCenter: parent.verticalCenter
        color: Theme.text
        selectionColor: Theme.accent
        selectedTextColor: Theme.onAccent
        font.family: Theme.fontFamily
        font.pixelSize: root.fontSize
        clip: true
        selectByMouse: true
        maximumLength: root.maximumLength
        onAccepted: root.accepted()
        onTextEdited: root.edited()
        Keys.onEscapePressed: (event) => { root.escaped(); event.accepted = true }
        Keys.onReturnPressed: (event) => { root.lastModifiers = event.modifiers; event.accepted = false }
        Keys.onEnterPressed: (event) => { root.lastModifiers = event.modifiers; event.accepted = false }
        Keys.onUpPressed: root.upPressed()
        Keys.onDownPressed: root.downPressed()
        Keys.onTabPressed: (event) => { root.tabPressed(); event.accepted = true }
        onActiveFocusChanged: {
            if (activeFocus && root.layerWindow && typeof Desk !== "undefined" && Desk) {
                Desk.wantKeyboard(true, root.monitorKey)
            }
        }
        Text {
            anchors.fill: parent
            verticalAlignment: Text.AlignVCenter
            text: root.placeholder
            visible: input.text === "" && input.preeditText === ""
            color: Theme.textFaint
            font: input.font
            elide: Text.ElideRight
        }
    }
    MouseArea {
        // Clicking the padding focuses the field too.
        anchors.fill: parent
        z: -1
        onPressed: root.focusField()
    }
    IconButton {
        id: clear
        visible: root.clearButton && input.text !== ""
        anchors.right: parent.right
        anchors.rightMargin: 5
        anchors.verticalCenter: parent.verticalCenter
        size: 24
        iconSize: 14
        icon: "x"
        color: Theme.textDim
        onClicked: { input.clear(); root.edited(); root.focusField() }
    }
}
