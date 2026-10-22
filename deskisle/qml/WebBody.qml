// Body of a web island: optional navigation toolbar, the page surface, a
// loading line and a failure card.
import QtQuick

Item {
    id: body
    property var island: null
    readonly property var proxy: island ? island.proxy : null
    readonly property string uid: island ? island.uid : ""
    readonly property var web: proxy ? proxy.web : ({})
    readonly property bool toolbar: !!proxy && proxy.webToolbar
    readonly property real zoom: web.zoom || 1

    function reload() {
        Desk.act(uid, "web.reload", {})
    }
    function act(name, args) {
        Desk.act(uid, name, args || {})
    }

    // Toolbar ------------------------------------------------------------------------------------------
    Item {
        id: bar
        visible: body.toolbar
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.leftMargin: 8
        anchors.rightMargin: 8
        height: visible ? 34 : 0
        Row {
            id: nav
            anchors.verticalCenter: parent.verticalCenter
            spacing: 2
            IconButton {
                icon: "arrow-left"
                tip: "后退"
                size: 28
                iconSize: 16
                enabled: !!body.web.canBack
                opacity: enabled ? 1 : 0.35
                onClicked: body.act("web.back")
            }
            IconButton {
                icon: "arrow-right"
                tip: "前进"
                size: 28
                iconSize: 16
                enabled: !!body.web.canForward
                opacity: enabled ? 1 : 0.35
                onClicked: body.act("web.forward")
            }
            IconButton {
                icon: body.web.loading ? "x" : "refresh"
                tip: body.web.loading ? "停止" : "刷新"
                size: 28
                iconSize: 16
                onClicked: body.act(body.web.loading ? "web.stop" : "web.reload")
            }
            IconButton {
                icon: "home"
                tip: "回到主页"
                size: 28
                iconSize: 16
                onClicked: body.act("web.home")
            }
        }
        Rectangle {
            id: urlPill
            anchors.left: nav.right
            anchors.leftMargin: 6
            anchors.right: zoomRow.left
            anchors.rightMargin: 6
            anchors.verticalCenter: parent.verticalCenter
            height: 26
            radius: 13
            color: urlMouse.containsMouse ? Theme.hover : (Theme.dark ? Qt.rgba(1, 1, 1, 0.05) : Qt.rgba(0, 0, 0, 0.04))
            border.width: 1
            border.color: Theme.hairline
            Row {
                anchors.left: parent.left
                anchors.leftMargin: 10
                anchors.right: parent.right
                anchors.rightMargin: 10
                anchors.verticalCenter: parent.verticalCenter
                spacing: 6
                Glyph {
                    anchors.verticalCenter: parent.verticalCenter
                    name: (body.web.url || "").indexOf("https:") === 0 ? "lock" : "world"
                    size: 13
                    color: Theme.textFaint
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    width: parent.width - 20
                    text: body.web.url || (body.proxy ? body.proxy.webUrl : "")
                    color: Theme.textDim
                    font.family: Theme.fontFamily
                    font.pixelSize: 12
                    elide: Text.ElideMiddle
                }
            }
            MouseArea {
                id: urlMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.IBeamCursor
                onClicked: body.island.flash("webUrl")
            }
        }
        Row {
            id: zoomRow
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: 0
            IconButton {
                icon: "zoom-out"
                tip: "缩小"
                size: 26
                iconSize: 15
                onClicked: body.act("web.zoom", { zoom: Math.max(0.25, Math.round((body.zoom - 0.1) * 10) / 10) })
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                width: 38
                horizontalAlignment: Text.AlignHCenter
                text: Math.round(body.zoom * 100) + "%"
                color: Theme.textFaint
                font.family: Theme.fontFamily
                font.pixelSize: 11
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: body.act("web.zoom", { zoom: 1.0 })
                }
            }
            IconButton {
                icon: "zoom-in"
                tip: "放大"
                size: 26
                iconSize: 15
                onClicked: body.act("web.zoom", { zoom: Math.min(5, Math.round((body.zoom + 0.1) * 10) / 10) })
            }
        }
    }

    // Page -------------------------------------------------------------------------------------------
    WebSurface {
        id: surface
        island: body.island
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: bar.bottom
        anchors.bottom: parent.bottom
        anchors.leftMargin: 6
        anchors.rightMargin: 6
        anchors.bottomMargin: 6
        anchors.topMargin: body.toolbar ? 2 : 0
        cornerRadius: Math.max(6, Theme.radius - 8)
    }

    // Loading line (indeterminate).
    Item {
        anchors.left: surface.left
        anchors.right: surface.right
        anchors.top: surface.top
        anchors.leftMargin: surface.cornerRadius
        anchors.rightMargin: surface.cornerRadius
        height: 2
        clip: true
        visible: !!body.web.loading
        Rectangle {
            id: runner
            width: parent.width * 0.35
            height: 2
            radius: 1
            color: Theme.accent
            SequentialAnimation on x {
                running: runner.visible
                loops: Animation.Infinite
                NumberAnimation { from: -runner.width; to: runner.parent.width; duration: Math.max(600, Theme.ms(1100)); easing.type: Easing.InOutQuad }
            }
        }
    }

    // Load failure.
    Rectangle {
        visible: !!body.web.status && !body.web.loading
        anchors.horizontalCenter: surface.horizontalCenter
        anchors.bottom: surface.bottom
        anchors.bottomMargin: 12
        width: Math.min(surface.width - 20, failRow.implicitWidth + 24)
        height: 34
        radius: 17
        color: Theme.dark ? Qt.rgba(0.12, 0.12, 0.14, 0.95) : Qt.rgba(1, 1, 1, 0.96)
        border.width: 1
        border.color: Theme.hairline
        Row {
            id: failRow
            anchors.centerIn: parent
            spacing: 8
            Glyph {
                anchors.verticalCenter: parent.verticalCenter
                name: "alert-triangle"
                size: 15
                color: Theme.danger
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: body.web.status || ""
                color: Theme.text
                font.family: Theme.fontFamily
                font.pixelSize: 12
            }
            GButton {
                anchors.verticalCenter: parent.verticalCenter
                text: "重试"
                kind: "ghost"
                compact: true
                onClicked: body.reload()
            }
        }
    }
}
