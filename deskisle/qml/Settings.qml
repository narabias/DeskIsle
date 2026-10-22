// DeskIsle settings: one window (App.open_settings keeps a single instance).
// `page` is the request: "<section>" or "<section>:<row title>" (jumps to and
// highlights that row).  Backdrop = the blurred primary wallpaper under a
// theme veil, so the window carries the same colours as the desk.
import QtQuick
import QtQuick.Window
import QtQuick.Effects

Window {
    id: win
    // GTextField: fields here take the keyboard with the window itself.
    readonly property bool ownFocus: true
    property string page: "appearance"
    property string section: "appearance"
    property string wallSrc: App.primaryWallSource()
    property string query: ""
    property bool updateDot: false

    readonly property var pages: [
        { id: "appearance", title: "外观", icon: "palette", file: "SettingsAppearance.qml",
          subtitle: "主题、强调色、玻璃质感、壁纸与文字" },
        { id: "desktop", title: "桌面", icon: "device-desktop", file: "SettingsDesktop.qml",
          subtitle: "桌面图标、归流规则、排布、唤醒方式与性能" },
        { id: "widgets", title: "小组件", icon: "apps", file: "SettingsWidgets.qml",
          subtitle: "时钟、天气与自定义小组件" },
        { id: "ai", title: "AI 与扩展", icon: "robot", file: "SettingsAgent.qml",
          subtitle: "让 AI 助手通过 MCP 或命令行帮你整理桌面" },
        { id: "about", title: "关于", icon: "info-circle", file: "SettingsAbout.qml",
          subtitle: "版本与更新、数据位置与开源组件" }
    ]
    readonly property var aliases: ({ general: "desktop", rules: "desktop", update: "about", updates: "about",
                                      agent: "ai", mcp: "ai", weather: "widgets", clock: "widgets",
                                      custom: "widgets", theme: "appearance", wallpaper: "appearance" })
    readonly property var current: {
        for (var i = 0; i < pages.length; ++i) {
            if (pages[i].id === section) {
                return pages[i]
            }
        }
        return pages[0]
    }

    // Settings search: [section, row title, extra keywords].  Every title must
    // exist in its page file (tests/test_qml_static.py checks this).
    readonly property var searchIndex: [
        ["appearance", "主题模式", "深色 浅色 暗色 夜间 白天 dark light 跟随系统 跟随壁纸 自动"],
        ["appearance", "白天开始", "时间 浅色 早上"],
        ["appearance", "夜间开始", "时间 深色 晚上"],
        ["appearance", "强调色", "颜色 主色 配色 accent 壁纸取色"],
        ["appearance", "默认材质", "毛玻璃 液态玻璃 清透 材质 glass"],
        ["appearance", "玻璃浓度", "模糊 透明度 折射 浓淡"],
        ["appearance", "背景来源", "动态壁纸 静态壁纸 图片 纯色 wallpaper engine lively"],
        ["appearance", "动态壁纸刷新率", "帧率 fps 耗电"],
        ["appearance", "背景图片", "自定义图片 选择图片"],
        ["appearance", "字体", "字型 font 导入字体 微软雅黑"],
        ["appearance", "字号", "文字大小 字体大小 size"],
        ["appearance", "文字颜色", "字体颜色 字色 浅色文字 深色文字 自定义颜色 color"],
        ["appearance", "减弱动态效果", "动画 过渡 motion 晕动"],
        ["appearance", "灵动岛悬停放大", "顶部 放大 动画"],
        ["desktop", "由桌屿显示桌面图标", "原生图标 隐藏图标 桌面图标"],
        ["desktop", "自动归流", "自动整理 新文件 规则"],
        ["desktop", "归流规则", "规则 扩展名 分类 整理 rules"],
        ["desktop", "使用 Everything 搜索", "搜索 everything 索引 查找文件"],
        ["desktop", "吸附到网格", "网格 对齐 snap"],
        ["desktop", "网格尺寸", "网格 吸附"],
        ["desktop", "收纳岛间距", "间距 间隔 gap 排布"],
        ["desktop", "按显示器组合记忆布局", "多显示器 显示器 投影 扩展屏 布局记忆"],
        ["desktop", "重新连接等待", "显示器 断开 插拔"],
        ["desktop", "布局快照", "快照 备份 恢复 导入 导出 布局 删除快照"],
        ["desktop", "双击桌面空白处", "唤醒 隐藏 双击"],
        ["desktop", "胶囊悬停预览", "胶囊 收拢 预览 延迟"],
        ["desktop", "全局快捷键", "快捷键 热键 hotkey 键盘"],
        ["desktop", "守护桌面层", "守护 看门狗 崩溃 自动重启 watchdog"],
        ["desktop", "开机自动启动", "启动 开机 自启"],
        ["desktop", "无人观看时暂停", "暂停 省电 全屏 游戏"],
        ["desktop", "视频帧率上限", "帧率 视频 动画 fps"],
        ["desktop", "空闲时释放内存", "内存 占用 释放 性能 卡顿 memory"],
        ["desktop", "当前内存占用", "内存 占用 释放 webview2 进程"],
        ["desktop", "网页显示方式", "webview2 网页 合成 窗口"],
        ["widgets", "时钟样式", "时钟 数字 指针 翻页 表盘"],
        ["widgets", "24 小时制", "时钟 12 小时 上午 下午"],
        ["widgets", "显示秒", "时钟 秒针"],
        ["widgets", "显示农历", "农历 节气 节日 阴历"],
        ["widgets", "自动定位", "天气 定位 位置 城市"],
        ["widgets", "城市", "天气 城市 搜索 位置"],
        ["widgets", "使用华氏度", "天气 温度 华氏 摄氏"],
        ["widgets", "天气数据", "天气 刷新 MSN"],
        ["widgets", "自定义文件夹", "自定义 小组件 文件夹 html qml theme.json"],
        ["widgets", "新建小组件", "自定义 小组件 创建 html"],
        ["ai", "允许 AI 助手控制桌屿", "ai 智能体 agent 助手 mcp 接口"],
        ["ai", "MCP 配置", "mcp claude cursor 配置 json"],
        ["ai", "命令行", "cli 命令 脚本 终端"],
        ["ai", "说明文档", "guide 文档 命令列表"],
        ["about", "软件更新", "更新 版本 升级 检查更新"],
        ["about", "自动检查更新", "更新 自动"],
        ["about", "数据目录", "数据 配置 文件夹 备份"],
        ["about", "运行日志", "日志 log 反馈 问题"],
        ["about", "使用说明", "说明 帮助 教程 常见问题 快捷键"],
        ["about", "更新日志", "更新日志 版本 变化 changelog"],
        ["about", "开源组件", "许可 license 第三方 开源"]
    ]
    readonly property var results: {
        var q = query.trim().toLowerCase()
        if (q === "") {
            return []
        }
        var words = q.split(/\s+/)
        var found = []
        for (var i = 0; i < searchIndex.length; ++i) {
            var entry = searchIndex[i]
            var hay = (entry[1] + " " + entry[2]).toLowerCase()
            var ok = true
            for (var w = 0; w < words.length; ++w) {
                if (hay.indexOf(words[w]) < 0) {
                    ok = false
                    break
                }
            }
            if (ok) {
                found.push({ section: entry[0], title: entry[1], pageTitle: titleOf(entry[0]),
                             exact: entry[1].toLowerCase().indexOf(q) >= 0 })
            }
        }
        found.sort(function (a, b) { return (b.exact ? 1 : 0) - (a.exact ? 1 : 0) })
        return found.slice(0, 14)
    }
    property int resultIndex: 0
    onResultsChanged: resultIndex = 0

    function titleOf(id) {
        for (var i = 0; i < pages.length; ++i) {
            if (pages[i].id === id) {
                return pages[i].title
            }
        }
        return ""
    }
    function go(id, rowTitle) {
        id = aliases[id] || id
        if (titleOf(id) === "") {
            id = "appearance"
        }
        pendingReveal = rowTitle || ""
        if (id !== section) {
            section = id
        } else if (pendingReveal !== "") {
            revealTimer.restart()
        } else {
            flick.contentY = 0
        }
    }
    function openResult(entry) {
        if (!entry) {
            return
        }
        query = ""
        searchField.text = ""
        searchField.release()
        go(entry.section, entry.title)
    }
    property string pendingReveal: ""
    function request(text) {
        if (!text) {
            return
        }
        var cut = text.indexOf(":")
        go(cut < 0 ? text : text.slice(0, cut), cut < 0 ? "" : text.slice(cut + 1))
    }
    onPageChanged: request(page)
    Component.onCompleted: {
        request(page)
        win.updateDot = !!App.updateInfo().available
    }

    function findRow(item, title) {
        if (!item) {
            return null
        }
        if (item.title === title && item.flash !== undefined && item.visible) {
            return item
        }
        var kids = item.children
        for (var i = 0; i < kids.length; ++i) {
            var hit = findRow(kids[i], title)
            if (hit) {
                return hit
            }
        }
        return null
    }
    function reveal(title) {
        var row = findRow(pageLoader.item, title)
        if (!row) {
            return
        }
        var y = row.mapToItem(flick.contentItem, 0, 0).y
        var target = Math.max(0, Math.min(y - 96, flick.contentHeight - flick.height))
        scrollAnim.stop()
        scrollAnim.to = target
        scrollAnim.start()
        row.flash()
    }

    width: 1000
    height: 720
    minimumWidth: 840
    minimumHeight: 560
    title: "桌屿设置"
    color: Theme.dark ? "#14171C" : "#EEF0F3"

    Connections {
        target: App
        function onWallChanged() {
            if (!wallThrottle.running) {
                wallThrottle.start()
            }
        }
        function onInfoChanged() {
            win.updateDot = !!App.updateInfo().available
        }
    }
    // The backdrop is a blurred still of the wallpaper: refreshed when the window opens and at
    // most every 30 s while it is open (a live wallpaper changes constantly; following every
    // frame made the whole window flicker), always with a cross-fade.
    Timer {
        id: wallThrottle
        interval: 30000
        onTriggered: win.wallSrc = App.primaryWallSource()
    }
    onVisibleChanged: if (visible) win.wallSrc = App.primaryWallSource()
    Timer {
        id: revealTimer
        interval: 80
        onTriggered: {
            if (win.pendingReveal !== "") {
                win.reveal(win.pendingReveal)
                win.pendingReveal = ""
            }
        }
    }

    Shortcut {
        sequences: [StandardKey.Find]
        onActivated: searchField.focusField()
    }
    Shortcut {
        sequences: [StandardKey.Close]
        onActivated: win.close()
    }
    Shortcut {
        sequence: "Ctrl+Tab"
        onActivated: win.cycle(1)
    }
    Shortcut {
        sequence: "Ctrl+Shift+Tab"
        onActivated: win.cycle(-1)
    }
    function cycle(step) {
        for (var i = 0; i < pages.length; ++i) {
            if (pages[i].id === section) {
                go(pages[(i + step + pages.length) % pages.length].id, "")
                return
            }
        }
    }

    // ---- backdrop ----------------------------------------------------------------
    Item {
        id: wallBox
        anchors.fill: parent
        visible: false
        property bool useA: true
        property string src: win.wallSrc
        Component.onCompleted: wallA.source = src
        onSrcChanged: {
            if (useA) {
                wallB.source = src
            } else {
                wallA.source = src
            }
        }
        Image {
            id: wallA
            anchors.fill: parent
            sourceSize.width: 480
            fillMode: Image.PreserveAspectCrop
            asynchronous: true
            cache: false
            opacity: wallBox.useA ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: Theme.ms(600); easing.type: Easing.InOutQuad } }
            onStatusChanged: if (status === Image.Ready && !wallBox.useA && source == wallBox.src) wallBox.useA = true
        }
        Image {
            id: wallB
            anchors.fill: parent
            sourceSize.width: 480
            fillMode: Image.PreserveAspectCrop
            asynchronous: true
            cache: false
            opacity: wallBox.useA ? 0 : 1
            Behavior on opacity { NumberAnimation { duration: Theme.ms(600); easing.type: Easing.InOutQuad } }
            onStatusChanged: if (status === Image.Ready && wallBox.useA && source == wallBox.src) wallBox.useA = false
        }
    }
    MultiEffect {
        anchors.fill: parent
        source: wallBox
        visible: wallA.status === Image.Ready || wallB.status === Image.Ready
        autoPaddingEnabled: false
        blurEnabled: true
        blur: 1.0
        blurMax: 64
        saturation: 0.1
    }
    Rectangle {
        anchors.fill: parent
        color: Theme.dark ? Qt.rgba(0.075, 0.085, 0.105, 0.80) : Qt.rgba(0.945, 0.952, 0.965, 0.80)
        Behavior on color { ColorAnimation { duration: Theme.ms(260) } }
    }

    // ---- sidebar --------------------------------------------------------------------
    Item {
        id: sidebar
        width: 236
        height: parent.height

        Row {
            id: brand
            x: 22
            y: 24
            spacing: 12
            Image {
                width: 40
                height: 40
                source: "../assets/ui/app-icon.png"
                sourceSize: Qt.size(80, 80)
                smooth: true
                mipmap: true
            }
            Column {
                anchors.verticalCenter: parent.verticalCenter
                spacing: 1
                Text {
                    text: "桌屿"
                    color: Theme.text
                    font.family: Theme.fontFamily
                    font.pixelSize: 18
                    font.weight: Font.DemiBold
                }
                Text {
                    text: "DeskIsle " + Desk.version
                    color: Theme.textDim
                    font.family: Theme.fontFamily
                    font.pixelSize: 12
                }
            }
        }

        GTextField {
            id: searchField
            x: 16
            y: brand.y + brand.height + 22
            width: sidebar.width - 32
            layerWindow: false
            icon: "search"
            placeholder: "搜索设置"
            fontSize: 13
            onEdited: win.query = text
            onAccepted: win.openResult(win.results[win.resultIndex])
            onEscaped: {
                text = ""
                win.query = ""
                release()
            }
            onDownPressed: win.resultIndex = Math.min(win.results.length - 1, win.resultIndex + 1)
            onUpPressed: win.resultIndex = Math.max(0, win.resultIndex - 1)
        }

        // Navigation (or search results while typing)
        Column {
            id: nav
            x: 12
            y: searchField.y + searchField.height + 14
            width: sidebar.width - 24
            spacing: 2
            visible: win.query.trim() === ""
            Repeater {
                model: win.pages
                delegate: Item {
                    id: navItem
                    required property var modelData
                    readonly property bool on: modelData.id === win.section
                    width: nav.width
                    height: 42
                    Rectangle {
                        anchors.fill: parent
                        radius: 10
                        color: navItem.on ? (Theme.dark ? Qt.rgba(1, 1, 1, 0.09) : Qt.rgba(1, 1, 1, 0.78))
                                          : (navArea.containsMouse ? Theme.hover : "transparent")
                        border.width: navItem.on && !Theme.dark ? 1 : 0
                        border.color: Theme.hairline
                        Behavior on color { ColorAnimation { duration: Theme.ms(120) } }
                    }
                    Rectangle {
                        // selection marker
                        x: 0
                        width: 3
                        radius: 1.5
                        height: navItem.on ? 18 : 0
                        anchors.verticalCenter: parent.verticalCenter
                        color: Theme.accent
                        Behavior on height { NumberAnimation { duration: Theme.ms(180); easing.type: Easing.OutCubic } }
                    }
                    Glyph {
                        x: 14
                        anchors.verticalCenter: parent.verticalCenter
                        name: navItem.modelData.icon
                        size: 19
                        color: navItem.on ? Theme.accent : Theme.textDim
                    }
                    Text {
                        x: 44
                        anchors.verticalCenter: parent.verticalCenter
                        text: navItem.modelData.title
                        color: Theme.text
                        font.family: Theme.fontFamily
                        font.pixelSize: 14
                        font.weight: navItem.on ? Font.DemiBold : Font.Normal
                    }
                    Rectangle {
                        // "update available" dot on 关于
                        visible: navItem.modelData.id === "about" && win.updateDot
                        width: 8
                        height: 8
                        radius: 4
                        color: Theme.accent
                        anchors.right: parent.right
                        anchors.rightMargin: 14
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    MouseArea {
                        id: navArea
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: win.go(navItem.modelData.id, "")
                    }
                }
            }
        }
        Column {
            id: resultList
            x: 12
            y: nav.y
            width: sidebar.width - 24
            spacing: 2
            visible: !nav.visible
            Text {
                visible: win.results.length === 0
                width: parent.width
                leftPadding: 10
                topPadding: 8
                wrapMode: Text.Wrap
                text: "没有找到“" + win.query.trim() + "”相关的设置"
                color: Theme.textDim
                font.family: Theme.fontFamily
                font.pixelSize: 13
            }
            Repeater {
                model: win.results
                delegate: Item {
                    id: hit
                    required property var modelData
                    required property int index
                    width: resultList.width
                    height: 48
                    Rectangle {
                        anchors.fill: parent
                        radius: 10
                        color: hit.index === win.resultIndex ? Theme.accentSoft
                               : (hitArea.containsMouse ? Theme.hover : "transparent")
                    }
                    Column {
                        x: 12
                        anchors.verticalCenter: parent.verticalCenter
                        width: parent.width - 24
                        spacing: 2
                        Text {
                            width: parent.width
                            elide: Text.ElideRight
                            text: hit.modelData.title
                            color: Theme.text
                            font.family: Theme.fontFamily
                            font.pixelSize: 14
                        }
                        Text {
                            text: hit.modelData.pageTitle
                            color: Theme.textDim
                            font.family: Theme.fontFamily
                            font.pixelSize: 11
                        }
                    }
                    MouseArea {
                        id: hitArea
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onEntered: win.resultIndex = hit.index
                        onClicked: win.openResult(hit.modelData)
                    }
                }
            }
        }

        // Footer: quick links
        Column {
            x: 12
            width: sidebar.width - 24
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 16
            spacing: 2
            Repeater {
                model: [
                    { icon: "eye-off", text: Desk.hidden ? "显示桌面收纳岛" : "暂时隐藏收纳岛", act: "hide" },
                    { icon: "power", text: "退出桌屿", act: "quit" }
                ]
                delegate: Item {
                    id: foot
                    required property var modelData
                    width: parent.width
                    height: 36
                    Rectangle {
                        anchors.fill: parent
                        radius: 9
                        color: footArea.containsMouse ? Theme.hover : "transparent"
                    }
                    Glyph {
                        x: 14
                        anchors.verticalCenter: parent.verticalCenter
                        name: foot.modelData.icon
                        size: 16
                        color: foot.modelData.act === "quit" ? Theme.danger : Theme.textDim
                    }
                    Text {
                        x: 44
                        anchors.verticalCenter: parent.verticalCenter
                        text: foot.modelData.text
                        color: foot.modelData.act === "quit" ? Theme.danger : Theme.textDim
                        font.family: Theme.fontFamily
                        font.pixelSize: 13
                    }
                    MouseArea {
                        id: footArea
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            if (foot.modelData.act === "quit") {
                                Desk.requestQuit()
                            } else {
                                Desk.toggleHidden()
                            }
                        }
                    }
                }
            }
        }
    }

    // ---- content ---------------------------------------------------------------------
    Item {
        id: contentArea
        x: sidebar.width
        width: parent.width - sidebar.width
        height: parent.height

        Flickable {
            id: flick
            anchors.fill: parent
            anchors.rightMargin: 4
            contentWidth: width
            contentHeight: body.height + 56
            boundsBehavior: Flickable.StopAtBounds
            flickDeceleration: 3200
            maximumFlickVelocity: 5200
            clip: true

            NumberAnimation {
                id: scrollAnim
                target: flick
                property: "contentY"
                duration: Theme.ms(320)
                easing.type: Easing.OutCubic
            }

            Column {
                id: body
                x: 28
                y: 28
                width: Math.min(flick.width - 64, 820)
                spacing: 22

                Column {
                    id: header
                    width: parent.width
                    spacing: 4
                    Text {
                        text: win.current.title
                        color: Theme.text
                        font.family: Theme.fontFamily
                        font.pixelSize: 26
                        font.weight: Font.DemiBold
                    }
                    Text {
                        width: parent.width
                        wrapMode: Text.Wrap
                        text: win.current.subtitle
                        color: Theme.textDim
                        font.family: Theme.fontFamily
                        font.pixelSize: 13
                    }
                }
                Loader {
                    id: pageLoader
                    width: parent.width
                    source: win.current.file
                    transform: Translate { id: pageShift }
                    onLoaded: {
                        item.win = win
                        flick.contentY = 0
                        pageIn.restart()
                        if (win.pendingReveal !== "") {
                            revealTimer.restart()
                        }
                    }
                    ParallelAnimation {
                        id: pageIn
                        NumberAnimation { target: pageLoader; property: "opacity"; from: 0; to: 1; duration: Theme.ms(200) }
                        NumberAnimation { target: pageShift; property: "y"; from: 10; to: 0; duration: Theme.ms(260); easing.type: Easing.OutCubic }
                    }
                }
            }
        }

        // Thin scroll indicator (draggable)
        Item {
            id: scrollTrack
            anchors.right: parent.right
            anchors.rightMargin: 4
            y: 8
            width: 8
            height: parent.height - 16
            visible: flick.contentHeight > flick.height + 1
            opacity: trackArea.containsMouse || trackArea.pressed || flick.moving || scrollAnim.running ? 1 : 0.45
            Behavior on opacity { NumberAnimation { duration: Theme.ms(200) } }
            readonly property real ratio: Math.min(1, flick.height / Math.max(1, flick.contentHeight))
            Rectangle {
                id: thumb
                width: trackArea.containsMouse || trackArea.pressed ? 8 : 5
                anchors.right: parent.right
                radius: width / 2
                height: Math.max(36, scrollTrack.height * scrollTrack.ratio)
                y: (scrollTrack.height - height) * (flick.contentY / Math.max(1, flick.contentHeight - flick.height))
                color: Theme.dark ? Qt.rgba(1, 1, 1, 0.32) : Qt.rgba(0, 0, 0, 0.30)
                Behavior on width { NumberAnimation { duration: Theme.ms(120) } }
            }
            MouseArea {
                id: trackArea
                anchors.fill: parent
                anchors.leftMargin: -6
                hoverEnabled: true
                property real grab: 0
                onPressed: (mouse) => {
                    grab = mouse.y >= thumb.y && mouse.y <= thumb.y + thumb.height ? mouse.y - thumb.y : thumb.height / 2
                    scrollTo(mouse.y)
                }
                onPositionChanged: (mouse) => { if (pressed) scrollTo(mouse.y) }
                function scrollTo(my) {
                    var span = Math.max(1, scrollTrack.height - thumb.height)
                    var r = Math.max(0, Math.min(1, (my - grab) / span))
                    flick.contentY = r * Math.max(0, flick.contentHeight - flick.height)
                }
            }
        }
    }

    // ---- toast: notices raised while this window is in front ----------------------
    Connections {
        target: Desk.noticesModel
        function onRowsInserted(parent, first, last) {
            if (win.active) {
                var n = Desk.noticesModel.at(last)
                if (n) {
                    toast.show(n.title, n.text, n.kind)
                }
            }
        }
    }
    Rectangle {
        id: toast
        property string kind: "info"
        property string head: ""
        property string body: ""
        function show(t, b, k) {
            toast.head = t
            toast.body = b || ""
            toast.kind = k || "info"
            toastTimer.restart()
            toast.shown = true
        }
        property bool shown: false
        x: contentArea.x + Math.round((contentArea.width - width) / 2)
        y: win.height - height - 22 + (shown ? 0 : 14)
        width: Math.min(contentArea.width - 48, toastRow.implicitWidth + 32)
        height: toastRow.implicitHeight + 20
        radius: height / 2 > 22 ? 16 : height / 2
        opacity: shown ? 1 : 0
        visible: opacity > 0.01
        color: Theme.dark ? Qt.rgba(0.13, 0.14, 0.17, 0.97) : Qt.rgba(1, 1, 1, 0.98)
        border.width: 1
        border.color: Theme.hairline
        Behavior on opacity { NumberAnimation { duration: Theme.ms(180) } }
        Behavior on y { NumberAnimation { duration: Theme.ms(220); easing.type: Easing.OutCubic } }
        Timer {
            id: toastTimer
            interval: 3200
            onTriggered: toast.shown = false
        }
        Row {
            id: toastRow
            x: 16
            anchors.verticalCenter: parent.verticalCenter
            spacing: 10
            Glyph {
                anchors.verticalCenter: parent.verticalCenter
                name: toast.kind === "warning" || toast.kind === "error" ? "alert-triangle" : "circle-check"
                size: 17
                color: toast.kind === "error" ? Theme.danger : toast.kind === "warning" ? "#F5A524"
                     : toast.kind === "success" ? "#34C77B" : Theme.accent
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                width: Math.min(implicitWidth, contentArea.width - 120)
                elide: Text.ElideRight
                text: toast.body !== "" ? toast.head + "  ·  " + toast.body : toast.head
                color: Theme.text
                font.family: Theme.fontFamily
                font.pixelSize: 13
            }
        }
    }

    // ---- confirmation sheet (same request as the desktop ConfirmCard) --------------
    Item {
        id: sheet
        anchors.fill: parent
        readonly property var info: Desk.confirmInfo
        readonly property bool open: !!info && !!info.id && win.active
        property var shownInfo: ({})
        onInfoChanged: if (info && info.id) shownInfo = info
        visible: opacity > 0.01
        opacity: open ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: Theme.ms(160) } }
        Rectangle {
            anchors.fill: parent
            color: Qt.rgba(0, 0, 0, Theme.dark ? 0.45 : 0.25)
        }
        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.AllButtons
            onWheel: (wheel) => wheel.accepted = true
        }
        Rectangle {
            id: sheetCard
            width: 440
            height: sheetCol.implicitHeight + 40
            anchors.centerIn: parent
            radius: 18
            scale: sheet.open ? 1 : 0.95
            Behavior on scale { NumberAnimation { duration: Theme.ms(220); easing.type: Easing.OutBack } }
            color: Theme.dark ? "#22252B" : "#FFFFFF"
            border.width: 1
            border.color: Theme.hairline
            Column {
                id: sheetCol
                x: 22
                y: 20
                width: parent.width - 44
                spacing: 10
                Row {
                    spacing: 8
                    visible: sheet.shownInfo.source === "agent"
                    Glyph { name: "robot"; size: 15; color: Theme.accent; anchors.verticalCenter: parent.verticalCenter }
                    Text {
                        text: "来自 AI 助手的请求"
                        color: Theme.accent
                        font.family: Theme.fontFamily
                        font.pixelSize: 12
                        font.weight: Font.DemiBold
                    }
                }
                Text {
                    width: parent.width
                    wrapMode: Text.Wrap
                    text: sheet.shownInfo.title || ""
                    color: Theme.text
                    font.family: Theme.fontFamily
                    font.pixelSize: 17
                    font.weight: Font.DemiBold
                }
                Text {
                    width: parent.width
                    visible: text !== ""
                    wrapMode: Text.Wrap
                    text: sheet.shownInfo.text || ""
                    color: Theme.textDim
                    font.family: Theme.fontFamily
                    font.pixelSize: 13
                    lineHeight: 1.15
                }
                Item { width: 1; height: 6 }
                Row {
                    anchors.right: parent.right
                    spacing: 10
                    GButton {
                        text: "取消"
                        onClicked: Desk.resolveConfirm(sheet.shownInfo.id, false)
                    }
                    GButton {
                        text: sheet.shownInfo.accept || "确定"
                        kind: sheet.shownInfo.danger !== false ? "danger" : "accent"
                        onClicked: Desk.resolveConfirm(sheet.shownInfo.id, true)
                    }
                }
            }
        }
        Shortcut {
            enabled: sheet.open
            sequence: "Esc"
            onActivated: Desk.resolveConfirm(sheet.shownInfo.id, false)
        }
    }
}
