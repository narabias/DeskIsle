// The dynamic bar ("灵动岛"): a black capsule at the top of the primary monitor.
//   [preset chip · page dots] | search | clean desk | + | (undo) | (now playing) | (focus) | settings
// Buttons toggle the bar panels shown by PanelHost right below it; the wheel
// over the preset chip switches presets, right click opens the desktop menu.
import QtQuick
import QtQuick.Effects

Item {
    id: bar
    property var deskLayer: null
    readonly property string key: deskLayer ? deskLayer.key : ""
    readonly property var scene: deskLayer ? deskLayer.scene : null
    readonly property string panel: deskLayer && deskLayer.panelHere ? Desk.panel : ""
    readonly property bool media: Player.available && Player.hasSession
    readonly property real h: Theme.barHeight
    readonly property color ink: "#F3F4F6"
    readonly property color inkDim: Qt.rgba(0.95, 0.96, 0.97, 0.55)
    readonly property color wash: Qt.rgba(1, 1, 1, 0.13)

    width: pill.width
    height: h
    transformOrigin: Item.Top
    scale: Desk.prefs.bar_hover_zoom && hover.hovered && panel === "" ? 1.07 : 1
    Behavior on scale { NumberAnimation { duration: Theme.ms(220); easing.type: Easing.OutCubic } }
    opacity: Desk.hidden && !hover.hovered && panel === "" ? 0.78 : 1
    Behavior on opacity { NumberAnimation { duration: Theme.ms(200) } }

    HoverHandler { id: hover }

    function toggle(name) {
        Desk.togglePanel(name, key)
    }

    RectangularShadow {
        anchors.fill: pill
        radius: pill.radius
        blur: 22
        offset.y: 5
        color: Qt.rgba(0, 0, 0, 0.42)
    }
    Rectangle {
        id: pill
        height: bar.h
        width: row.width + 10
        radius: height / 2
        color: "#0D0E11"
        border.width: 1
        border.color: Qt.rgba(1, 1, 1, 0.08)
        Behavior on width { NumberAnimation { duration: Theme.ms(280); easing.type: Easing.OutCubic } }

        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.RightButton
            onClicked: (mouse) => {
                var g = mapToGlobal(mouse.x, mouse.y)
                App.popupMenuAt("desktop", bar.key, {}, Math.round(g.x), Math.round(g.y))
            }
        }

        Row {
            id: row
            x: 5
            anchors.verticalCenter: parent.verticalCenter
            spacing: 1

            // Preset chip -------------------------------------------------------------------------------
            Item {
                id: chip
                anchors.verticalCenter: parent.verticalCenter
                height: bar.h - 8
                width: chipRow.implicitWidth + 22
                readonly property var pages: bar.scene ? bar.scene.pages : []
                Rectangle {
                    anchors.fill: parent
                    radius: height / 2
                    color: bar.panel === "presets" ? Qt.rgba(1, 1, 1, 0.16) : (chipArea.containsMouse ? bar.wash : "transparent")
                    Behavior on color { ColorAnimation { duration: Theme.ms(110) } }
                }
                Row {
                    id: chipRow
                    anchors.centerIn: parent
                    spacing: 7
                    Glyph {
                        anchors.verticalCenter: parent.verticalCenter
                        name: "layout-board"
                        size: 16
                        color: Theme.accent
                    }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: bar.scene && bar.scene.pageTitle !== "" ? bar.scene.pageTitle : "桌面"
                        color: bar.ink
                        font.family: Theme.fontFamily
                        font.pixelSize: 13
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                        width: Math.min(implicitWidth, 130)
                    }
                    Row {
                        anchors.verticalCenter: parent.verticalCenter
                        visible: chip.pages.length > 1
                        spacing: 4
                        Repeater {
                            model: chip.pages.length > 1 ? chip.pages : []
                            delegate: Rectangle {
                                required property var modelData
                                width: modelData.current ? 12 : 5
                                height: 5
                                radius: 2.5
                                color: modelData.current ? bar.ink : Qt.rgba(1, 1, 1, 0.32)
                                Behavior on width { NumberAnimation { duration: Theme.ms(200) } }
                            }
                        }
                    }
                }
                MouseArea {
                    id: chipArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: bar.toggle("presets")
                    property real acc: 0
                    onWheel: (wheel) => {
                        acc += wheel.angleDelta.y
                        if (Math.abs(acc) >= 120) {
                            Desk.cyclePage(bar.key, acc > 0 ? -1 : 1)
                            acc = 0
                        }
                    }
                }
                Tip {
                    text: "预设：点击切换或管理，滚轮快速切换"
                    shown: chipArea.containsMouse
                }
            }

            Rectangle {
                anchors.verticalCenter: parent.verticalCenter
                width: 1
                height: 16
                color: Qt.rgba(1, 1, 1, 0.12)
            }
            Item { width: 3; height: 1 }

            IconButton {
                anchors.verticalCenter: parent.verticalCenter
                icon: "search"
                tip: "搜索桌面与文件  Ctrl+Alt+F"
                size: bar.h - 6
                color: bar.panel === "search" ? Theme.accent : bar.ink
                hoverColor: bar.wash
                checked: bar.panel === "search"
                flat: true
                onClicked: bar.toggle("search")
            }
            IconButton {
                anchors.verticalCenter: parent.verticalCenter
                icon: Desk.hidden ? "eye" : "eye-off"
                tip: Desk.hidden ? "恢复显示  Ctrl+Alt+H" : "清屏  Ctrl+Alt+H"
                size: bar.h - 6
                color: Desk.hidden ? Theme.accent : bar.ink
                hoverColor: bar.wash
                flat: true
                onClicked: Desk.toggleHidden()
            }
            IconButton {
                id: plus
                anchors.verticalCenter: parent.verticalCenter
                icon: "plus"
                tip: "新建收纳岛、网页或小组件"
                size: bar.h - 6
                iconSize: 19
                color: bar.panel.indexOf("new") === 0 ? Theme.accent : bar.ink
                hoverColor: bar.wash
                flat: true
                rotation: bar.panel.indexOf("new") === 0 ? 45 : 0
                Behavior on rotation { NumberAnimation { duration: Theme.ms(240); easing.type: Easing.OutBack } }
                onClicked: bar.toggle("new")
            }
            IconButton {
                anchors.verticalCenter: parent.verticalCenter
                visible: Desk.canUndo
                icon: "undo"
                tip: "撤销排布  Ctrl+Alt+Z"
                size: bar.h - 6
                color: bar.ink
                hoverColor: bar.wash
                flat: true
                onClicked: Desk.undo()
            }

            // Now playing ---------------------------------------------------------------------------------
            Item {
                id: mini
                anchors.verticalCenter: parent.verticalCenter
                visible: bar.media
                height: bar.h - 8
                width: miniRow.implicitWidth + 14
                Rectangle {
                    anchors.fill: parent
                    radius: height / 2
                    color: bar.panel === "media" ? Qt.rgba(1, 1, 1, 0.16) : (miniArea.containsMouse ? bar.wash : "transparent")
                }
                Row {
                    id: miniRow
                    anchors.centerIn: parent
                    spacing: 7
                    Item {
                        anchors.verticalCenter: parent.verticalCenter
                        width: 22
                        height: 22
                        Rectangle {
                            anchors.fill: parent
                            radius: 6
                            color: Qt.rgba(1, 1, 1, 0.12)
                            visible: !cover.ready
                            Glyph {
                                anchors.centerIn: parent
                                name: "music"
                                size: 13
                                color: bar.ink
                            }
                        }
                        RoundImage {
                            id: cover
                            anchors.fill: parent
                            radius: 6
                            source: Player.cover
                        }
                    }
                    Row {
                        // Equalizer bars (animated while playing).
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 2
                        height: 14
                        Repeater {
                            model: 3
                            delegate: Rectangle {
                                required property int index
                                anchors.bottom: parent.bottom
                                width: 3
                                radius: 1.5
                                color: Player.accent && Player.accent.a > 0 ? Qt.lighter(Player.accent, 1.3) : Theme.accent
                                height: 4
                                SequentialAnimation on height {
                                    running: Player.playing && !App.paused && Theme.ms(100) > 0
                                    loops: Animation.Infinite
                                    NumberAnimation { to: 14 - index * 3; duration: 260 + index * 90; easing.type: Easing.InOutSine }
                                    NumberAnimation { to: 4 + index; duration: 300 + index * 70; easing.type: Easing.InOutSine }
                                }
                            }
                        }
                    }
                }
                MouseArea {
                    id: miniArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    acceptedButtons: Qt.LeftButton | Qt.MiddleButton
                    onClicked: (mouse) => {
                        if (mouse.button === Qt.MiddleButton) {
                            Player.playPause()
                        } else {
                            bar.toggle("media")
                        }
                    }
                }
                Tip {
                    text: (Player.title || "正在播放") + (Player.artist ? " · " + Player.artist : "") + "\n中键：播放 / 暂停"
                    shown: miniArea.containsMouse && bar.panel !== "media"
                }
            }

            IconButton {
                anchors.verticalCenter: parent.verticalCenter
                visible: Desk.focusMode
                icon: "focus"
                tip: "退出聚焦层  Ctrl+Alt+Space"
                size: bar.h - 6
                color: Theme.accent
                hoverColor: bar.wash
                flat: true
                onClicked: Desk.toggleFocus()
            }
            IconButton {
                anchors.verticalCenter: parent.verticalCenter
                icon: "settings"
                tip: "设置"
                size: bar.h - 6
                color: bar.ink
                hoverColor: bar.wash
                flat: true
                onClicked: Desk.openSettings("")
            }
        }
    }
}
