// Notices at the bottom right of the primary monitor (newest at the bottom).
// info / warning / error / success, optional action buttons; they time out
// unless the pointer rests on them (timeout 0 = stays until closed).  They live
// in their own always-on-top window (PopupWindow.qml) that never takes focus.
import QtQuick

Item {
    id: stack
    property var deskLayer: null
    property var wall: null
    property bool standalone: false
    readonly property bool wanted: Desk.noticesModel.count > 0
    width: 368
    height: Math.max(1, col.height)

    Column {
        id: col
        width: parent.width
        spacing: 10
        move: Transition {
            NumberAnimation { properties: "y"; duration: Theme.ms(220); easing.type: Easing.OutCubic }
        }
        Repeater {
            model: Desk.noticesModel
            delegate: Item {
                id: card
                required property var object
                readonly property var notice: object
                readonly property string kind: notice ? notice.kind : "info"
                readonly property color tone: kind === "error" ? Theme.danger
                                            : kind === "warning" ? "#F5A524"
                                            : kind === "success" ? "#34C77B" : Theme.accent
                width: col.width
                height: body.implicitHeight + 28
                property real slide: 1
                opacity: 1 - slide
                transform: Translate { x: card.slide * 48 }
                Component.onCompleted: enter.start()
                NumberAnimation {
                    id: enter
                    target: card
                    property: "slide"
                    from: 1
                    to: 0
                    duration: Theme.ms(300)
                    easing.type: Easing.OutCubic
                }

                MouseArea {
                    // Background: drag the notices somewhere else.
                    anchors.fill: parent
                    onPressed: (mouse) => {
                        if (Window.window && Window.window.beginMove) {
                            Window.window.beginMove()
                        }
                    }
                }
                Glass {
                    anchors.fill: parent
                    blurSource: stack.wall ? stack.wall.blurred : null
                    sharpSource: stack.wall ? stack.wall.sharp : null
                    solidFallback: stack.standalone || !stack.wall || !stack.wall.ready
                    solidAlpha: stack.standalone ? 0.95 : -1
                    solidShadow: stack.standalone
                    backdropOrigin: Qt.point(stack.x + card.x + (stack.deskLayer ? stack.deskLayer.inset : 0),
                                             stack.y + card.y + (stack.deskLayer ? stack.deskLayer.inset : 0))
                    backdropSize: Qt.size(stack.deskLayer && stack.deskLayer.scene ? stack.deskLayer.scene.monitorWidth : 1920,
                                          stack.deskLayer && stack.deskLayer.scene ? stack.deskLayer.scene.monitorHeight : 1080)
                    radius: 18
                    material: "frosted"
                    dark: Theme.dark
                    strength: Theme.strength
                    shadowSize: 18 * Theme.shadow
                    elevation: hover.hovered ? 1.4 : 1.2
                }
                HoverHandler { id: hover }

                Rectangle {
                    // Kind marker.
                    x: 14
                    y: 16
                    width: 30
                    height: 30
                    radius: 10
                    color: Qt.rgba(card.tone.r, card.tone.g, card.tone.b, 0.18)
                    Glyph {
                        anchors.centerIn: parent
                        name: card.kind === "error" || card.kind === "warning" ? "alert-triangle"
                              : card.kind === "success" ? "circle-check" : "info-circle"
                        size: 17
                        color: card.tone
                    }
                }
                Column {
                    id: body
                    x: 56
                    y: 14
                    width: parent.width - 56 - 40
                    spacing: 4
                    Text {
                        width: parent.width
                        text: card.notice ? card.notice.title : ""
                        color: Theme.text
                        wrapMode: Text.Wrap
                        maximumLineCount: 2
                        elide: Text.ElideRight
                        font.family: Theme.fontFamily
                        font.pixelSize: 14
                        font.weight: Font.DemiBold
                    }
                    Text {
                        width: parent.width
                        visible: text !== ""
                        text: card.notice ? card.notice.text : ""
                        color: Theme.textDim
                        wrapMode: Text.Wrap
                        maximumLineCount: 5
                        elide: Text.ElideRight
                        font.family: Theme.fontFamily
                        font.pixelSize: 12
                        lineHeight: 1.15
                    }
                    Item { width: 1; height: actions.visible ? 4 : 0 }
                    Flow {
                        id: actions
                        width: parent.width
                        visible: card.notice && card.notice.actions.length > 0
                        spacing: 8
                        Repeater {
                            model: card.notice ? card.notice.actions : []
                            delegate: GButton {
                                required property var modelData
                                required property int index
                                compact: true
                                kind: index === 0 ? "accent" : "tonal"
                                text: modelData.text || modelData.id
                                onClicked: Desk.noticeAction(card.notice.nid_, modelData.id)
                            }
                        }
                    }
                }
                IconButton {
                    anchors.right: parent.right
                    anchors.rightMargin: 8
                    y: 10
                    size: 26
                    iconSize: 14
                    icon: "x"
                    color: Theme.textDim
                    tip: "关闭"
                    onClicked: Desk.dismissNotice(card.notice.nid_)
                }

                // Remaining time (pauses while hovered).
                property real remaining: 1
                NumberAnimation on remaining {
                    id: countdown
                    running: !!card.notice && card.notice.timeout > 0
                    paused: running && hover.hovered
                    from: 1
                    to: 0
                    duration: card.notice ? Math.max(1, card.notice.timeout) : 1
                    onFinished: if (card.notice) Desk.dismissNotice(card.notice.nid_)
                }
                Rectangle {
                    visible: !!card.notice && card.notice.timeout > 0
                    x: 18
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 6
                    height: 2
                    radius: 1
                    width: (parent.width - 36) * card.remaining
                    color: Qt.rgba(card.tone.r, card.tone.g, card.tone.b, 0.55)
                }
            }
        }
    }
}
