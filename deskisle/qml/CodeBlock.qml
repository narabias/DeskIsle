// Monospace snippet with a copy button (settings: MCP configuration, CLI examples).
import QtQuick

Rectangle {
    id: root
    property string code: ""
    property string copyNote: "已复制到剪贴板"
    readonly property string mono: {
        var wanted = ["Cascadia Mono", "Cascadia Code", "Consolas", "JetBrains Mono", "Menlo",
                      "DejaVu Sans Mono", "Liberation Mono", "Courier New"]
        var have = Qt.fontFamilies()
        for (var i = 0; i < wanted.length; ++i) {
            if (have.indexOf(wanted[i]) >= 0) {
                return wanted[i]
            }
        }
        return "monospace"
    }
    width: parent ? parent.width : 400
    implicitHeight: edit.implicitHeight + 26
    height: implicitHeight
    radius: 10
    color: Theme.dark ? Qt.rgba(0, 0, 0, 0.30) : Qt.rgba(0, 0, 0, 0.045)
    border.width: 1
    border.color: Theme.hairline

    TextEdit {
        id: edit
        x: 14
        y: 13
        width: parent.width - 28 - copy.width
        text: root.code
        readOnly: true
        selectByMouse: true
        wrapMode: TextEdit.WrapAnywhere
        color: Theme.text
        selectionColor: Theme.accent
        selectedTextColor: Theme.onAccent
        font.family: root.mono
        font.pixelSize: 13
    }
    IconButton {
        id: copy
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 6
        icon: "copy"
        tip: "复制"
        size: 30
        iconSize: 16
        color: Theme.textDim
        onClicked: Desk.copyText(root.code, root.copyNote)
    }
}
