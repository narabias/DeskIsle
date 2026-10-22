// Settings · 小组件: clock defaults, weather location / units, and the custom
// widget folder (QML / HTML widgets, theme.json) with its problems.
import QtQuick

Column {
    id: page
    property var win: null
    readonly property var p: Desk.prefs
    property var cityResults: []
    property bool citySearching: false
    width: parent ? parent.width : 640
    spacing: 22

    Connections {
        target: Weather
        function onSearchFinished(results) {
            page.cityResults = results
            page.citySearching = false
        }
    }
    Timer {
        id: cityDebounce
        interval: 450
        onTriggered: {
            if (cityField.text.trim() !== "") {
                page.citySearching = true
                Weather.searchCity(cityField.text)
            } else {
                page.cityResults = []
            }
        }
    }

    // ---- 时钟 ------------------------------------------------------------------------
    SettingsCard {
        title: "时钟"
        note: "这里是所有时钟小组件的默认设置；单个时钟可以在它的右键菜单中另行设置。"
        SettingRow {
            title: "时钟样式"
            description: page.p.clock_style === "analog" ? "指针：圆形表盘与流畅的秒针。"
                       : page.p.clock_style === "split" ? "翻页：像翻页钟一样逐位翻动的数字卡片。"
                       : "数字：大号数字时间与日期。"
            pref: "clock_style"
            kind: "segmented"
            options: [
                { value: "digital", text: "数字" },
                { value: "analog", text: "指针" },
                { value: "split", text: "翻页" }
            ]
        }
        SettingRow {
            title: "24 小时制"
            description: "关闭后使用 12 小时制并显示上午 / 下午。"
            pref: "clock_24h"
            kind: "switch"
        }
        SettingRow {
            visible: page.p.clock_style !== "split"   // flip cards have no seconds
            title: "显示秒"
            pref: "clock_seconds"
            kind: "switch"
        }
        SettingRow {
            title: "显示农历"
            description: "在日期旁显示农历、节气与传统节日。"
            pref: "clock_lunar"
            kind: "switch"
        }
    }

    // ---- 天气 ------------------------------------------------------------------------
    SettingsCard {
        title: "天气"
        note: "天气来自 MSN 天气（与 Windows 任务栏天气相同），不可用时改用 Open-Meteo。"
        SettingRow {
            title: "自动定位"
            description: (Desk.isWindows ? "使用 Windows 定位服务（需要在系统“隐私和安全性 › 定位”中允许）；不可用时按网络位置估算。"
                                         : "按网络位置估算所在城市。")
                         + (Weather.locationNote ? " " + Weather.locationNote : "")
            pref: "weather_auto_location"
            kind: "switch"
            onChanged: (v) => {
                if (v) {
                    Weather.useAutoLocation()
                }
            }
        }
        SettingRow {
            id: cityRow
            visible: !page.p.weather_auto_location
            title: "城市"
            description: page.p.weather_city ? "当前：" + page.p.weather_city : "尚未选择城市，请在下方搜索。"
            stacked: true
            GTextField {
                id: cityField
                width: Math.min(cityRow.width - 32, 380)
                layerWindow: false
                icon: "map-pin"
                placeholder: "输入城市名称，例如：杭州、Tokyo"
                fontSize: 13
                onEdited: cityDebounce.restart()
                onAccepted: {
                    cityDebounce.stop()
                    cityDebounce.triggered()
                }
            }
        }
        Column {
            visible: cityRow.visible && (page.cityResults.length > 0 || page.citySearching)
            width: parent.width
            bottomPadding: 8
            Text {
                visible: page.citySearching
                x: 18
                height: 30
                verticalAlignment: Text.AlignVCenter
                text: "正在搜索…"
                color: Theme.textDim
                font.family: Theme.fontFamily
                font.pixelSize: 12
            }
            Repeater {
                model: page.cityResults
                delegate: Item {
                    id: city
                    required property var modelData
                    width: parent ? parent.width : 600
                    height: 44
                    Rectangle {
                        x: 10
                        width: parent.width - 20
                        height: parent.height - 4
                        y: 2
                        radius: 9
                        color: cityArea.containsMouse ? Theme.hover : "transparent"
                    }
                    Glyph {
                        x: 22
                        anchors.verticalCenter: parent.verticalCenter
                        name: "map-pin"
                        size: 16
                        color: Theme.accent
                    }
                    Text {
                        id: cityName
                        x: 48
                        anchors.verticalCenter: parent.verticalCenter
                        text: city.modelData.name
                        color: Theme.text
                        font.family: Theme.fontFamily
                        font.pixelSize: 14
                    }
                    Text {
                        anchors.left: cityName.right
                        anchors.leftMargin: 10
                        anchors.verticalCenter: parent.verticalCenter
                        text: city.modelData.detail
                        color: Theme.textDim
                        font.family: Theme.fontFamily
                        font.pixelSize: 12
                    }
                    MouseArea {
                        id: cityArea
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            Weather.useCity(city.modelData.name, city.modelData.lat, city.modelData.lon)
                            page.cityResults = []
                            cityField.text = ""
                        }
                    }
                }
            }
        }
        SettingRow {
            title: "使用华氏度"
            description: "温度显示为 °F。"
            pref: "weather_fahrenheit"
            kind: "switch"
        }
        SettingRow {
            title: "天气数据"
            description: {
                var d = Weather.data || {}
                var parts = []
                if (d.city) {
                    parts.push(d.city)
                }
                if (d.source) {
                    parts.push(d.source)
                }
                if (d.updated) {
                    parts.push("更新于 " + d.updated)
                }
                var line = parts.join(" · ")
                var st = Weather.status
                if (st && st !== d.source) {
                    line = line ? line + "。" + st : st
                }
                return line || "尚未获取天气。"
            }
            GButton {
                text: Weather.loading ? "正在更新…" : "立即刷新"
                icon: "refresh"
                compact: true
                enabled: !Weather.loading
                onClicked: Weather.refresh(true)
            }
        }
    }

    // ---- 自定义小组件 ------------------------------------------------------------------
    SettingsCard {
        id: customCard
        title: "自定义小组件"
        note: "每个小组件是自定义文件夹 widgets 下的一个子文件夹（widget.json + index.html 或 Widget.qml），保存后自动热重载；"
              + "theme.json 可以调整圆角、阴影等视觉参数。AI 助手也可以替你编写小组件，详见“AI 与扩展”。"
        SettingRow {
            title: "自定义文件夹"
            description: Custom.folderPath + (page.p.custom_folder ? "" : "（默认位置）")
            GButton {
                text: "打开"
                icon: "folder-open"
                compact: true
                onClicked: Custom.openFolder()
            }
            GButton {
                text: "更换…"
                compact: true
                onClicked: {
                    var folder = Desk.pickFolder()
                    if (folder) {
                        Desk.setPref("custom_folder", folder)
                    }
                }
            }
            GButton {
                visible: !!page.p.custom_folder
                text: "恢复默认"
                kind: "ghost"
                compact: true
                onClicked: Desk.setPref("custom_folder", "")
            }
            IconButton {
                icon: "refresh"
                tip: "重新加载"
                onClicked: Custom.reload()
            }
        }
        Repeater {
            model: Custom.widgetList
            delegate: Item {
                id: w
                required property var modelData
                readonly property bool broken: !!modelData.error
                width: parent ? parent.width : 600
                height: Math.max(60, info.implicitHeight + 24)
                Rectangle {
                    x: 16
                    width: parent.width - 32
                    height: 1
                    color: Theme.hairline
                }
                Rectangle {
                    x: 16
                    anchors.verticalCenter: parent.verticalCenter
                    width: 34
                    height: 34
                    radius: 10
                    color: w.broken ? Qt.rgba(Theme.danger.r, Theme.danger.g, Theme.danger.b, 0.16) : Theme.accentSoft
                    Glyph {
                        anchors.centerIn: parent
                        name: w.broken ? "alert-triangle" : (w.modelData.type === "qml" ? "code" : "world")
                        size: 18
                        color: w.broken ? Theme.danger : Theme.accent
                    }
                }
                Column {
                    id: info
                    x: 62
                    anchors.verticalCenter: parent.verticalCenter
                    width: parent.width - x - addButton.width - 32
                    spacing: 2
                    Text {
                        width: parent.width
                        elide: Text.ElideRight
                        text: w.modelData.name + (w.modelData.version ? "  v" + w.modelData.version : "")
                        color: Theme.text
                        font.family: Theme.fontFamily
                        font.pixelSize: 14
                    }
                    Text {
                        width: parent.width
                        wrapMode: Text.Wrap
                        maximumLineCount: 3
                        elide: Text.ElideRight
                        text: w.broken ? w.modelData.error
                              : [w.modelData.description || "", (w.modelData.type === "qml" ? "QML" : "HTML")
                                 + (w.modelData.network ? " · 需要网络" : "") + " · " + w.modelData.id]
                                .filter(function (s) { return s !== "" }).join("  ·  ")
                        color: w.broken ? Theme.danger : Theme.textDim
                        font.family: Theme.fontFamily
                        font.pixelSize: 12
                    }
                }
                GButton {
                    id: addButton
                    anchors.right: parent.right
                    anchors.rightMargin: 16
                    anchors.verticalCenter: parent.verticalCenter
                    text: "添加到桌面"
                    icon: "plus"
                    compact: true
                    enabled: !w.broken
                    onClicked: {
                        if (Custom.addWidget(w.modelData.id)) {
                            Desk.postNotice("已添加小组件", w.modelData.name, "success")
                        }
                    }
                }
            }
        }
        SettingRow {
            visible: Custom.widgetList.length === 0
            title: "还没有自定义小组件"
            description: "在下方新建一个，或把别人分享的小组件文件夹放进 widgets 文件夹。"
        }
        SettingRow {
            id: createRow
            title: "新建小组件"
            description: "从 HTML 示例模板创建一个新的小组件文件夹，然后用任意编辑器修改。"
            GTextField {
                id: newName
                width: 200
                layerWindow: false
                placeholder: "小组件名称"
                fontSize: 13
                onAccepted: createButton.clicked()
            }
            GButton {
                id: createButton
                text: "创建"
                icon: "plus"
                kind: "accent"
                compact: true
                anchors.verticalCenter: parent.verticalCenter
                onClicked: {
                    var id = Custom.createWidget(newName.text.trim() || "我的小组件")
                    if (id) {
                        newName.text = ""
                        Desk.postNotice("已创建小组件", "widgets/" + id + " · 编辑 index.html 后会自动刷新", "success")
                    } else {
                        Desk.postNotice("无法创建小组件", "请检查自定义文件夹是否可写。", "warning")
                    }
                }
            }
        }
        Column {
            visible: Custom.problemList.length > 0
            width: parent.width
            topPadding: 6
            bottomPadding: 12
            spacing: 6
            Repeater {
                model: Custom.problemList
                delegate: Row {
                    required property var modelData
                    x: 16
                    spacing: 8
                    Glyph {
                        name: "alert-triangle"
                        size: 15
                        color: Theme.danger
                    }
                    Text {
                        width: customCard.width - 72
                        wrapMode: Text.Wrap
                        text: String(modelData)
                        color: Theme.danger
                        font.family: Theme.fontFamily
                        font.pixelSize: 12
                    }
                }
            }
        }
    }
}
