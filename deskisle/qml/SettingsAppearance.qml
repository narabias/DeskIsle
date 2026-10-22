// Settings · 外观: theme mode, wallpaper accent, island glass, glass backdrop
// source, font and motion.
import QtQuick
import QtQuick.Effects

Column {
    id: page
    property var win: null
    readonly property var p: Desk.prefs
    property int tick: 0
    width: parent ? parent.width : 640
    spacing: 22

    Connections {
        target: App
        function onInfoChanged() { page.tick++ }
    }
    Timer {
        // App.liveStatus() is a plain call: poll it while this page is open.
        interval: 3000
        running: true
        repeat: true
        onTriggered: page.tick++
    }

    // "07:00" stepper: arrows / wheel move by 15 minutes.
    component TimeStepper: Row {
        id: ts
        property string pref: ""
        readonly property string value: String(Desk.prefs[pref] || "07:00")
        spacing: 4
        function minutes(t) {
            var m = /^(\d{1,2}):(\d{2})$/.exec(t)
            return m ? parseInt(m[1], 10) * 60 + parseInt(m[2], 10) : 0
        }
        function fmt(n) {
            n = ((n % 1440) + 1440) % 1440
            var h = Math.floor(n / 60), mm = n % 60
            return (h < 10 ? "0" : "") + h + ":" + (mm < 10 ? "0" : "") + mm
        }
        function step(d) {
            Desk.setPref(pref, fmt(Math.round((minutes(value) + d) / 15) * 15))
        }
        IconButton {
            anchors.verticalCenter: parent.verticalCenter
            icon: "chevron-left"
            tip: "提前 15 分钟"
            size: 28
            iconSize: 15
            onClicked: ts.step(-15)
        }
        Rectangle {
            anchors.verticalCenter: parent.verticalCenter
            width: 70
            height: 32
            radius: 16
            color: Theme.dark ? Qt.rgba(1, 1, 1, 0.07) : Qt.rgba(0, 0, 0, 0.05)
            border.width: 1
            border.color: Theme.hairline
            Text {
                anchors.centerIn: parent
                text: ts.value
                color: Theme.text
                font.family: Theme.fontFamily
                font.pixelSize: 15
                font.weight: Font.DemiBold
            }
            WheelHandler {
                onWheel: (event) => ts.step(event.angleDelta.y > 0 ? 15 : -15)
            }
        }
        IconButton {
            anchors.verticalCenter: parent.verticalCenter
            icon: "chevron-right"
            tip: "推后 15 分钟"
            size: 28
            iconSize: 15
            onClicked: ts.step(15)
        }
    }

    // ---- 主题 ----------------------------------------------------------------------
    SettingsCard {
        title: "主题"
        SettingRow {
            title: "主题模式"
            description: {
                var m = page.p.theme_mode
                var text = m === "auto_time" ? "白天使用浅色、夜间使用深色，按下面的时间切换。"
                         : m === "wallpaper" ? "壁纸明亮时用浅色，偏暗时用深色；更换壁纸后自动调整。"
                         : m === "system" ? "跟随 Windows 设置中的“选择应用模式”。"
                         : m === "light" ? "始终使用浅色。" : "始终使用深色。"
                return m === "light" || m === "dark" ? text : text + (Theme.dark ? "当前为深色。" : "当前为浅色。")
            }
            pref: "theme_mode"
            kind: "segmented"
            stacked: true
            options: [
                { value: "auto_time", text: "按时间", icon: "clock" },
                { value: "wallpaper", text: "跟随壁纸", icon: "photo" },
                { value: "system", text: "跟随系统", icon: "device-desktop" },
                { value: "light", text: "浅色", icon: "sun" },
                { value: "dark", text: "深色", icon: "moon" }
            ]
        }
        SettingRow {
            visible: page.p.theme_mode === "auto_time"
            title: "白天开始"
            description: "从这个时间起使用浅色主题。"
            TimeStepper { pref: "day_start" }
        }
        SettingRow {
            visible: page.p.theme_mode === "auto_time"
            title: "夜间开始"
            description: "从这个时间起使用深色主题。"
            TimeStepper { pref: "night_start" }
        }
        SettingRow {
            title: "强调色"
            description: "自动取自当前壁纸的主色调，用于开关、按钮与选中状态；更换壁纸后随之变化。"
            Item {
                width: 132
                height: 52
                Rectangle {
                    id: thumbFrame
                    width: 92
                    height: 52
                    radius: 10
                    color: Theme.hover
                    clip: true
                    Image {
                        id: thumbImg
                        anchors.fill: parent
                        source: page.win ? page.win.wallSrc : ""
                        sourceSize.width: 184
                        fillMode: Image.PreserveAspectCrop
                        asynchronous: true
                        cache: false
                        visible: false
                    }
                    Rectangle {
                        id: thumbMask
                        anchors.fill: parent
                        radius: 10
                        visible: false
                        layer.enabled: true
                    }
                    MultiEffect {
                        anchors.fill: parent
                        source: thumbImg
                        maskEnabled: true
                        maskSource: thumbMask
                        maskThresholdMin: 0.5
                        maskSpreadAtMin: 1.0
                    }
                    Rectangle {
                        anchors.fill: parent
                        radius: 10
                        color: "transparent"
                        border.width: 1
                        border.color: Theme.hairline
                    }
                }
                Rectangle {
                    // the colour picked from that wallpaper
                    x: thumbFrame.width + 10
                    anchors.verticalCenter: parent.verticalCenter
                    width: 30
                    height: 30
                    radius: 15
                    color: Theme.accent
                    border.width: 3
                    border.color: Theme.dark ? Qt.rgba(1, 1, 1, 0.85) : "#FFFFFF"
                    Behavior on color { ColorAnimation { duration: Theme.ms(400) } }
                }
            }
        }
    }

    // ---- 收纳岛 --------------------------------------------------------------------
    SettingsCard {
        title: "收纳岛"
        note: "单个收纳岛可以在它的右键菜单“材质”中另选。"
        SettingRow {
            title: "默认材质"
            description: page.p.island_material === "frosted" ? "毛玻璃：柔和地模糊背后的壁纸，文字最清楚。"
                       : page.p.island_material === "clear" ? "清透：几乎不模糊，像一块透明的玻璃。"
                       : "液态玻璃：边缘折射与高光，通透而有层次。"
            pref: "island_material"
            kind: "segmented"
            options: [
                { value: "liquid", text: "液态玻璃" },
                { value: "frosted", text: "毛玻璃" },
                { value: "clear", text: "清透" }
            ]
        }
        SettingRow {
            title: "玻璃浓度"
            description: "折射、着色与亮度变化的强度。数值越低越通透，越高越厚重。"
            pref: "glass_strength"
            kind: "slider"
            from: 0.3
            to: 1.6
            step: 0.05
            displayScale: 100
            unit: "%"
        }
    }

    // ---- 壁纸 ----------------------------------------------------------------------
    SettingsCard {
        title: "玻璃背景"
        note: Desk.isWindows ? "只影响桌屿玻璃背后的画面，不会更改 Windows 壁纸。"
                             : "当前不是 Windows：使用内置的演示壁纸，动态壁纸读取不可用。"
        SettingRow {
            title: "背景来源"
            description: {
                var m = page.p.wallpaper_mode
                return m === "live" ? "实时读取桌面壁纸画面，Wallpaper Engine、Lively 等动态壁纸也能透过玻璃流动。"
                     : m === "static" ? "使用 Windows 设置中的壁纸图片，按系统的契合度摆放。"
                     : m === "image" ? "使用你选择的图片作为玻璃背景。"
                     : "不读取壁纸，玻璃使用深色纯色底，最省电。"
            }
            pref: "wallpaper_mode"
            kind: "segmented"
            stacked: true
            options: [
                { value: "live", text: "动态壁纸", icon: "player-play" },
                { value: "static", text: "系统壁纸", icon: "photo" },
                { value: "image", text: "自定义图片", icon: "folder-open" },
                { value: "solid", text: "纯色", icon: "square" }
            ]
        }
        SettingRow {
            visible: page.p.wallpaper_mode === "live"
            title: "动态壁纸刷新率"
            description: "玻璃背后画面每秒更新的次数；画面不动时会自动放慢。越高越跟手，也越耗电。"
            pref: "live_fps"
            kind: "slider"
            from: 1
            to: 30
            step: 1
            unit: " 帧/秒"
        }
        SettingRow {
            id: liveRow
            readonly property string status: (page.tick, App.liveStatus())
            visible: page.p.wallpaper_mode === "live" && status !== ""
            title: "动态壁纸状态"
            description: status
            Glyph {
                name: "alert-triangle"
                size: 18
                color: "#F5A524"
            }
        }
        SettingRow {
            visible: page.p.wallpaper_mode === "image"
            title: "背景图片"
            description: page.p.wallpaper_image ? page.p.wallpaper_image : "尚未选择图片。"
            GButton {
                text: page.p.wallpaper_image ? "更换图片…" : "选择图片…"
                icon: "photo"
                compact: true
                onClicked: {
                    var f = Desk.pickFile("选择背景图片", "图片 (*.png *.jpg *.jpeg *.bmp *.webp *.gif)")
                    if (f) {
                        Desk.setPref("wallpaper_image", f)
                    }
                }
            }
        }
    }

    // ---- 文字 ----------------------------------------------------------------------
    SettingsCard {
        title: "文字"
        SettingRow {
            id: fontRow
            property bool expanded: false
            title: "字体"
            description: (page.p.font_family ? page.p.font_family : "系统默认（" + Theme.fontFamily + "）")
                         + (page.p.font_file ? " · 来自导入的字体文件" : "")
            GButton {
                text: fontRow.expanded ? "收起" : "更换字体"
                icon: fontRow.expanded ? "chevron-up" : "typography"
                compact: true
                onClicked: fontRow.expanded = !fontRow.expanded
            }
            GButton {
                text: "导入字体文件…"
                icon: "upload"
                compact: true
                onClicked: Desk.importFont()
            }
            GButton {
                visible: !!page.p.font_family || !!page.p.font_file
                text: "恢复默认"
                kind: "ghost"
                compact: true
                onClicked: {
                    Desk.setPref("font_file", "")
                    Desk.setPref("font_family", "")
                }
            }
        }
        Item {
            // font chooser (inline)
            id: picker
            visible: fontRow.expanded
            width: parent.width
            height: visible ? 300 : 0
            property var families: []
            onVisibleChanged: if (visible && families.length === 0) families = Theme.fontFamilies()
            readonly property var shown: {
                var q = filter.text.trim().toLowerCase()
                var out = []
                for (var i = 0; i < families.length; ++i) {
                    if (q === "" || families[i].name.toLowerCase().indexOf(q) >= 0) {
                        out.push(families[i])
                    }
                }
                return out
            }
            GTextField {
                id: filter
                x: 16
                y: 4
                width: parent.width - 32
                layerWindow: false
                icon: "search"
                placeholder: "搜索已安装的字体（共 " + picker.families.length + " 种，支持中文的排在前面）"
                fontSize: 13
            }
            ListView {
                id: fontList
                x: 10
                y: filter.y + filter.height + 8
                width: parent.width - 20
                height: parent.height - y - 8
                clip: true
                model: picker.shown
                boundsBehavior: Flickable.StopAtBounds
                delegate: Item {
                    id: fontItem
                    required property var modelData
                    readonly property bool on: modelData.name === (page.p.font_family || "")
                    width: fontList.width
                    height: 40
                    Rectangle {
                        anchors.fill: parent
                        anchors.margins: 1
                        radius: 9
                        color: fontItem.on ? Theme.accentSoft : (fontArea.containsMouse ? Theme.hover : "transparent")
                    }
                    Text {
                        x: 14
                        anchors.verticalCenter: parent.verticalCenter
                        width: parent.width * 0.42
                        elide: Text.ElideRight
                        text: fontItem.modelData.name
                        color: Theme.text
                        font.family: Theme.fontFamily
                        font.pixelSize: 13
                    }
                    Text {
                        anchors.right: badge.left
                        anchors.rightMargin: 12
                        anchors.verticalCenter: parent.verticalCenter
                        width: parent.width * 0.42
                        elide: Text.ElideRight
                        horizontalAlignment: Text.AlignRight
                        text: fontItem.modelData.cjk ? "桌屿 工作岛 Aa 123" : "DeskIsle Aa 123"
                        color: Theme.textDim
                        font.family: fontItem.modelData.name
                        font.pixelSize: 15
                    }
                    Rectangle {
                        id: badge
                        anchors.right: parent.right
                        anchors.rightMargin: 12
                        anchors.verticalCenter: parent.verticalCenter
                        width: 34
                        height: 20
                        radius: 10
                        color: fontItem.modelData.cjk ? Theme.accentSoft : "transparent"
                        Text {
                            anchors.centerIn: parent
                            visible: fontItem.modelData.cjk
                            text: "中文"
                            color: Theme.accent
                            font.family: Theme.fontFamily
                            font.pixelSize: 11
                        }
                    }
                    MouseArea {
                        id: fontArea
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: Desk.setPref("font_family", fontItem.modelData.name)
                    }
                }
            }
        }
        SettingRow {
            title: "字号"
            description: "收纳岛、菜单与设置中正文的大小。"
            pref: "font_size"
            kind: "slider"
            from: 7
            to: 20
            step: 0.5
            decimals: 1
            unit: " pt"
        }
        SettingRow {
            title: "文字颜色"
            description: page.p.text_color_mode === "auto" ? "跟随主题：深色主题用浅色文字，浅色主题用深色文字。"
                       : page.p.text_color_mode === "custom" ? "使用下面选择的颜色，次要文字按比例变淡。"
                       : "收纳岛、小组件、灵动岛、菜单与设置中的文字都使用这个颜色。"
            pref: "text_color_mode"
            kind: "segmented"
            options: [
                { value: "auto", text: "自动" },
                { value: "light", text: "浅色" },
                { value: "dark", text: "深色" },
                { value: "custom", text: "自定义" }
            ]
        }
        SettingRow {
            visible: page.p.text_color_mode === "custom"
            title: "自定义文字颜色"
            description: "点选色块，或输入十六进制颜色（例如 #FFE8A3）后按回车。"
            Row {
                spacing: 6
                Repeater {
                    model: ["#FFFFFF", "#FFE8A3", "#BFE3FF", "#C8F7C5", "#FFC9DE", "#2B2F36", "#11161D", "#5A3E2B"]
                    delegate: Rectangle {
                        id: swatch
                        required property string modelData
                        anchors.verticalCenter: parent.verticalCenter
                        width: 24
                        height: 24
                        radius: 12
                        color: modelData
                        border.width: page.p.text_color === modelData ? 3 : 1
                        border.color: page.p.text_color === modelData ? Theme.accent : Theme.hairline
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: Desk.setPref("text_color", swatch.modelData)
                        }
                    }
                }
                GTextField {
                    anchors.verticalCenter: parent.verticalCenter
                    width: 104
                    layerWindow: false
                    clearButton: false
                    maximumLength: 7
                    text: page.p.text_color
                    placeholder: "#RRGGBB"
                    onAccepted: Desk.setPref("text_color", text.trim())
                }
            }
        }
        Item {
            // live preview
            width: parent.width
            height: preview.implicitHeight + 28
            Rectangle {
                x: 16
                y: 2
                width: parent.width - 32
                height: parent.height - 14
                radius: 10
                color: Theme.dark ? Qt.rgba(0, 0, 0, 0.18) : Qt.rgba(0, 0, 0, 0.035)
                Text {
                    id: preview
                    x: 14
                    anchors.verticalCenter: parent.verticalCenter
                    width: parent.width - 28
                    wrapMode: Text.Wrap
                    text: "桌屿 DeskIsle · 把凌乱桌面整理成你的工作岛 0123456789"
                    color: Theme.text
                    font.family: Theme.fontFamily
                    font.pixelSize: Math.round(Theme.fontSize * 1.1)
                }
            }
        }
    }

    // ---- 动效 ----------------------------------------------------------------------
    SettingsCard {
        title: "动效"
        SettingRow {
            title: "减弱动态效果"
            description: "展开、收拢、让位与主题切换直接完成，不播放过渡动画。"
            pref: "reduce_motion"
            kind: "switch"
        }
        SettingRow {
            title: "灵动岛悬停放大"
            description: "鼠标经过屏幕顶部的灵动岛时轻微放大。"
            pref: "bar_hover_zoom"
            kind: "switch"
        }
    }
}
