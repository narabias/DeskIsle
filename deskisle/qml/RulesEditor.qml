// Settings · 桌面 · 归流规则: ordered auto-sort rules (first match wins) with an
// inline editor.  Rules only change where an item is shown - files never move.
import QtQuick

SettingsCard {
    id: card
    title: "归流规则"
    note: "规则从上到下依次匹配，第一条符合的规则生效。规则只改变项目在桌屿中的归属，不会移动、重命名或删除原文件。"
    property var rules: []
    property var targets: []
    property string editing: ""          // rule id, "new" or ""
    property string armed: ""            // rule id waiting for the second click on 删除

    readonly property var conditionLabels: ({ extension: "扩展名属于", name_contains: "名称包含",
                                              name_starts: "名称开头是", name_ends: "名称结尾是",
                                              kind: "项目类型是" })
    readonly property var kindOptions: [
        { value: "folder", text: "文件夹" }, { value: "shortcut", text: "快捷方式" },
        { value: "image", text: "图片" }, { value: "document", text: "文档" },
        { value: "media", text: "音频或视频" }, { value: "archive", text: "压缩包" }
    ]

    function reload() {
        rules = Desk.ruleList()
        targets = Desk.ruleTargets()
    }
    function kindText(value) {
        var parts = String(value).split(/[,;|]/)
        var out = []
        for (var i = 0; i < parts.length; ++i) {
            var k = parts[i].trim()
            for (var j = 0; j < kindOptions.length; ++j) {
                if (kindOptions[j].value === k) {
                    out.push(kindOptions[j].text)
                }
            }
        }
        return out.join("、")
    }
    function summary(rule) {
        var v = rule.condition === "kind" ? kindText(rule.value) : rule.value
        return (conditionLabels[rule.condition] || rule.condition) + " " + (v || "（未填写）")
    }
    Component.onCompleted: reload()
    Connections {
        target: Desk
        function onRulesChanged() { card.reload() }
        function onIslandsChanged() { card.reload() }
        function onStateReplaced() { card.reload() }
    }
    Timer {
        id: disarm
        interval: 3000
        onTriggered: card.armed = ""
    }

    // Small toggle chip (kinds, target islands).
    component Chip: Rectangle {
        id: chip
        property string text: ""
        property string sub: ""
        property bool on: false
        signal clicked()
        height: 30
        width: chipRow.implicitWidth + 24
        radius: 15
        color: on ? Theme.accent : (chipArea.containsMouse ? Theme.hover : (Theme.dark ? Qt.rgba(1, 1, 1, 0.06) : Qt.rgba(0, 0, 0, 0.04)))
        border.width: on ? 0 : 1
        border.color: Theme.hairline
        Row {
            id: chipRow
            anchors.centerIn: parent
            spacing: 6
            Text {
                text: chip.text
                color: chip.on ? Theme.onAccent : Theme.text
                font.family: Theme.fontFamily
                font.pixelSize: 13
            }
            Text {
                visible: chip.sub !== ""
                text: chip.sub
                color: chip.on ? Theme.onAccent : Theme.textFaint
                opacity: chip.on ? 0.8 : 1
                font.family: Theme.fontFamily
                font.pixelSize: 11
                anchors.verticalCenter: parent.verticalCenter
            }
        }
        MouseArea {
            id: chipArea
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: chip.clicked()
        }
    }

    component Caption: Text {
        color: Theme.textDim
        font.family: Theme.fontFamily
        font.pixelSize: 12
    }

    // Inline editor for one rule (or a new one).
    component RuleForm: Item {
        id: form
        property var rule: null
        property var host: null              // the RulesEditor (inline components cannot see its id)
        property string fName: ""
        property string fCondition: "extension"
        property string fValue: ""
        property var fKinds: []
        property string fTarget: ""
        property bool fEnabled: true
        property string error: ""
        width: parent ? parent.width : 600
        height: formCol.implicitHeight + 32

        Component.onCompleted: {
            if (rule) {
                fName = rule.name
                fCondition = rule.condition
                fValue = rule.condition === "kind" ? "" : rule.value
                fKinds = rule.condition === "kind" ? String(rule.value).split(/[,;|]/).map(function (s) { return s.trim() }).filter(function (s) { return s !== "" }) : []
                fTarget = rule.target
                fEnabled = rule.enabled
            } else {
                fTarget = form.host.targets.length ? form.host.targets[0].id : ""
            }
            nameField.text = fName
            valueField.text = fValue
        }
        function toggleKind(k) {
            var list = fKinds.slice()
            var at = list.indexOf(k)
            if (at >= 0) {
                list.splice(at, 1)
            } else {
                list.push(k)
            }
            fKinds = list
        }
        function save() {
            var value = fCondition === "kind" ? fKinds.join(",") : valueField.text.trim()
            if (value === "") {
                error = fCondition === "kind" ? "请至少选择一种项目类型。" : "请填写要匹配的内容。"
                return
            }
            if (fTarget === "") {
                error = "请选择要放入的收纳岛。"
                return
            }
            Desk.saveRule({ id: rule ? rule.id : "", name: nameField.text.trim(), condition: fCondition,
                            value: value, target: fTarget, enabled: fEnabled })
            form.host.editing = ""
        }

        Rectangle {
            x: 12
            y: 6
            width: parent.width - 24
            height: parent.height - 12
            radius: 12
            color: Theme.dark ? Qt.rgba(0, 0, 0, 0.20) : Qt.rgba(0, 0, 0, 0.035)
            border.width: 1
            border.color: Theme.hairline
        }
        Column {
            id: formCol
            x: 28
            y: 20
            width: parent.width - 56
            spacing: 10
            Text {
                text: form.rule ? "编辑规则" : "新建规则"
                color: Theme.text
                font.family: Theme.fontFamily
                font.pixelSize: 14
                font.weight: Font.DemiBold
            }
            Caption { text: "规则名称" }
            GTextField {
                id: nameField
                width: Math.min(parent.width, 360)
                layerWindow: false
                placeholder: "例如：自动收纳截图"
                fontSize: 13
            }
            Caption { text: "匹配条件" }
            Segmented {
                compact: true
                current: form.fCondition
                options: [
                    { value: "extension", text: "扩展名" }, { value: "name_contains", text: "名称包含" },
                    { value: "name_starts", text: "名称开头" }, { value: "name_ends", text: "名称结尾" },
                    { value: "kind", text: "项目类型" }
                ]
                onPicked: (v) => { form.fCondition = v; form.error = "" }
            }
            GTextField {
                id: valueField
                visible: form.fCondition !== "kind"
                width: Math.min(parent.width, 360)
                layerWindow: false
                fontSize: 13
                placeholder: form.fCondition === "extension" ? ".png, .jpg, .webp"
                           : form.fCondition === "name_contains" ? "名称中要包含的文字"
                           : form.fCondition === "name_starts" ? "名称开头的文字" : "名称结尾的文字"
                onEdited: form.error = ""
                onAccepted: form.save()
            }
            Flow {
                visible: form.fCondition === "kind"
                width: parent.width
                spacing: 8
                Repeater {
                    model: form.host ? form.host.kindOptions : []
                    delegate: Chip {
                        required property var modelData
                        text: modelData.text
                        on: form.fKinds.indexOf(modelData.value) >= 0
                        onClicked: { form.toggleKind(modelData.value); form.error = "" }
                    }
                }
            }
            Caption {
                visible: form.fCondition !== "kind"
                text: "多个值用逗号分隔，不区分大小写。"
                color: Theme.textFaint
            }
            Caption { text: "放入收纳岛" }
            Flow {
                width: parent.width
                spacing: 8
                Repeater {
                    model: form.host ? form.host.targets : []
                    delegate: Chip {
                        required property var modelData
                        text: modelData.title
                        sub: modelData.page
                        on: form.fTarget === modelData.id
                        onClicked: { form.fTarget = modelData.id; form.error = "" }
                    }
                }
                Caption {
                    visible: !!form.host && form.host.targets.length === 0
                    text: "还没有可以放入的收纳岛，请先在桌面上新建一个普通收纳岛。"
                }
            }
            Row {
                spacing: 10
                GSwitch {
                    anchors.verticalCenter: parent.verticalCenter
                    checked: form.fEnabled
                    onToggled: (v) => form.fEnabled = v
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: "启用此规则"
                    color: Theme.text
                    font.family: Theme.fontFamily
                    font.pixelSize: 13
                }
            }
            Text {
                visible: form.error !== ""
                text: form.error
                color: Theme.danger
                font.family: Theme.fontFamily
                font.pixelSize: 12
            }
            Row {
                spacing: 10
                GButton {
                    text: "保存规则"
                    kind: "accent"
                    icon: "check"
                    onClicked: form.save()
                }
                GButton {
                    text: "取消"
                    kind: "ghost"
                    onClicked: form.host.editing = ""
                }
            }
        }
    }

    // ---- header ------------------------------------------------------------------------
    SettingRow {
        title: card.rules.length ? "共 " + card.rules.length + " 条规则" : "还没有规则"
        description: Desk.prefs.auto_organize ? "新出现在桌面上的项目会自动按规则归入收纳岛。"
                                              : "“自动归流”已关闭：规则只在点“立即归流”时使用。"
        GButton {
            text: "立即归流"
            icon: "filter"
            compact: true
            enabled: card.rules.length > 0
            onClicked: Desk.action("rules.apply", {})
        }
        GButton {
            text: "新建规则"
            icon: "plus"
            kind: "accent"
            compact: true
            onClicked: card.editing = "new"
        }
    }
    Loader {
        width: parent.width
        active: card.editing === "new"
        visible: active
        sourceComponent: RuleForm { host: card }
    }

    // ---- list --------------------------------------------------------------------------
    Repeater {
        model: card.rules
        delegate: Column {
            id: entry
            required property var modelData
            required property int index
            width: parent ? parent.width : 600
            Item {
                width: parent.width
                height: 62
                Rectangle {
                    x: 16
                    width: parent.width - 32
                    height: 1
                    color: Theme.hairline
                }
                GSwitch {
                    id: onSwitch
                    x: 16
                    anchors.verticalCenter: parent.verticalCenter
                    checked: entry.modelData.enabled
                    onToggled: (v) => Desk.setRuleEnabled(entry.modelData.id, v)
                }
                Column {
                    x: onSwitch.x + onSwitch.width + 14
                    anchors.verticalCenter: parent.verticalCenter
                    width: tools.x - x - 12
                    spacing: 3
                    opacity: entry.modelData.enabled ? 1 : 0.55
                    Text {
                        width: parent.width
                        elide: Text.ElideRight
                        text: (entry.index + 1) + ". " + entry.modelData.name
                        color: Theme.text
                        font.family: Theme.fontFamily
                        font.pixelSize: 14
                    }
                    Text {
                        width: parent.width
                        elide: Text.ElideRight
                        text: card.summary(entry.modelData) + "  →  "
                              + (entry.modelData.targetTitle !== ""
                                 ? entry.modelData.targetTitle + "（" + entry.modelData.targetPage + "）"
                                 : "目标收纳岛已不存在")
                        color: entry.modelData.valid ? Theme.textDim : Theme.danger
                        font.family: Theme.fontFamily
                        font.pixelSize: 12
                    }
                }
                Row {
                    id: tools
                    anchors.right: parent.right
                    anchors.rightMargin: 12
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 2
                    IconButton {
                        icon: "chevron-up"
                        tip: "提高优先级"
                        enabled: entry.index > 0
                        onClicked: Desk.moveRule(entry.modelData.id, -1)
                    }
                    IconButton {
                        icon: "chevron-down"
                        tip: "降低优先级"
                        enabled: entry.index < card.rules.length - 1
                        onClicked: Desk.moveRule(entry.modelData.id, 1)
                    }
                    IconButton {
                        icon: "pencil"
                        tip: "编辑"
                        checked: card.editing === entry.modelData.id
                        onClicked: card.editing = card.editing === entry.modelData.id ? "" : entry.modelData.id
                    }
                    IconButton {
                        visible: card.armed !== entry.modelData.id
                        icon: "trash"
                        tip: "删除"
                        danger: true
                        onClicked: { card.armed = entry.modelData.id; disarm.restart() }
                    }
                    GButton {
                        visible: card.armed === entry.modelData.id
                        text: "确认删除"
                        kind: "danger"
                        compact: true
                        onClicked: { card.armed = ""; Desk.deleteRule(entry.modelData.id) }
                    }
                }
            }
            Loader {
                width: parent.width
                active: card.editing === entry.modelData.id
                visible: active
                sourceComponent: RuleForm { host: card; rule: entry.modelData }
            }
        }
    }
}
