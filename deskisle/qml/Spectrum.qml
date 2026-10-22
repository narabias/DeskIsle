// A slim "audio line" for the now-playing widget: a row of rounded bars on a
// bass-heavy envelope that runs the full width of the island, tallest a little
// left of centre and thinning out to dots towards the right (as on the desk's
// media widget).  QML has no access to the mixed audio stream, so the motion is
// a smoothed, music-like animation: it moves while playing, settles when paused
// and stops entirely with 减弱动态效果.
import QtQuick

Item {
    id: spectrum
    property color color: Theme.accent
    property bool playing: true
    property int barCount: 0                 // 0 = as many as fit at the set bar width
    property real barWidth: 3
    property real barGap: 3
    property real minBarHeight: 2
    property real intensity: 1.0
    property var heights: []

    readonly property real slot: barWidth + barGap
    readonly property int bars: {
        if (barCount > 0) {
            return barCount
        }
        return Math.max(6, Math.min(64, Math.floor((width + barGap) / slot)))
    }
    readonly property real contentWidth: bars * slot - barGap
    readonly property bool animate: playing && !App.paused && !Theme.reduceMotion
    readonly property real maxBarHeight: Math.max(minBarHeight + 1, height)

    onBarsChanged: rebuild()
    onWidthChanged: rebuild()
    Component.onCompleted: rebuild()

    function rebuild() {
        var out = []
        for (var i = 0; i < bars; ++i) {
            out.push(minBarHeight)
        }
        heights = out
    }

    // Bass-heavy envelope: a quick rise to a peak near 22 % of the width, a
    // long decay, and a tail that drops to single dots.
    function envelope(p) {
        var peak = Math.exp(-Math.pow((p - 0.22) / 0.30, 2))
        var tail = 0.42 * Math.pow(1 - p, 1.7)
        return Math.min(1, 0.14 + 0.86 * peak + tail * 0.45)
    }

    Timer {
        interval: 45
        repeat: true
        running: spectrum.animate && spectrum.visible
        onTriggered: spectrum.step()
    }

    property real phase: 0

    function step() {
        phase += 0.17
        var out = []
        var boost = 0.82 + 0.18 * Math.sin(phase * 0.9)
        for (var i = 0; i < bars; ++i) {
            var p = bars > 1 ? i / (bars - 1) : 0
            var target
            if (animate) {
                var motion = 0.55
                        + 0.24 * Math.sin(phase * 1.9 + i * 0.83)
                        + 0.14 * Math.sin(phase * 3.3 + i * 2.17)
                        + 0.06 * Math.sin(phase * 5.7 + i * 0.31)
                var energy = Math.max(0, Math.min(1, Math.abs(motion)))
                target = minBarHeight + (envelope(p) * boost * (0.22 + 0.78 * energy)
                                         * intensity) * (maxBarHeight - minBarHeight)
            } else {
                target = minBarHeight
            }
            var prev = heights.length > i ? heights[i] : minBarHeight
            // Fast attack, soft release - the way a level meter moves.
            out.push(prev + (target - prev) * (target > prev ? 0.55 : 0.28))
        }
        heights = out
    }

    // Baseline: the "line" the bars grow from.
    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 1
        radius: 0.5
        color: spectrum.color
        opacity: spectrum.playing ? 0.35 : 0.18
    }

    Item {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        width: spectrum.contentWidth
        height: parent.height

        Repeater {
            model: spectrum.bars
            delegate: Rectangle {
                required property int index
                x: index * spectrum.slot
                width: spectrum.barWidth
                height: spectrum.heights.length > index ? spectrum.heights[index] : spectrum.minBarHeight
                anchors.bottom: parent.bottom
                radius: width / 2
                color: spectrum.color
                // Fade towards the right so the tail reads as a fading line.
                opacity: 0.95 - 0.45 * (spectrum.bars > 1 ? index / (spectrum.bars - 1) : 0)
            }
        }
    }
}
