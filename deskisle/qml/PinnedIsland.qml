// An island pinned above other windows ("置顶"): its own frameless, always on
// top window with a margin for the shadow.  It cannot sample the wallpaper,
// so the glass uses its solid fallback.
import QtQuick
import QtQuick.Window

Window {
    id: win
    property var proxy: null
    property var scene: null
    readonly property real margin: 28
    color: "transparent"
    title: proxy ? "桌屿 · " + proxy.title : "桌屿"

    Island {
        proxy: win.proxy
        scene: win.scene
        wall: null
        standalone: true
        standaloneMargin: win.margin
    }
}
