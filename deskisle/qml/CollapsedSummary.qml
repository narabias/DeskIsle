// One-line summary for a folded (collapsed) widget island.  Widgets have no
// header, so without this the island was just an empty glass bar after 收拢.
// Weather: icon + condition + temperature.  Media: "正在播放：歌名 - 歌手",
// a small audio line and prev / play / next.  Todo: open item count.
import QtQuick

Item {
    id: summary
    property var island: null
    readonly property string wid: island && island.proxy ? island.proxy.widget : ""
    readonly property var wx: Weather.data
    readonly property bool wxOk: !!wx && !!wx.ok
    readonly property var todoAll: (Todo.revision, island && island.uid !== "" ? Todo.list(island.uid) : [])
    readonly property int todoOpen: {
        var n = 0
        for (var i = 0; i < todoAll.length; ++i) {
            if (!todoAll[i].done) {
                n++
            }
        }
        return n
    }
    readonly property bool compact: width < 260

    // Weather --------------------------------------------------------------------------------------
    Row {
        visible: summary.wid === "weather"
        anchors.fill: parent
        anchors.leftMargin: 16
        anchors.rightMargin: 12
        spacing: 10
        WeatherIcon {
            anchors.verticalCenter: parent.verticalCenter
            size: Math.max(18, Math.min(26, summary.height - 12))
            name: summary.wxOk && summary.wx.icon ? summary.wx.icon : "cloud"
            animate: false
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: summary.wxOk ? (summary.wx.text || "天气") : "天气"
            color: Theme.text
            font.family: Theme.fontFamily
            font.pixelSize: 14
            font.weight: Font.DemiBold
            elide: Text.ElideRight
            width: Math.min(implicitWidth, summary.width * 0.42)
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: summary.wxOk ? Math.round(summary.wx.temp) + "°" : "--"
            color: Theme.text
            font.family: Theme.fontFamily
            font.pixelSize: 17
            font.weight: Font.Bold
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            visible: !summary.compact && summary.wxOk && !!summary.wx.city
            text: summary.wx.city || ""
            color: Theme.textFaint
            font.family: Theme.fontFamily
            font.pixelSize: 12
            elide: Text.ElideRight
            width: Math.min(implicitWidth, summary.width * 0.2)
        }
    }

    // Now playing ----------------------------------------------------------------------------------
    Item {
        visible: summary.wid === "media"
        anchors.fill: parent
        anchors.leftMargin: 10
        anchors.rightMargin: 8
        IconButton {
            id: play
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            size: 28
            iconSize: 16
            icon: Player.playing ? "player-pause" : "player-play"
            tip: Player.playing ? "暂停" : "播放"
            onClicked: Player.playPause()
        }
        IconButton {
            id: next
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            size: 28
            iconSize: 15
            icon: "player-skip-forward"
            tip: "下一首"
            enabled: Player.canNext
            onClicked: Player.next()
        }
        IconButton {
            id: prev
            anchors.right: next.left
            anchors.rightMargin: 2
            anchors.verticalCenter: parent.verticalCenter
            size: 28
            iconSize: 15
            icon: "player-skip-back"
            tip: "上一首"
            enabled: Player.canPrevious
            onClicked: Player.previous()
        }
        Spectrum {
            id: miniLine
            anchors.right: prev.left
            anchors.rightMargin: 8
            anchors.verticalCenter: parent.verticalCenter
            visible: !summary.compact
            width: Math.min(72, summary.width * 0.2)
            height: 14
            playing: Player.playing
            color: Player.cover !== "" ? (Theme.dark ? Qt.lighter(Player.accent, 1.25) : Player.accent)
                                       : Theme.accent
        }
        Text {
            anchors.left: play.right
            anchors.leftMargin: 8
            anchors.right: summary.compact ? prev.left : miniLine.left
            anchors.rightMargin: 8
            anchors.verticalCenter: parent.verticalCenter
            text: {
                if (!Player.hasSession) {
                    return "正在播放：没有媒体在播放"
                }
                var t = Player.title || "未知曲目"
                if (Player.artist !== "") {
                    t += " - " + Player.artist
                }
                return "正在播放：" + t
            }
            color: Theme.text
            font.family: Theme.fontFamily
            font.pixelSize: 13
            font.weight: Font.DemiBold
            elide: Text.ElideRight
        }
    }

    // Todo -----------------------------------------------------------------------------------------
    Row {
        visible: summary.wid === "todo"
        anchors.fill: parent
        anchors.leftMargin: 16
        anchors.rightMargin: 16
        spacing: 10
        Glyph {
            anchors.verticalCenter: parent.verticalCenter
            name: "checklist"
            size: 18
            color: Theme.accent
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: "待办"
            color: Theme.text
            font.family: Theme.fontFamily
            font.pixelSize: 14
            font.weight: Font.DemiBold
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: summary.todoOpen > 0 ? summary.todoOpen + " 个待办" : "当前没有待办"
            color: summary.todoOpen > 0 ? Theme.accent : Theme.textDim
            font.family: Theme.fontFamily
            font.pixelSize: 13
            elide: Text.ElideRight
        }
    }

    // Everything else (clock, custom): the widget name keeps the bar readable.
    Text {
        visible: summary.wid !== "weather" && summary.wid !== "media" && summary.wid !== "todo"
        anchors.fill: parent
        anchors.leftMargin: 16
        anchors.rightMargin: 16
        verticalAlignment: Text.AlignVCenter
        text: summary.island && summary.island.proxy ? summary.island.proxy.title : ""
        color: Theme.textDim
        font.family: Theme.fontFamily
        font.pixelSize: 13
        elide: Text.ElideRight
    }
}
