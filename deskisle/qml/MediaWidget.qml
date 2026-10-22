// Now playing widget (Windows media sessions / GSMTC): cover with a tint
// taken from it, title / artist / album, seek bar and transport controls,
// and a chip that switches between players when several are open.
// 2.0.1: cover cross-fade, ambient glow from the cover, eased cover colour,
// wide / tall layouts, neutral placeholder and the 网易云 SMTC hint.
import QtQuick
import QtQuick.Effects

Item {
    id: media
    property var island: null
    readonly property bool has: Player.available && Player.hasSession
    // Wide: cover on the left; tall: cover on top, text centred below (2.0.1).
    readonly property bool stacked: height >= 250 && width < height * 1.15
    readonly property real coverSize: stacked ? Math.max(64, Math.min(width - 56, height - 196 - media.footerHeight, 220))
                                              : Math.max(48, Math.min(height - media.footerHeight - 24, width * 0.38, 150))
    readonly property real radius: island ? island.radius : Theme.radius
    // Software rendering (no shaders): plain images instead of the masked / blurred effects.
    readonly property bool gpu: GraphicsInfo.api !== GraphicsInfo.Software && GraphicsInfo.api !== GraphicsInfo.Unknown
    property real pos: 0
    // Accent from the cover (Player.accent), eased so a new track does not flash.
    property color tint: Player.cover !== "" ? Player.accent : Theme.accent
    Behavior on tint { ColorAnimation { duration: Theme.ms(600) } }
    readonly property color tintInk: (0.299 * tint.r + 0.587 * tint.g + 0.114 * tint.b) > 0.68 ? "#15181D" : "#FFFFFF"

    // Audio line + short lyrics ---------------------------------------------------------------------
    // The line runs along the bottom edge; two short lyric lines sit above it when the island is
    // wide enough.  Everything below is hidden on small islands instead of squeezing the controls.
    readonly property bool showLine: media.has && media.width >= 240 && media.height >= 168
                                     && (!media.stacked || media.height >= 300)
    readonly property real lineHeight: media.showLine ? Math.max(16, Math.min(46, Math.round(media.height * 0.12))) : 0
    readonly property real lineInset: media.showLine ? 10 : 0
    readonly property real lineBlock: media.showLine ? media.lineHeight + 8 : 0
    readonly property real infoHeight: 128   // rows of text + seek + transport, for the room check
    // Lyrics scale with the widget: 11 px on a 440 px panel, up to 21 px on a full desk widget.
    readonly property real lyricSize: Math.round(Math.max(11, Math.min(21, media.width / 46)))
    readonly property real lyricSubSize: Math.max(10, media.lyricSize - 3)
    readonly property real lyricBlock: Math.round(media.lyricSize * 1.35 + media.lyricSubSize * 1.35 + 2)
    readonly property bool lyricReady: media.lyricLines.length > 0 && media.lyricIndex >= 0
    readonly property bool lyricsRoom: media.showLine && !media.stacked && media.width >= 320
                                       && media.height - media.lineBlock - media.lyricBlock - 8 >= media.infoHeight + 10
    readonly property bool showLyrics: media.lyricsRoom   // reserve the space even before lyrics arrive: no resize when they load
    readonly property real lyricsHeight: media.showLyrics ? media.lyricBlock : 0
    readonly property real footerHeight: media.lineBlock + media.lyricsHeight + media.lineInset
    readonly property string songKey: Player.title + "\u0001" + Player.artist
    property var lyricLines: []
    property int lyricIndex: -1
    property var lyricCache: ({})

    readonly property string lyricNow: {
        if (lyricIndex < 0 || lyricIndex >= lyricLines.length) {
            return ""
        }
        return lyricLines[lyricIndex].s !== "" ? lyricLines[lyricIndex].s : "♪"
    }
    readonly property string lyricSub: {
        if (lyricIndex < 0 || lyricIndex >= lyricLines.length) {
            return ""
        }
        var tr = lyricLines[lyricIndex].tr
        if (tr) {
            return tr
        }
        for (var i = lyricIndex + 1; i < lyricLines.length; ++i) {
            if (lyricLines[i].s !== "") {
                return lyricLines[i].s
            }
        }
        return ""
    }

    function lrcRows(text) {
        var rows = String(text || "").replace(/\r/g, "").split("\n")
        var out = []
        for (var i = 0; i < rows.length; ++i) {
            var m = rows[i].match(/^\[(\d+):(\d+(?:\.\d+)?)\]\s*(.*)$/)
            if (!m) {
                continue
            }
            out.push({ t: parseInt(m[1], 10) * 60 + parseFloat(m[2]), s: m[3].replace(/\s+$/, "") })
        }
        return out
    }
    function lrcToLines(text) {
        return lrcRows(text).sort(function(a, b) { return a.t - b.t })
    }
    // NetEase returns the original LRC plus a translated one (tlyric); pair them by time.
    function netEaseToLines(lrc, tlrc) {
        var tr = {}
        var trows = lrcRows(tlrc)
        for (var i = 0; i < trows.length; ++i) {
            if (trows[i].s !== "") {
                tr[Math.round(trows[i].t * 10)] = trows[i].s
            }
        }
        var rows = lrcRows(lrc)
        var out = []
        for (var j = 0; j < rows.length; ++j) {
            var s = rows[j].s
            if (s === "" || /^(作词|作曲|编曲|作詞|编曲|制作人|混音|母带|录音)/.test(s)) {
                continue
            }
            out.push({ t: rows[j].t, s: s, tr: tr[Math.round(rows[j].t * 10)] || "" })
        }
        out.sort(function(a, b) { return a.t - b.t })
        return out
    }
    function normText(s) {
        return String(s || "").toLowerCase()
                .replace(/[\s\-–—·・.,，、。:：()（）\[\]【】'"“”‘’!！?？&+\/]/g, "")
    }
    function rankNetEaseSongs(list, title, artist) {
        var want = normText(title)
        var wantArtist = normText(artist)
        var out = []
        for (var i = 0; i < list.length; ++i) {
            var song = list[i]
            if (!song || !song.id) {
                continue
            }
            var name = normText(song.name)
            var score = 0
            if (name === want) {
                score += 60
            } else if (want !== "" && (name.indexOf(want) >= 0 || want.indexOf(name) >= 0)) {
                score += 30
            } else {
                score -= 20
            }
            var who = []
            var ars = song.ar || song.artists || []
            for (var k = 0; k < ars.length; ++k) {
                who.push(normText(ars[k].name))
            }
            if (wantArtist !== "" && who.join("/").indexOf(wantArtist) >= 0) {
                score += 40
            }
            var ms = Number(song.dt || song.duration || 0)
            if (ms > 0 && Player.duration > 0) {
                score += Math.max(0, 20 - Math.abs(ms / 1000 - Player.duration))
            }
            if (score >= 30) {
                out.push({ score: score, song: song })
            }
        }
        out.sort(function(a, b) { return b.score - a.score })
        return out
    }
    function applyLyrics(lines) {
        lyricIndex = -1
        lyricLines = lines
        syncLyric()
    }
    function syncLyric() {
        if (lyricLines.length === 0) {
            return
        }
        var p = Player.currentPosition()
        var idx = -1
        for (var i = 0; i < lyricLines.length; ++i) {
            if (lyricLines[i].t <= p + 0.05) {
                idx = i
            } else {
                break
            }
        }
        if (idx !== lyricIndex) {
            lyricIndex = idx
        }
    }
    function finishLyrics(key, lines) {
        if (!lines || lines.length === 0) {
            return false
        }
        media.lyricCache[key] = lines
        if (media.lyricFor === key) {
            media.applyLyrics(lines)
        }
        return true
    }
    function xhrGet(url, done, referer) {
        var xhr = new XMLHttpRequest()
        xhr.open("GET", url)
        xhr.timeout = 8000
        if (referer) {
            try {
                xhr.setRequestHeader("Referer", referer)
            } catch (e) {
            }
        }
        xhr.onreadystatechange = function() {
            if (xhr.readyState === XMLHttpRequest.DONE) {
                done(xhr.status, xhr.responseText)
            }
        }
        xhr.send()
    }
    // NetEase first (it has most of the songs people play here, plus translations), lrclib as a fallback.
    function fetchNetEase(key, title, artist) {
        var q = encodeURIComponent((title + " " + artist).trim())
        media.xhrGet("https://music.163.com/api/cloudsearch/pc?s=" + q + "&type=1&limit=8", function(status, body) {
            if (media.lyricFor !== key) {
                return
            }
            var ranked = []
            if (status === 200) {
                try {
                    var data = JSON.parse(body)
                    ranked = media.rankNetEaseSongs((data.result && data.result.songs) || [], title, artist)
                } catch (e) {
                }
            }
            media.tryNetEaseSong(key, ranked, 0)
        }, "https://music.163.com/")
    }
    // Several hits can share a name/artist (remaster, live, an entry without lyrics): walk the
    // ranked list until one really has synced lyrics, then fall back to lrclib.
    function tryNetEaseSong(key, ranked, index) {
        if (media.lyricFor !== key) {
            return
        }
        if (index >= ranked.length || index >= 4) {
            media.fetchLrclib(key)
            return
        }
        var song = ranked[index].song
        media.xhrGet("https://music.163.com/api/song/lyric?id=" + song.id + "&lv=1&kv=1&tv=-1", function(st, txt) {
            if (media.lyricFor !== key) {
                return
            }
            var lines = []
            try {
                var obj = JSON.parse(txt)
                lines = media.netEaseToLines(obj.lrc && obj.lrc.lyric, obj.tlyric && obj.tlyric.lyric)
            } catch (e) {
            }
            if (media.finishLyrics(key, lines)) {
                return
            }
            media.tryNetEaseSong(key, ranked, index + 1)
        }, "https://music.163.com/")
    }
    function fetchLrclib(key) {
        var url = "https://lrclib.net/api/search?track_name=" + encodeURIComponent(Player.title)
        if (Player.artist !== "") {
            url += "&artist_name=" + encodeURIComponent(Player.artist)
        }
        media.xhrGet(url, function(status, body) {
            if (media.lyricFor !== key || status !== 200) {
                return
            }
            var lines = []
            try {
                var list = JSON.parse(body)
                var best = null
                var bestGap = 1e9
                for (var i = 0; i < list.length; ++i) {
                    var it = list[i]
                    if (!it || !it.syncedLyrics) {
                        continue
                    }
                    var gap = Math.abs((Number(it.duration) || 0) - Player.duration)
                    if (!best || (it.duration > 0 && Player.duration > 0 && gap < bestGap)) {
                        best = it
                        bestGap = gap
                    }
                }
                if (best) {
                    lines = media.lrcToLines(best.syncedLyrics)
                }
            } catch (e) {
            }
            media.finishLyrics(key, lines)
        })
    }
    function fetchLyrics() {
        if (!media.has || Player.title === "") {
            return
        }
        var key = media.songKey
        if (media.lyricFor === key) {
            return
        }
        media.lyricFor = key
        media.lyricLines = []
        media.lyricIndex = -1
        if (media.lyricCache.hasOwnProperty(key)) {
            media.applyLyrics(media.lyricCache[key])
            return
        }
        media.fetchNetEase(key, Player.title, Player.artist)
    }

    property string lyricFor: ""
    // A player may ignore repeat / shuffle over GSMTC (网易云音乐 does): say so instead of
    // leaving a button that seems dead.
    property int repeatTry: -1
    Timer {
        id: repeatWatch
        interval: 800
        onTriggered: {
            if (media.repeatTry >= 0 && Player.repeat !== media.repeatTry) {
                Desk.postNotice("循环模式", "当前播放器没有通过系统媒体控制提供循环切换。", "info")
            }
            media.repeatTry = -1
        }
    }
    onSongKeyChanged: lyricTimer.restart()
    Timer {
        id: lyricTimer
        interval: 900
        onTriggered: media.fetchLyrics()
    }
    Timer {
        interval: 150
        repeat: true
        running: media.visible && Player.playing && media.lyricLines.length > 0
        onTriggered: media.syncLyric()
    }

    function fmt(s) {
        if (!(s > 0)) {
            return "0:00"
        }
        s = Math.floor(s)
        var h = Math.floor(s / 3600)
        var m = Math.floor((s % 3600) / 60)
        var sec = s % 60
        return (h > 0 ? h + ":" + (m < 10 ? "0" : "") : "") + m + ":" + (sec < 10 ? "0" : "") + sec
    }
    function sync() {
        pos = Player.currentPosition()
    }
    Timer {
        // Often enough to move the knob about a pixel per tick (at most 1 s, at least 120 ms):
        // smooth without keeping the desktop layer rendering every frame.
        interval: Math.max(120, Math.min(1000, Player.duration > 0 ? Player.duration * 1000 / Math.max(60, seek.width) : 1000))
        repeat: true
        running: media.visible && Player.playing && !App.paused && !seek.dragging
        triggeredOnStart: true
        onTriggered: media.sync()
    }
    // Re-read the position whenever the player reports a change; resuming after a pause
    // re-anchors the lyric line so it cannot stay offset.
    property bool wasPlaying: false
    Connections {
        target: Player
        function onChanged() {
            media.sync()
            if (Player.playing && !media.wasPlaying) {
                media.syncLyric()
            }
            media.wasPlaying = Player.playing
        }
    }
    Component.onCompleted: {
        sync()
        loadCover()
        lyricTimer.restart()
    }

    // Covers cross-fade: the next one loads into the hidden slot, then swaps in.
    readonly property string coverUrl: Player.cover
    property int front: -1                  // 0 = slot A, 1 = slot B, -1 = placeholder
    onCoverUrlChanged: loadCover()
    function loadCover() {
        if (coverUrl === "") {
            front = -1
            return
        }
        var slot = front === 0 ? coverB : coverA
        slot.source = coverUrl
        if (slot.status === Image.Ready) {
            front = slot === coverA ? 0 : 1
        }
    }
    function slotReady(slot) {
        if (slot.status === Image.Ready && String(slot.source) === coverUrl) {
            front = slot === coverA ? 0 : 1
        }
    }
    Image {
        id: coverA
        visible: false
        sourceSize.width: 300
        sourceSize.height: 300
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        cache: false
        onStatusChanged: media.slotReady(coverA)
    }
    Image {
        id: coverB
        visible: false
        sourceSize.width: 300
        sourceSize.height: 300
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        cache: false
        onStatusChanged: media.slotReady(coverB)
    }

    // Ambient glow: the cover shrunk to a few pixels, stretched and blurred under the
    // content (the "album art glow" of Apple Music / WinIsland), cross-faded with the cover.
    Item {
        id: ambientSrc
        anchors.fill: parent
        visible: false
        layer.enabled: media.gpu && media.has && media.front >= 0
        Image {
            anchors.fill: parent
            source: coverA.source
            sourceSize.width: 24
            sourceSize.height: 24
            fillMode: Image.PreserveAspectCrop
            smooth: true
            cache: false
            opacity: media.front === 0 ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: Theme.ms(600) } }
        }
        Image {
            anchors.fill: parent
            source: coverB.source
            sourceSize.width: 24
            sourceSize.height: 24
            fillMode: Image.PreserveAspectCrop
            smooth: true
            cache: false
            opacity: media.front === 1 ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: Theme.ms(600) } }
        }
    }
    Rectangle {
        id: ambientMask
        anchors.fill: parent
        radius: media.radius
        visible: false
        layer.enabled: true
    }
    MultiEffect {
        anchors.fill: parent
        source: ambientSrc
        visible: media.gpu && media.has && media.front >= 0
        opacity: Theme.dark ? 0.55 : 0.42
        autoPaddingEnabled: false
        blurEnabled: true
        blur: 1.0
        blurMax: 48
        saturation: 0.15
        maskEnabled: true
        maskSource: ambientMask
        maskThresholdMin: 0.5
        maskSpreadAtMin: 1.0
    }
    // Light wash in the cover colour (also when the glow is unavailable, e.g. software rendering).
    Rectangle {
        anchors.fill: parent
        radius: media.radius
        visible: media.has
        opacity: 0.9
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0; color: Qt.rgba(media.tint.r, media.tint.g, media.tint.b, Theme.dark ? 0.26 : 0.18) }
            GradientStop { position: 0.8; color: Qt.rgba(media.tint.r, media.tint.g, media.tint.b, 0.0) }
        }
    }

    // Cover ----------------------------------------------------------------------------------------------
    Item {
        id: coverBox
        visible: media.has
        width: media.coverSize
        height: media.coverSize
        x: media.stacked ? Math.round((media.width - width) / 2) : 14
        y: media.stacked ? 18 : Math.max(8, Math.round((media.height - media.footerHeight - height) / 2))
        Rectangle {
            // Neutral placeholder (no more accent-coloured square while the art loads).
            anchors.fill: parent
            radius: 14
            opacity: media.front < 0 ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: Theme.ms(240) } }
            color: Theme.dark ? Qt.rgba(1, 1, 1, 0.08) : Qt.rgba(0, 0, 0, 0.06)
            border.width: 1
            border.color: Theme.hairline
            Glyph {
                anchors.centerIn: parent
                name: "music"
                size: parent.width * 0.38
                color: Theme.textFaint
                stroke: 1.5
            }
        }
        Rectangle {
            id: coverMask
            anchors.fill: parent
            radius: 14
            visible: false
            layer.enabled: true
        }
        // Shadow and mask are separate: a MultiEffect shadow pads the output, which misaligns the mask.
        RectangularShadow {
            anchors.fill: parent
            opacity: media.front >= 0 ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: Theme.ms(240) } }
            radius: 14
            blur: 18
            offset.y: 4
            color: Qt.rgba(0, 0, 0, Theme.dark ? 0.45 : 0.28)
        }
        MultiEffect {
            anchors.fill: parent
            source: coverA
            visible: opacity > 0.01
            opacity: media.front === 0 ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: Theme.ms(320) } }
            maskEnabled: true
            maskSource: coverMask
            maskThresholdMin: 0.5
            maskSpreadAtMin: 1.0
        }
        MultiEffect {
            anchors.fill: parent
            source: coverB
            visible: opacity > 0.01
            opacity: media.front === 1 ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: Theme.ms(320) } }
            maskEnabled: true
            maskSource: coverMask
            maskThresholdMin: 0.5
            maskSpreadAtMin: 1.0
        }
        Image {
            anchors.fill: parent
            visible: !media.gpu && media.front >= 0
            source: media.front === 1 ? coverB.source : coverA.source
            sourceSize.width: 300
            sourceSize.height: 300
            fillMode: Image.PreserveAspectCrop
            cache: false
        }
        // Paused: settle back a little (no bounce).
        scale: Player.playing ? 1 : 0.96
        Behavior on scale { NumberAnimation { duration: Theme.ms(320); easing.type: Easing.OutCubic } }
    }

    // Text + controls ------------------------------------------------------------------------------------
    Column {
        id: info
        visible: media.has
        x: media.stacked ? 18 : coverBox.x + coverBox.width + 14
        width: media.width - x - (media.stacked ? 18 : 14)
        y: media.stacked ? coverBox.y + coverBox.height + 12
                         : Math.max(6, Math.round((media.height - media.footerHeight - height) / 2))
        Behavior on y { NumberAnimation { duration: Theme.ms(220); easing.type: Easing.OutCubic } }
        spacing: 2
        // A new track fades its text in (instead of snapping).
        readonly property string track: Player.title + "\u0001" + Player.artist
        onTrackChanged: trackFade.restart()
        ParallelAnimation {
            id: trackFade
            NumberAnimation { target: titleRow; property: "opacity"; from: 0; to: 1; duration: Theme.ms(320); easing.type: Easing.OutCubic }
            NumberAnimation { target: subText; property: "opacity"; from: 0; to: 1; duration: Theme.ms(420); easing.type: Easing.OutCubic }
        }
        Item {
            id: titleRow
            width: parent.width
            height: titleText.implicitHeight
            Text {
                id: titleText
                anchors.left: parent.left
                anchors.right: appChip.visible ? appChip.left : parent.right
                anchors.rightMargin: appChip.visible ? 6 : 0
                horizontalAlignment: media.stacked && !appChip.visible ? Text.AlignHCenter : Text.AlignLeft
                text: Player.title || "未知曲目"
                color: Theme.text
                font.family: Theme.fontFamily
                font.pixelSize: 15
                font.weight: Font.DemiBold
                elide: Text.ElideRight
            }
            Rectangle {
                id: appChip
                visible: Player.app !== ""
                anchors.right: parent.right
                anchors.verticalCenter: titleText.verticalCenter
                width: Math.min(appText.implicitWidth + (Player.sessions.length > 1 ? 26 : 14), parent.width * 0.42)
                height: 18
                radius: 9
                color: appMouse.containsMouse ? Theme.hover : (Theme.dark ? Qt.rgba(1, 1, 1, 0.08) : Qt.rgba(0, 0, 0, 0.06))
                Row {
                    anchors.centerIn: parent
                    spacing: 2
                    Text {
                        id: appText
                        anchors.verticalCenter: parent.verticalCenter
                        width: Math.min(implicitWidth, appChip.width - (Player.sessions.length > 1 ? 24 : 12))
                        text: Player.app
                        color: Theme.textDim
                        font.family: Theme.fontFamily
                        font.pixelSize: 10
                        elide: Text.ElideRight
                    }
                    Glyph {
                        visible: Player.sessions.length > 1
                        anchors.verticalCenter: parent.verticalCenter
                        name: "arrows-shuffle"
                        size: 10
                        color: Theme.textDim
                    }
                }
                MouseArea {
                    id: appMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    enabled: Player.sessions.length > 1
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        var list = Player.sessions
                        var at = 0
                        for (var i = 0; i < list.length; i++) {
                            if (list[i].id === Player.sessionId) {
                                at = i
                            }
                        }
                        Player.selectSession(list[(at + 1) % list.length].id)
                    }
                }
                Tip {
                    text: Player.sessions.length > 1 ? "切换播放器（" + Player.sessions.length + " 个）" : ""
                    shown: appMouse.containsMouse
                }
            }
        }
        Text {
            id: subText
            width: parent.width
            horizontalAlignment: media.stacked ? Text.AlignHCenter : Text.AlignLeft
            text: [Player.artist, Player.album].filter(function(s) { return s !== "" }).join(" · ")
            color: Theme.textDim
            font.family: Theme.fontFamily
            font.pixelSize: 12
            elide: Text.ElideRight
        }
        Item { width: 1; height: Math.max(2, media.height * 0.03) }
        GSlider {
            id: seek
            visible: Player.duration > 0
            width: parent.width + 8
            x: -4
            from: 0
            to: Math.max(1, Player.duration)
            value: media.pos
            fill: media.tint
            enabled: Player.canSeek
            onCommitted: (v) => { Player.seek(v); media.pos = v }
        }
        Item {
            visible: Player.duration > 0
            width: parent.width
            height: 14
            Text {
                anchors.left: parent.left
                text: media.fmt(seek.dragging ? seek.shown : media.pos)
                color: Theme.textFaint
                font.family: Theme.fontFamily
                font.pixelSize: 10
            }
            Text {
                anchors.right: parent.right
                text: media.fmt(Player.duration)
                color: Theme.textFaint
                font.family: Theme.fontFamily
                font.pixelSize: 10
            }
        }
        Item { width: 1; height: 2 }
        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: Math.max(2, Math.min(10, (info.width - 180) / 4))
            IconButton {
                anchors.verticalCenter: parent.verticalCenter
                visible: info.width > 190
                icon: "arrows-shuffle"
                tip: Player.shuffle ? "随机播放：开" : "随机播放：关"
                size: 30
                iconSize: 15
                checked: Player.shuffle
                onClicked: Player.setShuffle(!Player.shuffle)
            }
            IconButton {
                anchors.verticalCenter: parent.verticalCenter
                icon: "player-skip-back"
                tip: "上一首"
                size: 34
                iconSize: 18
                enabled: Player.canPrevious
                onClicked: Player.previous()
            }
            Rectangle {
                id: playBtn
                anchors.verticalCenter: parent.verticalCenter
                width: 42
                height: 42
                radius: 21
                color: playMouse.pressed ? Qt.darker(media.tint, 1.15) : media.tint
                scale: playMouse.pressed ? 0.92 : (playMouse.containsMouse ? 1.05 : 1)
                Behavior on scale { NumberAnimation { duration: Theme.ms(120) } }
                Glyph {
                    anchors.centerIn: parent
                    anchors.horizontalCenterOffset: Player.playing ? 0 : 1
                    name: Player.playing ? "player-pause" : "player-play"
                    size: 20
                    filled: true
                    color: media.tintInk
                }
                MouseArea {
                    id: playMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: Player.playPause()
                }
            }
            IconButton {
                anchors.verticalCenter: parent.verticalCenter
                icon: "player-skip-forward"
                tip: "下一首"
                size: 34
                iconSize: 18
                enabled: Player.canNext
                onClicked: Player.next()
            }
            IconButton {
                id: repeatBtn
                anchors.verticalCenter: parent.verticalCenter
                visible: info.width > 190
                icon: "repeat"
                tip: Player.repeat === 1 ? "单曲循环" : (Player.repeat === 2 ? "列表循环" : "不循环")
                size: 30
                iconSize: 15
                checked: Player.repeat !== 0
                onClicked: {
                    media.repeatTry = (Player.repeat + 1) % 3
                    Player.setRepeat(media.repeatTry)
                    repeatWatch.restart()
                }
                Text {
                    visible: Player.repeat === 1
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.rightMargin: 4
                    anchors.topMargin: 3
                    text: "1"
                    color: Theme.accent
                    font.family: Theme.fontFamily
                    font.pixelSize: 8
                    font.weight: Font.Bold
                }
            }
        }
    }

    // Audio line + short lyrics, along the bottom edge -----------------------------------------------
    Item {
        id: footer
        visible: media.has && media.footerHeight > 0
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: media.footerHeight

        Column {
            id: lyricBox
            visible: media.showLyrics
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.leftMargin: 16
            anchors.rightMargin: 16
            anchors.bottom: line.top
            anchors.bottomMargin: 2
            spacing: 1
            Text {
                width: parent.width
                text: media.lyricNow
                color: Theme.text
                horizontalAlignment: Text.AlignHCenter
                elide: Text.ElideRight
                font.family: Theme.fontFamily
                font.pixelSize: media.lyricSize
                font.weight: Font.DemiBold
            }
            Text {
                width: parent.width
                visible: text !== ""
                text: media.lyricSub
                color: Theme.textDim
                opacity: 0.8
                horizontalAlignment: Text.AlignHCenter
                elide: Text.ElideRight
                font.family: Theme.fontFamily
                font.pixelSize: media.lyricSubSize
            }
        }
        Spectrum {
            id: line
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.bottomMargin: media.lineInset
            anchors.leftMargin: 16
            anchors.rightMargin: 16
            height: media.lineHeight
            barWidth: Math.max(2, Math.round(media.lineHeight / 7))
            barGap: Math.max(2, Math.round(media.lineHeight / 7))
            playing: Player.playing
            color: Theme.dark ? Qt.lighter(media.tint, 1.25) : media.tint
        }
    }

    // Nothing playing -------------------------------------------------------------------------------------
    Row {
        visible: !media.has
        anchors.centerIn: parent
        width: parent.width - 40
        spacing: 14
        Rectangle {
            width: 52
            height: 52
            radius: 14
            color: Theme.dark ? Qt.rgba(1, 1, 1, 0.06) : Qt.rgba(0, 0, 0, 0.05)
            Glyph {
                anchors.centerIn: parent
                name: "music"
                size: 24
                color: Theme.textFaint
            }
        }
        Column {
            width: parent.width - 66
            anchors.verticalCenter: parent.verticalCenter
            spacing: 4
            Text {
                width: parent.width
                text: Player.available ? "现在没有媒体在播放" : "无法读取系统媒体信息"
                color: Theme.text
                font.family: Theme.fontFamily
                font.pixelSize: 14
                font.weight: Font.DemiBold
                elide: Text.ElideRight
            }
            Text {
                width: parent.width
                text: !Player.available ? (Player.error || "需要 Windows 10 / 11 的系统媒体控制（GSMTC）。")
                      : Player.hint !== "" ? Player.hint
                      : "在任意播放器或浏览器里播放音乐、视频，这里会自动显示并可以控制。"
                color: Player.hint !== "" ? Theme.text : Theme.textDim
                font.family: Theme.fontFamily
                font.pixelSize: 11
                wrapMode: Text.Wrap
                maximumLineCount: 4
                elide: Text.ElideRight
            }
        }
    }
}
