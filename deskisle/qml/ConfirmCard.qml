// Non-modal confirmation for destructive actions (delete an island, a preset,
// layout import ...), also used when an AI assistant asks to do something
// destructive: then it carries a "来自 AI 助手" badge.  Esc cancels.  It lives
// in its own always-on-top window (PopupWindow.qml); drag the card to move it.
import QtQuick

Item {
    id: card
    property var deskLayer: null
    property var wall: null
    property bool standalone: false
    readonly property var info: Desk.confirmInfo
    readonly property bool open: !!info && !!info.id
    readonly property bool wanted: open
    property var shownInfo: ({})
    // Keep the last request while the card fades out (`open` may not be re-evaluated yet here).
    onInfoChanged: if (info && info.id) shownInfo = info
    Component.onCompleted: if (info && info.id) shownInfo = info
    readonly property bool agent: shownInfo.source === "agent"
    readonly property bool danger: shownInfo.danger !== false

    width: 440
    height: col.implicitHeight + 36
    visible: opacity > 0.01
    opacity: open ? 1 : 0
    scale: open ? 1 : 0.94
    transformOrigin: Item.Top
    Behavior on opacity { NumberAnimation { duration: Theme.ms(170) } }
    Behavior on scale { NumberAnimation { duration: Theme.ms(240); easing.type: Easing.OutBack } }

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.AllButtons
        onPressed: (mouse) => {
            if (mouse.button === Qt.LeftButton && Window.window && Window.window.beginMove) {
                Window.window.beginMove()
            }
        }
    }
    Glass {
        anchors.fill: parent
        blurSource: card.wall ? card.wall.blurred : null
        sharpSource: card.wall ? card.wall.sharp : null
        solidFallback: card.standalone || !card.wall || !card.wall.ready
        solidAlpha: card.standalone ? 0.96 : -1
        solidShadow: card.standalone
        backdropOrigin: Qt.point(card.x + (card.deskLayer ? card.deskLayer.inset : 0), card.y + (card.deskLayer ? card.deskLayer.inset : 0))
        backdropSize: Qt.size(card.deskLayer && card.deskLayer.scene ? card.deskLayer.scene.monitorWidth : 1920,
                              card.deskLayer && card.deskLayer.scene ? card.deskLayer.scene.monitorHeight : 1080)
        radius: Theme.radius
        material: "frosted"
        dark: Theme.dark
        strength: Theme.strength
        shadowSize: 24 * Theme.shadow
        elevation: 1.6
        tint: card.danger ? Theme.danger : Theme.accent
        tintStrength: 0.06
    }
    Rectangle {
        // Attention ring for assistant requests.
        anchors.fill: parent
        anchors.margins: -3
        radius: Theme.radius + 3
        color: "transparent"
        border.width: 2
        border.color: Theme.accent
        visible: card.agent && card.open
        SequentialAnimation on opacity {
            running: card.agent && card.open
            loops: Animation.Infinite
            NumberAnimation { to: 0.15; duration: 900; easing.type: Easing.InOutSine }
            NumberAnimation { to: 0.85; duration: 900; easing.type: Easing.InOutSine }
        }
    }

    Column {
        id: col
        x: 20
        y: 18
        width: parent.width - 40
        spacing: 10
        Rectangle {
            visible: card.agent
            height: 24
            width: agentRow.implicitWidth + 18
            radius: 12
            color: Theme.accentSoft
            Row {
                id: agentRow
                anchors.centerIn: parent
                spacing: 6
                Glyph { name: "robot"; size: 14; color: Theme.accent; anchors.verticalCenter: parent.verticalCenter }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: "来自 AI 助手的请求"
                    color: Theme.accent
                    font.family: Theme.fontFamily
                    font.pixelSize: 12
                    font.weight: Font.DemiBold
                }
            }
        }
        Row {
            width: parent.width
            spacing: 10
            Glyph {
                anchors.verticalCenter: parent.verticalCenter
                name: card.danger ? "alert-triangle" : "info-circle"
                size: 20
                color: card.danger ? Theme.danger : Theme.accent
            }
            Text {
                width: parent.width - 30
                anchors.verticalCenter: parent.verticalCenter
                text: card.shownInfo.title || ""
                color: Theme.text
                wrapMode: Text.Wrap
                font.family: Theme.fontFamily
                font.pixelSize: 16
                font.weight: Font.Bold
            }
        }
        Text {
            width: parent.width
            visible: text !== ""
            text: card.shownInfo.text || ""
            color: Theme.textDim
            wrapMode: Text.Wrap
            font.family: Theme.fontFamily
            font.pixelSize: 13
            lineHeight: 1.2
        }
        Item {
            width: parent.width
            height: 36
            Row {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                spacing: 10
                GButton {
                    text: "取消"
                    kind: "tonal"
                    onClicked: Desk.resolveConfirm(card.shownInfo.id, false)
                }
                GButton {
                    text: card.shownInfo.accept || "确定"
                    kind: card.danger ? "danger" : "accent"
                    onClicked: Desk.resolveConfirm(card.shownInfo.id, true)
                }
            }
        }
    }
}
