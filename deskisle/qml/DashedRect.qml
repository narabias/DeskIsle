// Rounded rectangle with a dashed outline (drop ghosts, placeholders).
import QtQuick
import QtQuick.Shapes

Item {
    id: root
    property real radius: 12
    property color stroke: Theme.accent
    property color fill: "transparent"
    property real strokeWidth: 2
    property var dash: [4, 3]

    Rectangle {
        anchors.fill: parent
        radius: root.radius
        color: root.fill
    }
    Shape {
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            strokeColor: root.stroke
            strokeWidth: root.strokeWidth
            fillColor: "transparent"
            strokeStyle: ShapePath.DashLine
            dashPattern: root.dash
            capStyle: ShapePath.RoundCap
            PathRectangle {
                x: root.strokeWidth / 2
                y: root.strokeWidth / 2
                width: Math.max(0, root.width - root.strokeWidth)
                height: Math.max(0, root.height - root.strokeWidth)
                radius: Math.max(0, root.radius - root.strokeWidth / 2)
            }
        }
    }
}
