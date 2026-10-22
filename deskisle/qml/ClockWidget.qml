// Clock widget: digital / analog / flip styles, 24 h or 12 h (with Chinese
// day periods), optional seconds, the lunar date with solar terms and
// festivals, and a month calendar with lunar days when the island is tall.
import QtQuick

Item {
    id: clock
    property var island: null
    readonly property var cfg: island && island.proxy ? island.proxy.widgetConfig : ({})
    readonly property var prefs: Desk.prefs
    readonly property bool h24: cfg.h24 !== undefined ? !!cfg.h24 : prefs.clock_24h !== false
    readonly property bool seconds: cfg.seconds !== undefined ? !!cfg.seconds : !!prefs.clock_seconds
    readonly property bool showLunar: (cfg.lunar !== undefined ? !!cfg.lunar : prefs.clock_lunar !== false)
                                      && Clock.lunarAvailable
    readonly property string style: cfg.style || prefs.clock_style || "digital"
    readonly property bool tall: height >= 330
    readonly property real faceH: tall ? Math.min(200, height * 0.42) : height
    property date now: new Date()

    Timer {
        interval: 1000
        running: true
        repeat: true
        triggeredOnStart: true
        onTriggered: clock.now = new Date()
    }

    function pad(n) {
        return n < 10 ? "0" + n : "" + n
    }
    readonly property int hours: now.getHours()
    readonly property string hh: h24 ? pad(hours) : String(hours % 12 === 0 ? 12 : hours % 12)
    readonly property string mm: pad(now.getMinutes())
    readonly property string ss: pad(now.getSeconds())
    readonly property string period: hours < 5 ? "凌晨" : hours < 8 ? "早上" : hours < 11 ? "上午"
                                   : hours < 13 ? "中午" : hours < 18 ? "下午" : "晚上"
    readonly property var weekNames: ["周日", "周一", "周二", "周三", "周四", "周五", "周六"]
    readonly property string dateText: (now.getMonth() + 1) + "月" + now.getDate() + "日  " + weekNames[now.getDay()]
    readonly property var lunar: Clock.lunar
    readonly property string lunarText: showLunar && lunar.text ? "农历" + lunar.text + (lunar.year ? "  " + lunar.year : "") : ""
    readonly property string special: showLunar ? (lunar.festival || lunar.term || "") : ""

    // Shared date / lunar block ------------------------------------------------------------------------
    // Inline components do not see the ids of this file, hence `host`.
    component DateBlock: Column {
        id: block
        property var host: null
        property real scale_: 1
        property int align: Text.AlignLeft
        spacing: 3
        Text {
            width: parent.width
            text: block.host ? block.host.dateText : ""
            color: Theme.textDim
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(14 * parent.scale_)
            font.weight: Font.Medium
            horizontalAlignment: parent.align
            elide: Text.ElideRight
        }
        Row {
            visible: !!block.host && (block.host.lunarText !== "" || block.host.special !== "")
            spacing: 6
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: block.host ? block.host.lunarText : ""
                color: Theme.textFaint
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(12 * block.scale_)
            }
            Rectangle {
                visible: !!block.host && block.host.special !== ""
                anchors.verticalCenter: parent.verticalCenter
                width: specialText.implicitWidth + 12
                height: 18
                radius: 9
                color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.18)
                Text {
                    id: specialText
                    anchors.centerIn: parent
                    text: block.host ? block.host.special : ""
                    color: Theme.accent
                    font.family: Theme.fontFamily
                    font.pixelSize: 11
                    font.weight: Font.DemiBold
                }
            }
        }
    }

    Item {
        id: face
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: clock.faceH

        // Digital ------------------------------------------------------------------------------------
        Item {
            id: digital
            anchors.fill: parent
            anchors.leftMargin: 22
            anchors.rightMargin: 18
            visible: clock.style !== "analog" && clock.style !== "split"
            readonly property real big: Math.max(30, Math.min(face.height * 0.40, width * (clock.seconds ? 0.25 : 0.30)))
            Column {
                anchors.verticalCenter: parent.verticalCenter
                anchors.verticalCenterOffset: 2
                width: parent.width
                spacing: 2
                Text {
                    visible: !clock.h24
                    text: clock.period
                    color: Theme.accent
                    font.family: Theme.fontFamily
                    font.pixelSize: Math.max(11, digital.big * 0.2)
                    font.weight: Font.DemiBold
                }
                Row {
                    spacing: 6
                    Text {
                        id: bigTime
                        text: clock.hh + ":" + clock.mm
                        color: Theme.text
                        font.family: Theme.fontFamily
                        font.pixelSize: digital.big
                        font.weight: Font.Light
                        font.letterSpacing: -1
                    }
                    Text {
                        visible: clock.seconds
                        anchors.baseline: bigTime.baseline
                        text: clock.ss
                        color: Theme.textFaint
                        font.family: Theme.fontFamily
                        font.pixelSize: digital.big * 0.36
                        font.weight: Font.Medium
                    }
                }
                Item { width: 1; height: 4 }
                DateBlock {
                    host: clock
                    width: parent.width
                    scale_: Math.max(0.85, Math.min(1.2, face.height / 190))
                }
            }
        }

        // Analog ---------------------------------------------------------------------------------------
        Item {
            id: analog
            anchors.fill: parent
            visible: clock.style === "analog"
            readonly property real d: Math.max(60, Math.min(face.height - 28, width * 0.5))
            Item {
                id: dial
                width: analog.d
                height: analog.d
                anchors.left: parent.left
                anchors.leftMargin: 18
                anchors.verticalCenter: parent.verticalCenter
                Rectangle {
                    anchors.fill: parent
                    radius: width / 2
                    color: Theme.dark ? Qt.rgba(1, 1, 1, 0.04) : Qt.rgba(0, 0, 0, 0.03)
                    border.width: 1
                    border.color: Theme.hairline
                }
                Repeater {
                    model: 60
                    delegate: Item {
                        required property int index
                        readonly property bool major: index % 5 === 0
                        x: dial.width / 2 - width / 2
                        y: 0
                        width: major ? 2.5 : 1.2
                        height: dial.height
                        rotation: index * 6
                        Rectangle {
                            width: parent.width
                            height: parent.major ? dial.height * 0.075 : dial.height * 0.035
                            y: dial.height * 0.04
                            radius: width / 2
                            color: parent.major ? Theme.textDim : Theme.textFaint
                            opacity: parent.major ? 0.9 : 0.5
                        }
                    }
                }
                component Hand: Item {
                    id: hand
                    property real angle: 0
                    property real length: 0.3
                    property real thick: 3
                    property color tint: Theme.text
                    anchors.fill: parent
                    rotation: angle
                    Rectangle {
                        width: hand.thick
                        height: hand.height * hand.length
                        radius: width / 2
                        x: hand.width / 2 - width / 2
                        y: hand.height / 2 - height + width
                        color: hand.tint
                        antialiasing: true
                    }
                }
                Hand {
                    angle: (clock.now.getHours() % 12) * 30 + clock.now.getMinutes() * 0.5
                    length: 0.27
                    thick: 4.5
                }
                Hand {
                    angle: clock.now.getMinutes() * 6 + clock.now.getSeconds() * 0.1
                    length: 0.39
                    thick: 3
                }
                Hand {
                    visible: clock.seconds
                    angle: clock.now.getSeconds() * 6
                    length: 0.43
                    thick: 1.4
                    tint: Theme.accent
                }
                Rectangle {
                    anchors.centerIn: parent
                    width: 8
                    height: 8
                    radius: 4
                    color: Theme.accent
                }
            }
            Column {
                anchors.left: dial.right
                anchors.leftMargin: 18
                anchors.right: parent.right
                anchors.rightMargin: 14
                anchors.verticalCenter: parent.verticalCenter
                spacing: 4
                Text {
                    text: (clock.h24 ? "" : clock.period + " ") + clock.hh + ":" + clock.mm
                    color: Theme.text
                    font.family: Theme.fontFamily
                    font.pixelSize: Math.max(18, Math.min(30, analog.d * 0.2))
                    font.weight: Font.Medium
                }
                DateBlock {
                    host: clock
                    width: parent.width
                    scale_: 0.92
                }
            }
        }

        // Flip ------------------------------------------------------------------------------------------
        Item {
            id: split
            anchors.fill: parent
            visible: clock.style === "split"
            readonly property real cardH: Math.max(48, Math.min(face.height - 70, (width - 64) / 2 * 0.9))
            readonly property real cardW: Math.min((width - 54) / 2, cardH * 1.18)
            component FlipCard: Item {
                id: card
                property string value: ""
                property string shown: ""
                // Only a visible card animates; the hidden styles just keep the text current.
                onValueChanged: {
                    if (card.visible && card.shown !== "") {
                        flip.restart()
                    } else {
                        flip.stop()
                        squash.yScale = 1
                        card.shown = card.value
                    }
                }
                Component.onCompleted: card.shown = card.value
                Rectangle {
                    anchors.fill: parent
                    radius: Math.min(16, height * 0.16)
                    color: Theme.dark ? Qt.rgba(1, 1, 1, 0.07) : Qt.rgba(0, 0, 0, 0.05)
                    border.width: 1
                    border.color: Theme.hairline
                    // Lower half a touch darker instead of a line through the digits.
                    Rectangle {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        anchors.margins: 1
                        height: parent.height / 2 - 1
                        radius: parent.radius
                        color: Theme.dark ? Qt.rgba(0, 0, 0, 0.10) : Qt.rgba(0, 0, 0, 0.025)
                    }
                }
                Text {
                    id: digits
                    anchors.centerIn: parent
                    text: card.shown
                    color: Theme.text
                    font.family: Theme.fontFamily
                    font.pixelSize: card.height * 0.62
                    font.weight: Font.DemiBold
                    transform: Scale { id: squash; origin.y: digits.height / 2; yScale: 1 }
                }
                SequentialAnimation {
                    id: flip
                    NumberAnimation { target: squash; property: "yScale"; to: 0; duration: Theme.ms(110); easing.type: Easing.InQuad }
                    PropertyAction { target: card; property: "shown"; value: card.value }
                    NumberAnimation { target: squash; property: "yScale"; to: 1; duration: Theme.ms(150); easing.type: Easing.OutQuad }
                }
            }
            Column {
                anchors.centerIn: parent
                spacing: 10
                Row {
                    anchors.horizontalCenter: parent.horizontalCenter
                    spacing: 10
                    FlipCard { value: clock.hh; width: split.cardW; height: split.cardH }
                    Column {
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: split.cardH * 0.16
                        Repeater {
                            model: 2
                            delegate: Rectangle {
                                width: 6
                                height: 6
                                radius: 3
                                color: Theme.accent
                                opacity: 0.9
                            }
                        }
                    }
                    FlipCard { value: clock.mm; width: split.cardW; height: split.cardH }
                }
                Row {
                    anchors.horizontalCenter: parent.horizontalCenter
                    spacing: 8
                    Text {
                        visible: !clock.h24
                        text: clock.period
                        color: Theme.accent
                        font.family: Theme.fontFamily
                        font.pixelSize: 13
                        font.weight: Font.DemiBold
                    }
                    Text {
                        text: clock.dateText
                        color: Theme.textDim
                        font.family: Theme.fontFamily
                        font.pixelSize: 13
                    }
                    Text {
                        visible: clock.lunarText !== ""
                        text: clock.showLunar ? "农历" + clock.lunar.text : ""
                        color: Theme.textFaint
                        font.family: Theme.fontFamily
                        font.pixelSize: 12
                    }
                    Text {
                        visible: clock.special !== ""
                        text: clock.special
                        color: Theme.accent
                        font.family: Theme.fontFamily
                        font.pixelSize: 12
                        font.weight: Font.DemiBold
                    }
                }
            }
        }
    }

    // Month calendar (tall island) ---------------------------------------------------------------------
    // Days with todo items carry a dot; click one to see what is due (2.0.1).
    MonthCalendar {
        id: calendar
        visible: clock.tall
        anchors.top: face.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.leftMargin: 14
        anchors.rightMargin: 14
        anchors.bottomMargin: 12
        anchorDate: clock.now
        showLunar: clock.showLunar
        marks: typeof Todo !== "undefined" && Todo.dueMap ? Todo.dueMap : ({})
        onPicked: (date, cx, cy) => {
            dayPop.items = Todo.itemsOn(date)
            dayPop.title = Number(date.slice(5, 7)) + "月" + Number(date.slice(8, 10)) + "日"
            dayPop.cx = cx
            dayPop.cy = cy
            dayPop.open = dayPop.items.length > 0
            if (dayPop.open) {
                dayHide.restart()
            }
        }
    }
    MouseArea {
        // Click anywhere else closes the day popover.
        anchors.fill: parent
        visible: dayPop.open
        onPressed: (mouse) => { dayPop.open = false; mouse.accepted = false }
    }
    Timer {
        id: dayHide
        interval: 6000
        onTriggered: dayPop.open = false
    }
    Rectangle {
        id: dayPop
        property bool open: false
        property var items: []
        property string title: ""
        property real cx: 0
        property real cy: 0
        z: 5
        visible: opacity > 0.01
        opacity: open ? 1 : 0
        scale: open ? 1 : 0.94
        transformOrigin: Item.Top
        Behavior on opacity { NumberAnimation { duration: Theme.ms(140) } }
        Behavior on scale { NumberAnimation { duration: Theme.ms(180); easing.type: Easing.OutCubic } }
        width: Math.min(clock.width - 24, 240)
        height: popCol.implicitHeight + 16
        x: Math.max(12, Math.min(clock.width - width - 12, calendar.x + cx - width / 2))
        y: Math.min(clock.height - height - 8, calendar.y + cy + 2)
        radius: 10
        color: Theme.dark ? Qt.rgba(0.10, 0.11, 0.13, 0.96) : Qt.rgba(0.98, 0.98, 0.99, 0.97)
        border.width: 1
        border.color: Theme.hairline
        Column {
            id: popCol
            x: 10
            y: 8
            width: parent.width - 20
            spacing: 4
            Text {
                text: dayPop.title + " · " + dayPop.items.length + " 项待办"
                color: Theme.textDim
                font.family: Theme.fontFamily
                font.pixelSize: 11
                font.weight: Font.DemiBold
            }
            Repeater {
                model: dayPop.items.slice(0, 6)
                delegate: Row {
                    required property var modelData
                    width: popCol.width
                    spacing: 6
                    Text {
                        width: 36
                        text: modelData.time || "全天"
                        color: Theme.accent
                        font.family: Theme.fontFamily
                        font.pixelSize: 11
                    }
                    Text {
                        width: parent.width - 42
                        text: modelData.text
                        elide: Text.ElideRight
                        color: modelData.done ? Theme.textFaint : Theme.text
                        font.strikeout: modelData.done
                        font.family: Theme.fontFamily
                        font.pixelSize: 12
                    }
                }
            }
        }
    }
}
