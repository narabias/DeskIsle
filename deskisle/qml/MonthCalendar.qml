// Month grid shared by the clock widget and the todo date picker (2.0.1).
// Monday first, lunar day names from the Clock service, optional marks
// (todo due dates: a dot under the day, red when overdue) and a selection.
import QtQuick

Item {
    id: cal
    property date anchorDate: new Date()     // month shown at offset 0
    property int offset: 0
    property bool showLunar: true
    property var marks: ({})                 // "YYYY-MM-DD" -> {count, overdue}
    property string selected: ""             // highlighted day (picker)
    property bool pickable: false            // every day is clickable (otherwise only marked days)
    property real minCellH: 26
    property bool divider: true
    signal picked(string date, real cx, real cy)

    readonly property int year: anchorDate.getFullYear()
    readonly property int month: anchorDate.getMonth() + 1
    readonly property int shownYear: year + Math.floor((month - 1 + offset) / 12)
    readonly property int shownMonth: ((month - 1 + offset) % 12 + 12) % 12 + 1
    readonly property var cells: visible ? Clock.monthGrid(shownYear, shownMonth) : []
    readonly property real cellW: width / 7
    readonly property real cellH: Math.max(minCellH, (height - 52) / 6)
    implicitHeight: 52 + 6 * minCellH

    Rectangle {
        visible: cal.divider
        anchors.left: parent.left
        anchors.right: parent.right
        height: 1
        color: Theme.hairline
    }
    Item {
        id: calHead
        y: 6
        width: parent.width
        height: 28
        Text {
            anchors.left: parent.left
            anchors.leftMargin: 4
            anchors.verticalCenter: parent.verticalCenter
            text: cal.shownYear + "年" + cal.shownMonth + "月"
            color: Theme.text
            font.family: Theme.fontFamily
            font.pixelSize: 13
            font.weight: Font.DemiBold
        }
        Row {
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            IconButton {
                icon: "chevron-left"
                size: 24
                iconSize: 14
                tip: "上个月"
                onClicked: cal.offset -= 1
            }
            IconButton {
                icon: "circle"
                size: 24
                iconSize: 9
                tip: "回到本月"
                visible: cal.offset !== 0
                onClicked: cal.offset = 0
            }
            IconButton {
                icon: "chevron-right"
                size: 24
                iconSize: 14
                tip: "下个月"
                onClicked: cal.offset += 1
            }
        }
    }
    Row {
        id: weekRow
        anchors.top: calHead.bottom
        width: parent.width
        Repeater {
            model: ["一", "二", "三", "四", "五", "六", "日"]
            delegate: Text {
                required property string modelData
                required property int index
                width: cal.cellW
                horizontalAlignment: Text.AlignHCenter
                text: modelData
                color: index >= 5 ? Theme.accent : Theme.textFaint
                font.family: Theme.fontFamily
                font.pixelSize: 11
            }
        }
    }
    Grid {
        anchors.top: weekRow.bottom
        anchors.topMargin: 4
        columns: 7
        Repeater {
            model: cal.cells
            delegate: Item {
                id: cell
                required property var modelData
                readonly property var mark: cal.marks ? cal.marks[modelData.date] : undefined
                readonly property bool chosen: cal.selected !== "" && cal.selected === modelData.date
                readonly property bool filled: modelData.today || chosen
                width: cal.cellW
                height: cal.cellH
                opacity: modelData.inMonth ? 1 : 0.35
                Rectangle {
                    anchors.centerIn: parent
                    width: Math.min(parent.width - 4, 38)
                    height: parent.height - 2
                    radius: 8
                    color: cell.chosen ? Theme.accent
                         : cell.modelData.today ? (cal.selected !== "" ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.22) : Theme.accent)
                         : (cellMouse.containsMouse ? Theme.hover : "transparent")
                    Behavior on color { ColorAnimation { duration: Theme.ms(120) } }
                }
                readonly property bool onAccent: cell.chosen || (cell.modelData.today && cal.selected === "")
                Column {
                    anchors.centerIn: parent
                    spacing: -1
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: cell.modelData.day
                        color: cell.onAccent ? Theme.onAccent : (cell.modelData.weekend ? Theme.accent : Theme.text)
                        font.family: Theme.fontFamily
                        font.pixelSize: 13
                        font.weight: cell.filled ? Font.Bold : Font.Normal
                    }
                    Text {
                        visible: cal.showLunar && cal.cellH >= 30
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: cell.modelData.lunar
                        color: cell.onAccent ? Theme.onAccent : (cell.modelData.special ? Theme.accent : Theme.textFaint)
                        font.family: Theme.fontFamily
                        font.pixelSize: 9
                    }
                }
                // Todo due on this day: a dot (red when something is overdue) - under the day
                // number, or in the corner when the lunar line takes the space below.
                readonly property bool lunarShown: cal.showLunar && cal.cellH >= 30
                Rectangle {
                    visible: !!cell.mark
                    x: cell.lunarShown ? Math.round(cell.width / 2 + Math.min(cell.width - 4, 38) / 2 - width - 3)
                                       : Math.round((cell.width - width) / 2)
                    y: cell.lunarShown ? 3 : cell.height - height - 2
                    width: cell.mark && cell.mark.count > 1 && !cell.lunarShown ? 10 : 5
                    height: 5
                    radius: 2.5
                    color: cell.onAccent ? Theme.onAccent : (cell.mark && cell.mark.overdue ? Theme.danger : Theme.accent)
                }
                MouseArea {
                    id: cellMouse
                    anchors.fill: parent
                    enabled: cal.pickable || !!cell.mark
                    hoverEnabled: enabled
                    cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                    onClicked: {
                        var p = cell.mapToItem(cal, cell.width / 2, cell.height)
                        cal.picked(cell.modelData.date, p.x, p.y)
                    }
                }
            }
        }
    }
}
