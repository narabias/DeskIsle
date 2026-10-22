// Background media of an island: a picture, an animated GIF or a looping,
// muted video, drawn between the glass and the content with the island's
// rounded corners and a feathered edge (shaders/media.frag).
// Animated media pause while nobody sees the desktop (App.paused), while the
// island is hidden (清屏) or collapsed, and repaint at most media_fps.
import QtQuick
import QtMultimedia

Item {
    id: root
    property var island: null
    readonly property var proxy: island ? island.proxy : null
    readonly property string path: proxy ? proxy.mediaPath : ""
    readonly property string ext: {
        var i = path.lastIndexOf(".")
        return i >= 0 ? path.substring(i + 1).toLowerCase() : ""
    }
    readonly property bool isVideo: ["mp4", "webm", "mov", "mkv", "avi", "wmv", "m4v"].indexOf(ext) >= 0
    readonly property bool isAnimated: ext === "gif"
    readonly property bool isStill: path !== "" && !isVideo && !isAnimated
    readonly property string url: {
        if (path === "") {
            return ""
        }
        if (path.indexOf("://") > 0) {
            return path
        }
        var p = path.replace(/\\/g, "/")
        return (p.charAt(0) === "/" ? "file://" : "file:///") + encodeURI(p).replace(/#/g, "%23").replace(/\?/g, "%3F")
    }
    readonly property bool running: visible && !App.paused && !!island && !island.deskHidden && !island.collapsed
    readonly property int fps: Math.max(1, Math.min(60, Number(Desk.prefs.media_fps) || 24))
    readonly property bool gpu: GraphicsInfo.api !== GraphicsInfo.Software && GraphicsInfo.api !== GraphicsInfo.Unknown

    Item {
        id: content
        anchors.fill: parent
        opacity: root.gpu ? 1 : (root.proxy ? root.proxy.mediaOpacity : 1)

        Image {
            anchors.fill: parent
            visible: root.isStill
            source: root.isStill ? root.url : ""
            fillMode: Image.PreserveAspectCrop
            asynchronous: true
            cache: false
            smooth: true
            sourceSize.width: 1600
            onStatusChanged: if (status === Image.Ready) tex.scheduleUpdate()
        }
        AnimatedImage {
            anchors.fill: parent
            visible: root.isAnimated
            source: root.isAnimated ? root.url : ""
            fillMode: Image.PreserveAspectCrop
            asynchronous: true
            cache: false
            playing: root.running
        }
        Loader {
            anchors.fill: parent
            active: root.isVideo
            sourceComponent: Item {
                MediaPlayer {
                    id: player
                    source: root.url
                    loops: MediaPlayer.Infinite
                    videoOutput: output
                    Component.onCompleted: if (root.running) play()
                }
                VideoOutput {
                    id: output
                    anchors.fill: parent
                    fillMode: VideoOutput.PreserveAspectCrop
                }
                Connections {
                    target: root
                    function onRunningChanged() {
                        if (root.running) {
                            player.play()
                        } else {
                            player.pause()
                        }
                    }
                }
            }
        }
    }

    ShaderEffectSource {
        id: tex
        sourceItem: root.gpu ? content : null
        hideSource: root.gpu
        visible: false
        live: root.isStill
        smooth: true
    }
    Timer {
        interval: Math.round(1000 / root.fps)
        repeat: true
        running: root.gpu && root.running && !root.isStill
        onTriggered: tex.scheduleUpdate()
    }
    ShaderEffect {
        anchors.fill: parent
        visible: root.gpu
        property var source: tex
        property size itemSize: Qt.size(width, height)
        property real radius: root.island ? root.island.radius : 0
        property real feather: root.proxy ? Math.max(0, root.proxy.mediaFeather) : 0
        property real amount: root.proxy ? Math.max(0, Math.min(1, root.proxy.mediaOpacity)) : 1
        fragmentShader: "shaders/media.frag.qsb"
    }
}
