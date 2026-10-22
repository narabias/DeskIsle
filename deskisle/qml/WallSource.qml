// Backdrop textures of one monitor for the glass shader.
// Two images are used in turn so a new wallpaper frame (live wallpapers update
// several times a second) never shows an empty texture while it loads.
import QtQuick
import QtQuick.Effects

Item {
    id: root
    property string source: ""
    property real blurAmount: 1.0
    readonly property Item sharp: front === 0 ? imgA : imgB
    readonly property Item blurred: blurTex
    readonly property bool ready: sharp.status === Image.Ready
    property int front: 0
    property int loading: -1
    width: sharp.implicitWidth > 0 ? sharp.implicitWidth : 16
    height: sharp.implicitHeight > 0 ? sharp.implicitHeight : 9

    onSourceChanged: {
        if (source === "") {
            return
        }
        var back = front === 0 ? imgB : imgA
        loading = front === 0 ? 1 : 0
        back.source = source
        if (back.status === Image.Ready) {
            front = loading
            loading = -1
        }
    }
    function settle(which) {
        if (which === loading) {
            front = which
            loading = -1
        }
    }

    Image {
        id: imgA
        visible: false
        cache: false
        asynchronous: true
        smooth: true
        mipmap: false
        onStatusChanged: if (status === Image.Ready) root.settle(0)
    }
    Image {
        id: imgB
        visible: false
        cache: false
        asynchronous: true
        smooth: true
        onStatusChanged: if (status === Image.Ready) root.settle(1)
    }
    MultiEffect {
        id: blurFx
        source: root.sharp
        width: root.width
        height: root.height
        blurEnabled: true
        blur: root.blurAmount
        blurMax: 48
        blurMultiplier: 0.6
        autoPaddingEnabled: false
    }
    ShaderEffectSource {
        id: blurTex
        sourceItem: blurFx
        hideSource: true
        visible: false
        live: true
        smooth: true
        textureSize: Qt.size(Math.max(16, Math.round(root.width / 2)), Math.max(9, Math.round(root.height / 2)))
    }
}
