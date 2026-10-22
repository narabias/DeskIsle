// Image with rounded corners (album covers, previews).
import QtQuick
import QtQuick.Effects

Item {
    id: root
    property alias source: img.source
    property real radius: 8
    property int fillMode: Image.PreserveAspectCrop
    property bool shadow: false
    readonly property bool ready: img.status === Image.Ready

    Image {
        id: img
        anchors.fill: parent
        visible: false
        fillMode: root.fillMode
        asynchronous: true
        smooth: true
        mipmap: true
        cache: false
    }
    Rectangle {
        id: mask
        anchors.fill: parent
        radius: root.radius
        visible: false
        layer.enabled: true
    }
    RectangularShadow {
        anchors.fill: parent
        visible: root.shadow && root.ready
        radius: root.radius
        blur: 12
        offset.y: 2
        color: Qt.rgba(0, 0, 0, 0.35)
    }
    MultiEffect {
        // Mask only: a MultiEffect shadow would pad the output and misalign the mask.
        anchors.fill: parent
        source: img
        visible: root.ready
        maskEnabled: true
        maskSource: mask
        maskThresholdMin: 0.5
        maskSpreadAtMin: 1.0
    }
}
