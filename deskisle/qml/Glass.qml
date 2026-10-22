// Liquid-glass surface: shadow + refracted wallpaper body + rim in one pass.
// The backdrop textures cover the whole monitor (see Layer.qml); the item
// passes its own position so it samples exactly the wallpaper behind it.
// Falls back to a translucent rounded rectangle on the software renderer.
import QtQuick
import QtQuick.Effects

Item {
    id: root
    property var blurSource: null
    property var sharpSource: null
    // Top-left of this item in monitor (window) coordinates and monitor size.
    property point backdropOrigin: Qt.point(x, y)
    property size backdropSize: Qt.size(1920, 1080)

    property real radius: 22
    property real exponent: 2.6           // 2 = circle corners, >2 = continuous corners
    property string material: "liquid"    // liquid | frosted | clear
    property bool dark: true
    property real strength: 1.0           // glass intensity (settings slider)
    property color tint: "#000000"
    property real tintStrength: 0.0
    property real shadowOpacity: dark ? 0.36 : 0.24
    property real shadowSize: 16
    property real elevation: 1.0
    property real hover: 0.0
    property real bodyOpacity: 1.0
    property point lightDir: Qt.point(-0.45, -0.89)
    property bool solidFallback: false    // force the plain card (pinned windows, popups, tests)
    property real solidAlpha: -1          // plain card opacity (-1: default)
    property bool solidShadow: false      // plain card in its own window: soft drop shadow
    // Web islands: rectangle (body coordinates) left fully transparent so the page
    // composed below the layer shows through; holeRadius rounds its corners.
    property rect hole: Qt.rect(0, 0, 0, 0)
    property real holeRadius: 0

    readonly property real pad: Math.ceil(shadowSize * 2.6 + 4)
    readonly property bool gpu: GraphicsInfo.api !== GraphicsInfo.Software
                                && GraphicsInfo.api !== GraphicsInfo.Unknown

    // refr: edge refraction (px), bezel: width of the curved rim (px), rim: highlight,
    // sharp: how much of the unblurred wallpaper shows, chroma: colour split at the rim.
    readonly property var _m: material === "frosted" ? { refr: 6, bezel: 16, rim: 0.42, sharp: 0.0, chroma: 0.03 }
                            : material === "clear"   ? { refr: 14, bezel: 22, rim: 0.55, sharp: 0.92, chroma: 0.08 }
                            :                          { refr: 18, bezel: 26, rim: 0.62, sharp: 0.16, chroma: 0.10 }
    // brightness, saturation, lift (+ towards white, - towards black)
    readonly property var _t: dark
        ? (material === "frosted" ? [0.74, 1.15, -0.22] : material === "clear" ? [0.90, 1.08, -0.08] : [0.80, 1.20, -0.17])
        : (material === "frosted" ? [1.02, 1.08, 0.40] : material === "clear" ? [1.02, 1.05, 0.12] : [1.03, 1.12, 0.28])

    ShaderEffect {
        id: fx
        visible: root.gpu && !root.solidFallback && !!root.blurSource && !!root.sharpSource
        x: -root.pad
        y: -root.pad
        width: root.width + 2 * root.pad
        height: root.height + 2 * root.pad
        blending: true
        property var blurTex: root.blurSource
        property var sharpTex: root.sharpSource
        property size itemSize: Qt.size(width, height)
        property real pad: root.pad
        property real radius: Math.min(root.radius, Math.min(root.width, root.height) / 2)
        property real exponent: root.exponent
        property rect wallRect: Qt.rect(root.backdropOrigin.x - root.pad, root.backdropOrigin.y - root.pad,
                                        root.backdropSize.width, root.backdropSize.height)
        property vector4d tint: Qt.vector4d(root.tint.r, root.tint.g, root.tint.b, root.tintStrength)
        property vector4d look: Qt.vector4d(root._m.refr * root.strength, root._m.bezel, root._m.rim, root._m.sharp)
        property vector4d tone: Qt.vector4d(1.0 + (root._t[0] - 1.0) * root.strength,
                                            1.0 + (root._t[1] - 1.0) * root.strength,
                                            root._t[2] * root.strength, root.dark ? 0.012 : 0.010)
        property vector4d shadowP: Qt.vector4d(root.shadowOpacity * root.elevation, root.shadowSize,
                                               root.shadowSize * 0.38, root.bodyOpacity)
        property point lightDir: root.lightDir
        property real hover: root.hover
        property real chroma: root._m.chroma
        property vector4d hole: Qt.vector4d(root.hole.x, root.hole.y, root.hole.width, root.hole.height)
        property real holeRadius: root.holeRadius
        fragmentShader: "shaders/glass.frag.qsb"
    }

    RectangularShadow {
        visible: root.solidShadow && !fx.visible && root.gpu
        anchors.fill: plain
        radius: plain.radius
        blur: root.shadowSize * 1.4
        offset.y: Math.round(root.shadowSize * 0.35)
        color: Qt.rgba(0, 0, 0, Math.min(0.6, root.shadowOpacity * root.elevation))
    }
    Rectangle {
        // Software renderer / no backdrop: a plain translucent card.
        id: plain
        visible: !fx.visible
        width: parent.width
        height: root.hole.width > 0 ? Math.max(radius * 2, root.hole.y) : parent.height
        radius: Math.min(root.radius, Math.min(root.width, root.height) / 2)
        opacity: root.bodyOpacity
        color: root.dark ? Qt.rgba(0.08, 0.09, 0.11, root.solidAlpha >= 0 ? root.solidAlpha : 0.80)
                         : Qt.rgba(0.97, 0.97, 0.98, root.solidAlpha >= 0 ? root.solidAlpha : 0.78)
        border.width: 1
        border.color: root.dark ? Qt.rgba(1, 1, 1, 0.16) : Qt.rgba(1, 1, 1, 0.70)
        Rectangle {
            anchors.fill: parent
            radius: parent.radius
            color: Qt.rgba(root.tint.r, root.tint.g, root.tint.b, root.tintStrength * 0.8)
        }
    }
}
