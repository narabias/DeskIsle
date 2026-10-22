// One transparent layer window per monitor (bottom of the Z order).
// From back to front: wallpaper textures for the glass (invisible), the
// wallpaper itself (demo window / focus layer only), loose desktop icons,
// islands, drop ghosts and the dynamic bar.  Bar panels, confirmation cards
// and notices have their own windows above everything (PopupWindow.qml).
// Everything is laid out in window coordinates; the window starts
// scene.inset px inside the monitor.
import QtQuick
import QtQuick.Window

Window {
    id: win
    property var scene: null
    readonly property string key: scene ? scene.key_ : ""
    readonly property bool primary: !!scene && scene.primary
    readonly property var work: scene ? scene.work : ({ x: 0, y: 0, w: width, h: height })
    readonly property var area: scene ? scene.area : ({ x: 0, y: 0, w: width, h: height })
    readonly property real inset: scene ? scene.inset : 0
    readonly property bool panelHere: Desk.panel !== "" && (Desk.panelMonitor === key
                                      || (Desk.panelMonitor === "" && primary))
    readonly property bool showLoose: Desk.isDemo || !!Desk.prefs.hide_native_icons
    readonly property alias wall: wallSource
    readonly property alias barItem: barLoader.item
    readonly property real panelTop: primary && barLoader.item ? barLoader.y + barLoader.height + 10 : work.y + 16

    // A confirmation card is placed next to the thing it is about: look the island up by the
    // title in the card ("删除“时钟”？").  Only the islands of this layer are searched.
    function islandByTitle(title) {
        if (!title) {
            return null
        }
        var list = islands.children
        for (var i = 0; i < list.length; ++i) {
            var item = list[i]
            if (item && item.proxy && item.proxy.title === title && item.visible) {
                return item
            }
        }
        return null
    }

    title: "桌屿 DeskIsle"
    color: "transparent"
    width: 1280
    height: 800

    // Wallpaper ----------------------------------------------------------------------------------------
    WallSource {
        id: wallSource
        z: -100
        source: win.scene ? win.scene.wallSource : ""
    }
    ShaderEffect {
        // Default shader: draws `source`.  The demo window shows the wallpaper like a desktop; the
        // focus layer (above every application) shows it so islands read as "the desktop, in front".
        id: wallpaper
        z: -90
        x: -win.inset
        y: -win.inset
        width: win.scene ? win.scene.monitorWidth : win.width
        height: win.scene ? win.scene.monitorHeight : win.height
        property var source: wallSource.sharp
        visible: wallSource.ready && opacity > 0.01
        opacity: Desk.isDemo || Desk.focusMode ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: Theme.ms(260); easing.type: Easing.OutCubic } }
    }
    Rectangle {
        z: -89
        anchors.fill: parent
        visible: opacity > 0.01
        color: Theme.dark ? "#000000" : "#FFFFFF"
        opacity: Desk.focusMode ? (Theme.dark ? 0.28 : 0.16) : 0
        Behavior on opacity { NumberAnimation { duration: Theme.ms(260) } }
    }
    Rectangle {
        // Demo fallback while the wallpaper loads (or without one).
        z: -91
        anchors.fill: parent
        visible: Desk.isDemo && !wallSource.ready
        gradient: Gradient {
            GradientStop { position: 0; color: "#1B2735" }
            GradientStop { position: 1; color: "#090A0F" }
        }
    }

    // Keyboard (only while a text field or the focus layer holds the keyboard) ---------------------------
    Item {
        id: keys
        anchors.fill: parent
        focus: true
        Keys.onPressed: (event) => {
            if (event.key === Qt.Key_Escape) {
                if (Desk.panel !== "") {
                    Desk.closePanel()
                } else if (Desk.confirmInfo.id && win.primary) {
                    Desk.resolveConfirm(Desk.confirmInfo.id, false)
                } else if (Desk.focusMode) {
                    Desk.toggleFocus()
                } else {
                    Desk.cancelGestures()
                }
                event.accepted = true
            } else if (event.key === Qt.Key_Z && (event.modifiers & Qt.ControlModifier)) {
                Desk.undo()
                event.accepted = true
            } else if (event.key === Qt.Key_F && (event.modifiers & Qt.ControlModifier)) {
                Desk.togglePanel("search", win.key)
                event.accepted = true
            }
        }
    }

    // Loose desktop icons (also the blank desktop: menus, rubber band, double-click wake) -----------------
    IconGrid {
        id: loose
        anchors.fill: parent
        z: 0
        model: win.showLoose && win.scene ? win.scene.looseModel : null
        container: "loose"
        free: true
        onDesktop: true
        iconSize: 48
        opacity: Desk.hidden ? 0 : 1
        visible: opacity > 0.01 || Desk.hidden
        Behavior on opacity { NumberAnimation { duration: Theme.ms(220); easing.type: Easing.OutCubic } }
        onActivated: (path) => Desk.openItem(path)
        onBlankMenu: (gx, gy) => App.popupMenuAt("desktop", win.key, {}, Math.round(gx), Math.round(gy))
        onBlankDoubleClicked: (gx, gy) => {
            if (Desk.prefs.wake_double_click) {
                Desk.toggleHidden()
            }
        }
        onBlankPressed: {
            Desk.closePanel()
            Desk.dismissMenus()
        }
    }

    // Islands -------------------------------------------------------------------------------------------
    Item {
        id: islands
        anchors.fill: parent
        z: 10
        Repeater {
            model: win.scene ? win.scene.islandsModel : null
            delegate: Island {
                required property var object
                proxy: object
                scene: win.scene
                wall: wallSource
            }
        }
    }

    // Drag feedback: target / make-way ghosts and the shadow of an island dragged in from another monitor.
    Item {
        anchors.fill: parent
        z: 5
        Repeater {
            model: win.scene ? win.scene.ghosts : []
            delegate: DashedRect {
                required property var modelData
                x: modelData.x
                y: modelData.y
                width: modelData.w
                height: modelData.h
                radius: Theme.radius
                stroke: modelData.style === "target" ? Theme.accent
                        : (Theme.dark ? Qt.rgba(1, 1, 1, 0.35) : Qt.rgba(0, 0, 0, 0.28))
                fill: modelData.style === "target" ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.12)
                      : (Theme.dark ? Qt.rgba(1, 1, 1, 0.05) : Qt.rgba(0, 0, 0, 0.04))
                strokeWidth: modelData.style === "target" ? 2 : 1.5
                Behavior on x { NumberAnimation { duration: Theme.ms(120); easing.type: Easing.OutCubic } }
                Behavior on y { NumberAnimation { duration: Theme.ms(120); easing.type: Easing.OutCubic } }
            }
        }
        DashedRect {
            readonly property var info: win.scene ? win.scene.dragShadow : ({})
            visible: !!info.visible
            x: info.x || 0
            y: info.y || 0
            width: info.w || 0
            height: info.h || 0
            radius: Theme.radius
            stroke: Theme.accent
            fill: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.16)
            Text {
                anchors.centerIn: parent
                width: parent.width - 24
                horizontalAlignment: Text.AlignHCenter
                elide: Text.ElideRight
                text: (parent.info.title || "") + "  →  " + (win.scene ? win.scene.label : "")
                color: Theme.text
                style: Text.Raised
                styleColor: Theme.dark ? "#80000000" : "#80FFFFFF"
                font.family: Theme.fontFamily
                font.pixelSize: 14
                font.weight: Font.DemiBold
            }
        }
    }

    // Dynamic bar (primary monitor) -------------------------------------------------------------------
    Loader {
        id: barLoader
        z: 40
        active: win.primary
        x: Math.round(win.area.x + (win.area.w - width) / 2)
        y: win.area.y + 10
        source: "DynamicBar.qml"
        onLoaded: item.deskLayer = win
    }

    // Focus layer / clean desk hints ------------------------------------------------------------------
    HintPill {
        id: focusHint
        z: 46
        shown: Desk.focusMode && win.primary
        icon: "focus"
        text: "聚焦层  ·  Esc 或 Ctrl+Alt+Space 退出"
        action: "退出"
        onTriggered: Desk.toggleFocus()
        x: Math.round(win.work.x + (win.work.w - width) / 2)
        y: win.work.y + win.work.h - height - 22
    }
    HintPill {
        id: hiddenHint
        z: 46
        property bool pulse: false
        function flash() {
            pulse = true
            hideTimer.restart()
        }
        shown: pulse && win.primary
        icon: Desk.hidden ? "eye-off" : "eye"
        text: Desk.hidden ? "已清屏  ·  双击桌面空白处恢复" : "已恢复显示"
        x: Math.round(win.work.x + (win.work.w - width) / 2)
        // stacks above the focus-mode pill instead of covering it
        y: win.work.y + win.work.h - height - 22 - (focusHint.shown ? focusHint.height + 10 : 0)
        Timer {
            id: hideTimer
            interval: 2400
            onTriggered: hiddenHint.pulse = false
        }
        Connections {
            target: Desk
            function onHiddenChanged() { hiddenHint.flash() }
        }
    }

    // Demo badge (fades out after a few seconds) -------------------------------------------------------
    Rectangle {
        id: demoBadge
        z: 80
        property bool fresh: true
        visible: Desk.isDemo && win.primary && opacity > 0.01
        opacity: fresh ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: Theme.ms(600) } }
        x: Math.round(win.area.x + (win.area.w - width) / 2)
        y: win.area.y + win.area.h - height - 12
        height: 26
        width: demoText.implicitWidth + 22
        radius: 13
        color: Qt.rgba(0, 0, 0, 0.5)
        Timer {
            running: Desk.isDemo
            interval: 9000
            onTriggered: demoBadge.fresh = false
        }
        Text {
            id: demoText
            anchors.centerIn: parent
            text: "演示模式 · 不会改动真实桌面"
            color: "#F2F4F7"
            font.family: Theme.fontFamily
            font.pixelSize: 12
        }
    }
}
