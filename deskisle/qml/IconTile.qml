// One file / folder icon: system icon (loaded asynchronously, glyph fallback),
// a label of up to two lines (three while hovered), hover / selection plates,
// pin and "missing" badges, and the dashed drop-gap form used while dragging.
import QtQuick
import QtQuick.Shapes

Item {
    id: tile
    property string path: ""
    property string name: ""
    property string icon: ""
    property bool isDir: false
    property bool available: true
    property bool pinned: false
    property bool selected: false
    property bool placeholder: false
    property bool match: true
    property bool hovered: false
    property bool onDesktop: false      // loose desktop icon: white label with shadow
    property bool dimmed: false         // being dragged away
    property int iconSize: 48
    readonly property bool compact: iconSize <= 32
    readonly property real plateBottom: label.y + label.height + (compact ? 4 : 6)

    opacity: !match ? 0.22 : (dimmed ? 0.4 : 1)
    Behavior on opacity { NumberAnimation { duration: Theme.ms(140) } }

    // Drop gap ---------------------------------------------------------------------------------------
    Item {
        id: gap
        visible: tile.placeholder
        anchors.fill: parent
        anchors.margins: 6
        scale: visible ? 1 : 0.6
        Behavior on scale { NumberAnimation { duration: Theme.ms(160); easing.type: Easing.OutBack } }
        Shape {
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
                strokeColor: Theme.accent
                strokeWidth: 1.5
                strokeStyle: ShapePath.DashLine
                dashPattern: [3, 3]
                fillColor: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.12)
                PathRectangle {
                    x: 0.75
                    y: 0.75
                    width: gap.width - 1.5
                    height: gap.height - 1.5
                    radius: Theme.smallRadius
                }
            }
        }
        Glyph {
            anchors.centerIn: parent
            name: "plus"
            size: 18
            color: Theme.accent
            opacity: 0.8
        }
    }

    // Hover / selection plate -------------------------------------------------------------------------
    Rectangle {
        id: plate
        visible: !tile.placeholder && (tile.selected || tile.hovered)
        x: 2
        y: 1
        width: tile.width - 4
        height: Math.max(tile.height - 2, tile.plateBottom - 1)
        radius: Theme.smallRadius
        color: tile.selected
               ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, tile.onDesktop ? 0.34 : 0.22)
               : (tile.onDesktop ? Qt.rgba(1, 1, 1, 0.16) : Theme.hover)
        border.width: tile.selected ? 1 : 0
        border.color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.7)
    }

    // Icon ---------------------------------------------------------------------------------------------
    Item {
        id: iconBox
        visible: !tile.placeholder
        width: tile.iconSize
        height: tile.iconSize
        anchors.horizontalCenter: parent.horizontalCenter
        y: tile.compact ? 4 : 7
        opacity: tile.available ? 1 : 0.45

        Image {
            id: img
            anchors.fill: parent
            source: tile.icon
            asynchronous: true
            cache: true
            smooth: true
            fillMode: Image.PreserveAspectFit
            opacity: status === Image.Ready ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: Theme.ms(120) } }
        }
        Glyph {
            anchors.centerIn: parent
            visible: img.status !== Image.Ready
            name: tile.isDir ? "folder" : "file"
            size: Math.round(tile.iconSize * 0.78)
            stroke: 1.3
            color: tile.onDesktop ? Qt.rgba(1, 1, 1, 0.85) : Theme.textDim
        }
    }

    // Badges -------------------------------------------------------------------------------------------
    Rectangle {
        visible: tile.pinned && !tile.placeholder
        width: 16
        height: 16
        radius: 8
        x: iconBox.x + iconBox.width - 10
        y: iconBox.y - 4
        color: Theme.accent
        Glyph {
            anchors.centerIn: parent
            name: "pin"
            size: 11
            stroke: 2
            color: Theme.onAccent
        }
    }
    Rectangle {
        visible: !tile.available && !tile.placeholder
        width: 18
        height: 18
        radius: 9
        x: iconBox.x + iconBox.width - 12
        y: iconBox.y + iconBox.height - 14
        color: Theme.danger
        Glyph {
            anchors.centerIn: parent
            name: "unlink"
            size: 12
            stroke: 2
            color: "white"
        }
    }

    // Label --------------------------------------------------------------------------------------------
    Text {
        id: label
        visible: !tile.placeholder
        anchors.top: iconBox.bottom
        anchors.topMargin: tile.compact ? 3 : 5
        anchors.horizontalCenter: parent.horizontalCenter
        width: tile.width - 8
        text: tile.name
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.WrapAtWordBoundaryOrAnywhere
        maximumLineCount: (tile.hovered || tile.selected) ? 3 : (tile.compact ? 1 : 2)
        elide: Text.ElideRight
        color: tile.onDesktop ? "white" : Theme.text
        style: tile.onDesktop ? Text.Raised : Text.Normal
        styleColor: Qt.rgba(0, 0, 0, 0.6)
        font.family: Theme.fontFamily
        font.pixelSize: tile.compact ? 11 : 12
        font.strikeout: !tile.available
    }

    Tip {
        text: tile.available ? tile.path : "找不到原文件（已移动或删除）\n" + tile.path
        shown: tile.hovered && !tile.placeholder && (label.truncated || !tile.available)
        anchorItem: iconBox
        delay: 900
    }
}
