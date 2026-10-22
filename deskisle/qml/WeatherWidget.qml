// Weather widget (MSN weather like Windows, Open-Meteo fallback): current
// conditions with an animated icon, feels-like / high / low, humidity, wind,
// air quality and UV, and a five day forecast when there is room.
import QtQuick

Item {
    id: wx
    property var island: null
    readonly property var d: Weather.data
    readonly property bool ok: !!d && !!d.ok
    readonly property bool roomy: height >= 205
    readonly property bool wide: width >= 470
    readonly property var days: ok && d.days ? d.days.slice(0, wide ? 7 : 5) : []

    function deg(v) {
        return v === undefined || v === null || isNaN(v) ? "--" : Math.round(v) + "°"
    }
    function aqiColor(v) {
        if (v === undefined || v === null) return Theme.textFaint
        if (v <= 50) return "#36B37E"
        if (v <= 100) return "#D9A400"
        if (v <= 150) return "#F08C2E"
        if (v <= 200) return "#E5484D"
        return "#8E4EC6"
    }

    // Header line: place, update time, refresh -------------------------------------------------------
    Item {
        id: top
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.leftMargin: 18
        anchors.rightMargin: 10
        anchors.topMargin: 10
        height: 26
        Row {
            anchors.left: parent.left
            anchors.right: refresh.left
            anchors.verticalCenter: parent.verticalCenter
            spacing: 5
            Glyph {
                anchors.verticalCenter: parent.verticalCenter
                name: "map-pin"
                size: 14
                color: Theme.accent
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: wx.ok ? (wx.d.city || "当前位置") : "天气"
                color: Theme.text
                font.family: Theme.fontFamily
                font.pixelSize: 13
                font.weight: Font.DemiBold
                elide: Text.ElideRight
                width: Math.min(implicitWidth, parent.width - 120)
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                visible: wx.ok && !!wx.d.updated
                text: "· " + (wx.d.updated || "") + " 更新"
                color: Theme.textFaint
                font.family: Theme.fontFamily
                font.pixelSize: 11
            }
        }
        IconButton {
            id: refresh
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            size: 26
            iconSize: 14
            icon: "refresh"
            tip: wx.ok ? "刷新 · 数据来自" + (wx.d.source || "") : "刷新"
            onClicked: Weather.refresh(true)
            RotationAnimation on rotation {
                running: Weather.loading
                from: 0
                to: 360
                duration: 900
                loops: Animation.Infinite
                onStopped: refresh.rotation = 0
            }
        }
    }

    // Current conditions -------------------------------------------------------------------------------
    Item {
        id: now
        visible: wx.ok
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: top.bottom
        anchors.leftMargin: 16
        anchors.rightMargin: 16
        anchors.topMargin: 2
        height: wx.roomy ? 78 : Math.max(56, wx.height - top.height - 40)
        WeatherIcon {
            id: icon
            anchors.verticalCenter: parent.verticalCenter
            size: Math.min(64, now.height - 6)
            name: wx.d.icon || "cloud"
        }
        Text {
            id: temp
            anchors.left: icon.right
            anchors.leftMargin: 12
            anchors.verticalCenter: parent.verticalCenter
            text: wx.deg(wx.d.temp)
            color: Theme.text
            font.family: Theme.fontFamily
            font.pixelSize: Math.min(50, now.height * 0.7)
            font.weight: Font.Light
        }
        Column {
            anchors.left: temp.right
            anchors.leftMargin: 12
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: 3
            Text {
                width: parent.width
                text: wx.d.text || ""
                color: Theme.text
                font.family: Theme.fontFamily
                font.pixelSize: 15
                font.weight: Font.Medium
                elide: Text.ElideRight
            }
            Text {
                width: parent.width
                text: "体感 " + wx.deg(wx.d.feels) + "   " + wx.deg(wx.d.high) + " / " + wx.deg(wx.d.low)
                color: Theme.textDim
                font.family: Theme.fontFamily
                font.pixelSize: 12
                elide: Text.ElideRight
            }
        }
    }

    // Details chips ----------------------------------------------------------------------------------------
    Flow {
        id: chips
        visible: wx.ok && (wx.roomy || wx.height >= 150)
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: now.bottom
        anchors.leftMargin: 16
        anchors.rightMargin: 16
        anchors.topMargin: 4
        spacing: 6
        clip: true
        height: 24
        component Chip: Rectangle {
            id: chip
            property string icon: ""
            property string text: ""
            property color tint: Theme.textDim
            visible: text !== ""
            height: 22
            width: chipRow.implicitWidth + 16
            radius: 11
            color: Theme.dark ? Qt.rgba(1, 1, 1, 0.06) : Qt.rgba(0, 0, 0, 0.045)
            Row {
                id: chipRow
                anchors.centerIn: parent
                spacing: 4
                Glyph {
                    visible: chip.icon !== ""
                    anchors.verticalCenter: parent.verticalCenter
                    name: chip.icon
                    size: 12
                    color: chip.tint
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: chip.text
                    color: Theme.textDim
                    font.family: Theme.fontFamily
                    font.pixelSize: 11
                }
            }
        }
        Chip {
            icon: "droplet"
            tint: "#4EA4F5"
            text: wx.ok && wx.d.humidity !== undefined && wx.d.humidity !== null ? "湿度 " + Math.round(wx.d.humidity) + "%" : ""
        }
        Chip {
            icon: "wind"
            text: wx.ok ? (wx.d.wind || "") : ""
        }
        Chip {
            icon: "circle"
            tint: wx.aqiColor(wx.d.aqi)
            text: wx.ok && wx.d.aqi !== undefined && wx.d.aqi !== null ? (wx.d.aqiText || "空气质量") + " " + Math.round(wx.d.aqi) : ""
        }
        Chip {
            icon: "sun"
            tint: "#FFB52E"
            text: wx.ok && wx.d.uv ? "紫外线 " + wx.d.uv : ""
        }
    }

    // Forecast ------------------------------------------------------------------------------------------
    Row {
        id: forecast
        visible: wx.ok && wx.roomy && wx.days.length > 0
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.leftMargin: 10
        anchors.rightMargin: 10
        anchors.bottomMargin: 10
        height: Math.min(70, wx.height - chips.y - chips.height - 14)
        Repeater {
            model: wx.days
            delegate: Item {
                required property var modelData
                required property int index
                width: forecast.width / Math.max(1, wx.days.length)
                height: forecast.height
                Rectangle {
                    anchors.fill: parent
                    anchors.margins: 1
                    radius: 10
                    color: index === 0 ? (Theme.dark ? Qt.rgba(1, 1, 1, 0.06) : Qt.rgba(0, 0, 0, 0.04)) : "transparent"
                }
                Column {
                    anchors.centerIn: parent
                    spacing: 2
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: modelData.label || ""
                        color: index === 0 ? Theme.text : Theme.textDim
                        font.family: Theme.fontFamily
                        font.pixelSize: 11
                        font.weight: index === 0 ? Font.DemiBold : Font.Normal
                    }
                    WeatherIcon {
                        anchors.horizontalCenter: parent.horizontalCenter
                        size: Math.max(16, Math.min(24, forecast.height - 40))
                        name: modelData.icon || "cloud"
                        animate: false
                        stroke: 1.7
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: wx.deg(modelData.high) + "<font color='" + Theme.textFaint + "'> " + wx.deg(modelData.low) + "</font>"
                        textFormat: Text.StyledText
                        color: Theme.text
                        font.family: Theme.fontFamily
                        font.pixelSize: 11
                    }
                }
            }
        }
    }

    // No data ---------------------------------------------------------------------------------------------
    Column {
        visible: !wx.ok
        anchors.centerIn: parent
        anchors.verticalCenterOffset: 10
        width: parent.width - 36
        spacing: 8
        WeatherIcon {
            anchors.horizontalCenter: parent.horizontalCenter
            size: 40
            name: "cloud"
            animate: Weather.loading
        }
        Text {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            text: Weather.loading ? "正在获取天气…" : (Weather.status || "暂时无法获取天气")
            color: Theme.textDim
            font.family: Theme.fontFamily
            font.pixelSize: 12
            wrapMode: Text.Wrap
        }
        Text {
            visible: !Weather.loading && Weather.locationNote !== ""
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            text: Weather.locationNote
            color: Theme.textFaint
            font.family: Theme.fontFamily
            font.pixelSize: 11
            wrapMode: Text.Wrap
        }
        Row {
            visible: !Weather.loading
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 8
            GButton {
                text: "重试"
                icon: "refresh"
                kind: "tonal"
                compact: true
                onClicked: Weather.refresh(true)
            }
            GButton {
                text: "设置位置"
                icon: "map-pin"
                kind: "ghost"
                compact: true
                onClicked: Desk.openSettings("widgets:自动定位")
            }
        }
    }
}
