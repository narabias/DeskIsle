// Stroke icon from glyphs.js (Tabler Icons, MIT) drawn with Qt Quick Shapes.
// Usage: Glyph { name: "folder"; size: 18; color: Theme.text }
import QtQuick
import QtQuick.Shapes
import "glyphs.js" as G

Item {
    id: root
    property string name: ""
    property color color: Theme ? Theme.text : "white"
    property real size: 18
    // Stroke width in the 24 px design grid (Tabler uses 2; 1.75 reads lighter on glass).
    property real stroke: 1.75
    property bool filled: false

    readonly property string pathData: G.paths[name] || ""
    implicitWidth: size
    implicitHeight: size
    width: size
    height: size

    Shape {
        width: 24
        height: 24
        visible: root.pathData !== ""
        preferredRendererType: Shape.CurveRenderer
        transform: Scale { xScale: root.width / 24; yScale: root.height / 24 }
        ShapePath {
            strokeColor: root.color
            strokeWidth: root.stroke
            fillColor: root.filled ? root.color : "transparent"
            capStyle: ShapePath.RoundCap
            joinStyle: ShapePath.RoundJoin
            PathSvg { path: root.pathData }
        }
    }
}
