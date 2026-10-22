// Presets ("预设"): every preset is an independent island layout of this
// monitor.  Click to switch, double-click (or menu → 重命名) to rename inline,
// right-click for duplicate / delete.  Presets shown on another monitor are
// marked with that monitor's name.
import QtQuick

Item {
    id: panel
    property var host: null
    readonly property string key: host ? host.key : ""
    readonly property var scene: host && host.deskLayer ? host.deskLayer.scene : null
    readonly property var pages: scene ? scene.pages : []
    property string editing: ""
    implicitWidth: 560
    implicitHeight: col.implicitHeight + 36

    function checkArg() {
        var arg = Desk.panelArg
        if (arg.indexOf("rename:") === 0) {
            editing = arg.substring(7)
        }
    }
    Component.onCompleted: checkArg()
    Connections {
        target: Desk
        function onPanelChanged() { panel.checkArg() }
    }
    function run(action, args) {
        var a = args || {}
        a.monitor = key
        Desk.action(action, a)
    }

    Column {
        id: col
        x: 18
        y: 18
        width: parent.width - 36
        spacing: 14

        Row {
            spacing: 8
            Glyph { name: "layout-board"; size: 18; color: Theme.accent; anchors.verticalCenter: parent.verticalCenter }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: "预设"
                color: Theme.text
                font.family: Theme.fontFamily
                font.pixelSize: 16
                font.weight: Font.Bold
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: "每个预设是一套独立的岛屿布局"
                color: Theme.textDim
                font.family: Theme.fontFamily
                font.pixelSize: 12
            }
        }

        Flow {
            width: parent.width
            spacing: 10
            Repeater {
                model: panel.pages
                delegate: Item {
                    id: card
                    required property var modelData
                    readonly property bool current: modelData.current
                    readonly property bool editingThis: panel.editing === modelData.id
                    width: 164
                    height: 78
                    Rectangle {
                        anchors.fill: parent
                        radius: Theme.smallRadius
                        color: card.current ? Theme.accentSoft
                               : (area.containsMouse ? Theme.hover : (Theme.dark ? Qt.rgba(1, 1, 1, 0.05) : Qt.rgba(0, 0, 0, 0.035)))
                        border.width: card.current ? 1.5 : 1
                        border.color: card.current ? Theme.accent : Theme.hairline
                        Behavior on color { ColorAnimation { duration: Theme.ms(110) } }
                    }
                    MouseArea {
                        id: area
                        anchors.fill: parent
                        hoverEnabled: true
                        acceptedButtons: Qt.LeftButton | Qt.RightButton
                        cursorShape: Qt.PointingHandCursor
                        onClicked: (mouse) => {
                            if (mouse.button === Qt.RightButton) {
                                var g = mapToGlobal(mouse.x, mouse.y)
                                App.popupMenuAt("preset", card.modelData.id, { monitor: panel.key }, Math.round(g.x), Math.round(g.y))
                            } else if (!card.current) {
                                panel.run("page.switch:" + card.modelData.id)
                            }
                        }
                        onDoubleClicked: panel.editing = card.modelData.id
                    }
                    Column {
                        x: 12
                        y: 11
                        width: parent.width - 24
                        spacing: 3
                        Item {
                            width: parent.width
                            height: 24
                            Text {
                                visible: !card.editingThis
                                anchors.verticalCenter: parent.verticalCenter
                                width: parent.width - (card.current ? 20 : 0)
                                text: card.modelData.title
                                color: Theme.text
                                elide: Text.ElideRight
                                font.family: Theme.fontFamily
                                font.pixelSize: 14
                                font.weight: Font.DemiBold
                            }
                            Glyph {
                                visible: card.current && !card.editingThis
                                anchors.right: parent.right
                                anchors.verticalCenter: parent.verticalCenter
                                name: "circle-check"
                                size: 16
                                color: Theme.accent
                            }
                            Loader {
                                anchors.fill: parent
                                active: card.editingThis
                                sourceComponent: GTextField {
                                    height: 26
                                    implicitHeight: 26
                                    fontSize: 13
                                    clearButton: false
                                    selectOnFocus: true
                                    monitorKey: panel.key
                                    maximumLength: 40
                                    Component.onCompleted: {
                                        text = card.modelData.title
                                        Qt.callLater(focusField)
                                    }
                                    onAccepted: {
                                        if (text.trim() !== "") {
                                            panel.run("page.rename:" + card.modelData.id, { title: text.trim() })
                                        }
                                        panel.editing = ""
                                        release()
                                    }
                                    onEscaped: {
                                        panel.editing = ""
                                        release()
                                    }
                                }
                            }
                        }
                        Text {
                            text: card.modelData.count + " 个岛屿"
                            color: Theme.textDim
                            font.family: Theme.fontFamily
                            font.pixelSize: 12
                        }
                        Text {
                            visible: card.modelData.label !== ""
                            width: parent.width
                            text: card.modelData.label
                            color: Theme.textFaint
                            elide: Text.ElideRight
                            font.family: Theme.fontFamily
                            font.pixelSize: 11
                        }
                    }
                }
            }
            // "New" card.
            Item {
                width: 164
                height: 78
                DashedRect {
                    anchors.fill: parent
                    radius: Theme.smallRadius
                    stroke: newArea.containsMouse ? Theme.accent : Theme.hairline
                    strokeWidth: 1.4
                    fill: newArea.containsMouse ? Theme.hover : "transparent"
                }
                Column {
                    anchors.centerIn: parent
                    spacing: 4
                    Glyph { anchors.horizontalCenter: parent.horizontalCenter; name: "plus"; size: 20; color: Theme.accent }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: "新建空白预设"
                        color: Theme.textDim
                        font.family: Theme.fontFamily
                        font.pixelSize: 12
                    }
                }
                MouseArea {
                    id: newArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: panel.run("page.new")
                }
            }
        }

        Row {
            spacing: 8
            GButton {
                text: "复制当前预设"
                icon: "copy"
                compact: true
                onClicked: panel.run("page.duplicate")
            }
            GButton {
                text: "保存布局快照"
                icon: "device-floppy"
                compact: true
                onClicked: panel.run("snapshot.save")
            }
        }
        Text {
            width: parent.width
            wrapMode: Text.Wrap
            text: "提示：在灵动岛的预设名称上滚动滚轮可快速切换；双击预设可重命名，右键可复制或删除。"
            color: Theme.textFaint
            font.family: Theme.fontFamily
            font.pixelSize: 12
        }
    }
}
