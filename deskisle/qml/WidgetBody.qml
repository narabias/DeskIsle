// Body of a widget island: a built-in widget (clock, weather, now playing,
// todo), a custom Qt Quick widget from the custom folder, or an HTML widget
// (page surface).  `widget` is the island proxy; custom QML widgets reach it
// by that name (see AGENTS.md / custom folder README).
import QtQuick

Item {
    id: body
    property var island: null
    property var widget: island ? island.proxy : null
    readonly property string wid: widget ? widget.widget : ""
    readonly property bool custom: wid.indexOf("custom:") === 0
    readonly property bool hasCustom: typeof Custom !== "undefined" && !!Custom
    readonly property var info: custom && hasCustom && Custom.revision >= 0 ? Custom.widgetInfo(wid) : ({})
    readonly property bool html: custom && info.type === "html"
    // A windowed page covers everything in its area: keep a strip above it for the grip
    // (drag, menu) - right clicks inside the page open the island menu as well.
    readonly property bool pageAbove: html && !!island && !!island.webView && island.webView.above
    readonly property string problem: !custom ? "" : (!hasCustom ? "自定义文件夹不可用"
                                    : (!info.id ? "找不到这个小组件（" + wid.substring(7) + "）"
                                    : (info.error || (qmlLoader.status === Loader.Error ? (info.entry || "Widget.qml") + " 有错误，详情见“设置 → 关于 → 运行日志”" : ""))))

    function reload() {
        if (qmlLoader.active) {
            qmlLoader.active = false
            qmlLoader.active = true
        }
    }

    // Built-in -------------------------------------------------------------------------------------------
    Loader {
        anchors.fill: parent
        active: !body.custom && body.wid !== ""
        source: body.wid === "clock" ? "ClockWidget.qml"
              : body.wid === "weather" ? "WeatherWidget.qml"
              : body.wid === "media" ? "MediaWidget.qml"
              : body.wid === "todo" ? "TodoWidget.qml" : ""
        onLoaded: item.island = body.island
    }

    // Custom Qt Quick widget -------------------------------------------------------------------------------
    Loader {
        id: qmlLoader
        anchors.fill: parent
        anchors.margins: 6
        active: body.custom && body.hasCustom && info.type === "qml" && !info.error
        source: active ? (Custom.revision, Custom.widgetUrl(body.wid)) : ""
    }

    // HTML widget ------------------------------------------------------------------------------------------
    Rectangle {
        visible: body.pageAbove && !(body.island && (body.island.hovered || body.island.dragging))
        anchors.horizontalCenter: parent.horizontalCenter
        y: 11
        width: 32
        height: 4
        radius: 2
        color: Theme.textFaint
        opacity: 0.55
    }
    Loader {
        anchors.fill: parent
        anchors.margins: 4
        anchors.topMargin: body.pageAbove ? 28 : 4
        active: body.html && !body.info.error
        sourceComponent: Component {
            WebSurface {
                island: body.island
                cornerRadius: Math.max(6, (body.island ? body.island.radius : Theme.radius) - 4)
            }
        }
    }

    // Problem card ------------------------------------------------------------------------------------------
    Column {
        visible: body.problem !== ""
        anchors.centerIn: parent
        width: parent.width - 32
        spacing: 8
        Glyph {
            anchors.horizontalCenter: parent.horizontalCenter
            name: "alert-triangle"
            size: 24
            color: Theme.danger
        }
        Text {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            text: body.problem
            color: Theme.textDim
            font.family: Theme.fontFamily
            font.pixelSize: 12
            wrapMode: Text.Wrap
        }
        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 8
            GButton {
                text: "打开文件夹"
                icon: "folder-open"
                kind: "tonal"
                compact: true
                visible: body.hasCustom
                onClicked: Custom.openFolder()
            }
            GButton {
                text: "重新加载"
                icon: "refresh"
                kind: "ghost"
                compact: true
                visible: body.hasCustom
                onClicked: Custom.reload()
            }
        }
    }
}
