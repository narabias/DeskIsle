// One settings row: title + description on the left, a control on the right.
// kind "switch" | "slider" | "segmented" binds the control to Desk.prefs[pref];
// otherwise put any controls as children (they go to the right, or below the
// text with stacked: true).
import QtQuick

Item {
    id: row
    property string title: ""
    property string description: ""
    property string pref: ""
    property string kind: ""
    property var options: []              // segmented: [{value, text}]
    property real from: 0
    property real to: 1
    property real step: 0
    property string unit: ""
    property int decimals: 0
    property real displayScale: 1
    property bool stacked: false
    // A hairline above every row that has a visible row before it.
    property bool divider: {
        if (!parent) {
            return false
        }
        var kids = parent.children
        for (var i = 0; i < kids.length; ++i) {
            if (kids[i] === row) {
                return false
            }
            if (kids[i].visible && kids[i].height > 0) {
                return true
            }
        }
        return false
    }
    default property alias content: slot.data
    readonly property var value: pref !== "" ? Desk.prefs[pref] : undefined
    signal changed(var value)

    function commit(v) {
        if (pref !== "") {
            Desk.setPref(pref, v)
        }
        changed(v)
    }
    // Settings search: briefly tint the row it jumped to.
    function flash() {
        flashAnim.restart()
    }

    width: parent ? parent.width : 640
    visible: true
    readonly property real controlHeight: Math.max(slot.implicitHeight, ctl.item ? ctl.implicitHeight : 0)
    implicitHeight: stacked ? textCol.implicitHeight + controlHeight + 38
                            : Math.max(58, textCol.implicitHeight + 26, controlHeight + 20)
    height: visible ? implicitHeight : 0

    Rectangle {
        id: flashRect
        anchors.fill: parent
        anchors.margins: 3
        radius: 11
        color: Theme.accentSoft
        opacity: 0
        SequentialAnimation {
            id: flashAnim
            NumberAnimation { target: flashRect; property: "opacity"; to: 1; duration: 160 }
            PauseAnimation { duration: 900 }
            NumberAnimation { target: flashRect; property: "opacity"; to: 0; duration: 900 }
        }
    }
    Rectangle {
        visible: row.divider
        x: 16
        width: parent.width - 32
        height: 1
        color: Theme.hairline
    }
    Column {
        id: textCol
        x: 16
        y: row.stacked ? 14 : Math.round((row.height - implicitHeight) / 2)
        width: row.stacked ? row.width - 32 : row.width - 48 - Math.max(slot.implicitWidth, ctl.item ? ctl.implicitWidth : 0)
        spacing: 3
        Text {
            width: parent.width
            text: row.title
            color: Theme.text
            wrapMode: Text.Wrap
            font.family: Theme.fontFamily
            font.pixelSize: 14
        }
        Text {
            width: parent.width
            visible: text !== ""
            text: row.description
            color: Theme.textDim
            wrapMode: Text.Wrap
            font.family: Theme.fontFamily
            font.pixelSize: 12
            lineHeight: 1.12
        }
    }
    Row {
        id: slot
        spacing: 8
        anchors.right: row.stacked ? undefined : parent.right
        anchors.rightMargin: 16
        x: row.stacked ? 16 : 0
        y: row.stacked ? textCol.y + textCol.implicitHeight + 10 : Math.round((row.height - implicitHeight) / 2)
        layoutDirection: Qt.LeftToRight
    }
    Loader {
        id: ctl
        anchors.right: row.stacked ? undefined : parent.right
        anchors.rightMargin: 16
        anchors.verticalCenter: row.stacked ? undefined : parent.verticalCenter
        x: row.stacked ? 16 : 0
        y: row.stacked ? textCol.y + textCol.implicitHeight + 10 : 0
        active: row.kind !== ""
        sourceComponent: row.kind === "switch" ? switchC : row.kind === "slider" ? sliderC : row.kind === "segmented" ? segC : null
    }
    Component {
        id: switchC
        GSwitch {
            checked: !!row.value
            onToggled: (v) => row.commit(v)
        }
    }
    Component {
        id: sliderC
        Row {
            spacing: 10
            Text {
                anchors.verticalCenter: parent.verticalCenter
                width: 64
                horizontalAlignment: Text.AlignRight
                text: (sl.shown * row.displayScale).toFixed(row.decimals) + row.unit
                color: Theme.textDim
                font.family: Theme.fontFamily
                font.pixelSize: 12
            }
            GSlider {
                id: sl
                anchors.verticalCenter: parent.verticalCenter
                width: 200
                from: row.from
                to: row.to
                stepSize: row.step
                value: Number(row.value) || 0
                onCommitted: (v) => row.commit(row.step >= 1 ? Math.round(v) : v)
            }
        }
    }
    Component {
        id: segC
        Segmented {
            options: row.options
            current: row.value
            onPicked: (v) => row.commit(v)
        }
    }
}
