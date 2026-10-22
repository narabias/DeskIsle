// Animated, coloured weather icon composed from stroke glyphs:
// sun, moon, cloud(-sun/-moon), rain, drizzle, storm, snow, mist, wind.
// `name` uses the weather service's icon ids (services/weather.py glyph_for).
import QtQuick

Item {
    id: root
    property string name: "cloud"
    property real size: 48
    property bool animate: true
    property real stroke: 1.6
    width: size
    height: size

    readonly property bool live: animate && visible && Theme.ms(1000) > 0
    readonly property color sunColor: "#FFB52E"
    readonly property color moonColor: "#F2D27A"
    readonly property color cloudColor: Theme.dark ? "#E9EEF6" : "#7D8796"
    readonly property color rainColor: "#4EA4F5"
    readonly property color boltColor: "#FFC93C"
    readonly property bool hasSun: name === "sun" || name === "cloud-sun"
    readonly property bool hasMoon: name === "moon" || name === "cloud-moon"
    readonly property bool partly: name === "cloud-sun" || name === "cloud-moon"
    readonly property bool hasCloud: name !== "sun" && name !== "moon" && name !== "wind" && name !== "mist"
    readonly property bool rain: name === "cloud-rain" || name === "cloud-storm"
    readonly property bool drizzle: name === "cloud-drizzle"
    readonly property bool snow: name === "snowflake" || name === "cloud-snow"
    readonly property bool storm: name === "cloud-storm"

    // Sun / moon -----------------------------------------------------------------------------------
    Glyph {
        id: sun
        visible: root.hasSun
        name: "sun"
        color: root.sunColor
        stroke: root.stroke
        size: root.partly ? root.size * 0.62 : root.size
        x: root.partly ? root.size * 0.02 : 0
        y: root.partly ? root.size * 0.02 : 0
        RotationAnimation on rotation {
            running: root.live && sun.visible
            from: 0
            to: 360
            duration: 24000
            loops: Animation.Infinite
        }
    }
    Glyph {
        id: moon
        visible: root.hasMoon
        name: "moon"
        color: root.moonColor
        stroke: root.stroke
        size: root.partly ? root.size * 0.56 : root.size * 0.9
        x: root.partly ? root.size * 0.04 : root.size * 0.05
        y: root.partly ? root.size * 0.02 : root.size * 0.05
        SequentialAnimation on rotation {
            running: root.live && moon.visible
            loops: Animation.Infinite
            NumberAnimation { from: -6; to: 6; duration: 3200; easing.type: Easing.InOutSine }
            NumberAnimation { from: 6; to: -6; duration: 3200; easing.type: Easing.InOutSine }
        }
    }

    // Cloud ------------------------------------------------------------------------------------------
    Item {
        id: cloudBox
        visible: root.hasCloud
        width: root.size
        height: root.size
        Glyph {
            id: cloud
            name: "cloud"
            color: root.cloudColor
            stroke: root.stroke
            size: root.partly ? root.size * 0.8 : root.size * 0.9
            property real drift: 0
            x: (root.partly ? root.size * 0.2 : root.size * 0.05) + drift * root.size
            y: root.partly ? root.size * 0.22 : (root.rain || root.drizzle || root.snow ? root.size * -0.04 : root.size * 0.05)
            SequentialAnimation on drift {
                running: root.live && cloudBox.visible
                loops: Animation.Infinite
                NumberAnimation { from: 0; to: 0.04; duration: 2600; easing.type: Easing.InOutSine }
                NumberAnimation { from: 0.04; to: 0; duration: 2600; easing.type: Easing.InOutSine }
            }
        }
    }

    // Rain / drizzle / snow ---------------------------------------------------------------------------
    Repeater {
        model: root.rain || root.drizzle || root.snow ? 3 : 0
        delegate: Item {
            id: drop
            required property int index
            readonly property real baseX: root.size * (0.32 + index * 0.17)
            readonly property real baseY: root.size * 0.66
            x: baseX
            y: baseY
            width: root.snow ? root.size * 0.09 : Math.max(1.5, root.size * 0.04)
            height: root.snow ? width : (root.drizzle ? width * 1.6 : root.size * 0.16)
            Rectangle {
                anchors.fill: parent
                radius: width / 2
                color: root.snow ? root.cloudColor : root.rainColor
                rotation: root.snow ? 0 : 12
                antialiasing: true
            }
            opacity: 0
            SequentialAnimation {
                running: root.live
                loops: Animation.Infinite
                PauseAnimation { duration: drop.index * (root.snow ? 520 : 260) }
                ParallelAnimation {
                    NumberAnimation { target: drop; property: "y"; from: drop.baseY; to: drop.baseY + root.size * 0.22; duration: root.snow ? 1500 : 760; easing.type: Easing.InQuad }
                    NumberAnimation { target: drop; property: "x"; from: drop.baseX; to: drop.baseX - root.size * (root.snow ? 0.02 : 0.05); duration: root.snow ? 1500 : 760 }
                    SequentialAnimation {
                        NumberAnimation { target: drop; property: "opacity"; from: 0; to: 1; duration: 140 }
                        PauseAnimation { duration: root.snow ? 1100 : 420 }
                        NumberAnimation { target: drop; property: "opacity"; to: 0; duration: 200 }
                    }
                }
                PauseAnimation { duration: (2 - drop.index) * (root.snow ? 520 : 260) }
            }
            Component.onCompleted: if (!root.live) opacity = 0.9
        }
    }

    // Storm bolt -------------------------------------------------------------------------------------
    Glyph {
        id: bolt
        visible: root.storm
        name: "bolt"
        color: root.boltColor
        stroke: root.stroke
        size: root.size * 0.42
        x: root.size * 0.4
        y: root.size * 0.56
        SequentialAnimation on opacity {
            running: root.live && bolt.visible
            loops: Animation.Infinite
            NumberAnimation { to: 1; duration: 80 }
            PauseAnimation { duration: 120 }
            NumberAnimation { to: 0.25; duration: 120 }
            NumberAnimation { to: 1; duration: 80 }
            PauseAnimation { duration: 2400 }
            NumberAnimation { to: 0.25; duration: 300 }
        }
    }

    // Mist / wind --------------------------------------------------------------------------------------
    Glyph {
        visible: root.name === "mist"
        name: "cloud-fog"
        color: root.cloudColor
        stroke: root.stroke
        size: root.size * 0.92
        x: root.size * 0.04
        y: root.size * 0.04
        SequentialAnimation on opacity {
            running: root.live && root.name === "mist"
            loops: Animation.Infinite
            NumberAnimation { to: 0.55; duration: 2200; easing.type: Easing.InOutSine }
            NumberAnimation { to: 1; duration: 2200; easing.type: Easing.InOutSine }
        }
    }
    Glyph {
        id: windGlyph
        visible: root.name === "wind"
        name: "wind"
        color: root.cloudColor
        stroke: root.stroke
        size: root.size * 0.92
        y: root.size * 0.04
        SequentialAnimation on x {
            running: root.live && windGlyph.visible
            loops: Animation.Infinite
            NumberAnimation { from: 0; to: root.size * 0.08; duration: 1400; easing.type: Easing.InOutSine }
            NumberAnimation { from: root.size * 0.08; to: 0; duration: 1400; easing.type: Easing.InOutSine }
        }
    }
}
