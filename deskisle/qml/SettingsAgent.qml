// Settings · AI 与扩展: the local agent interface (named pipe), MCP client
// configuration, CLI examples and the safety model.
import QtQuick

Column {
    id: page
    property var win: null
    property int tick: 0
    readonly property var info: (tick, App.agentInfo())
    readonly property string mcpJson: {
        var cfg = { mcpServers: { deskisle: { command: info.mcpCommand || "", args: info.mcpArgs || [] } } }
        return JSON.stringify(cfg, null, 2)
    }
    readonly property string cli: info.cli || "deskisle-cli"
    width: parent ? parent.width : 640
    spacing: 22

    Connections {
        target: App
        function onInfoChanged() { page.tick++ }
    }
    Connections {
        target: Desk
        function onPrefsChanged() { statusDelay.restart() }
    }
    Timer {
        // the pipe starts / stops a moment after the switch flips
        id: statusDelay
        interval: 600
        onTriggered: page.tick++
    }

    SettingsCard {
        title: "AI 助手"
        note: "AI 助手可以查看桌面布局、新建与整理收纳岛、搜索文件、读写自定义小组件等。所有通信都在本机进行，不开放任何网络端口。"
        SettingRow {
            title: "允许 AI 助手控制桌屿"
            description: "通过本机命名管道接收 MCP 服务器与命令行的请求。"
            pref: "agent_enabled"
            kind: "switch"
        }
        SettingRow {
            title: "连接状态"
            description: page.info.listening ? "正在监听：" + page.info.pipe
                       : page.info.enabled ? "接口未能启动，请查看运行日志。" : "已关闭，AI 助手无法连接。"
            Rectangle {
                width: statusText.implicitWidth + 30
                height: 26
                radius: 13
                color: page.info.listening ? Qt.rgba(0.20, 0.78, 0.48, 0.16)
                     : page.info.enabled ? Qt.rgba(0.96, 0.65, 0.14, 0.16) : Theme.hover
                Rectangle {
                    x: 11
                    anchors.verticalCenter: parent.verticalCenter
                    width: 7
                    height: 7
                    radius: 3.5
                    color: page.info.listening ? "#34C77B" : page.info.enabled ? "#F5A524" : Theme.textFaint
                }
                Text {
                    id: statusText
                    x: 23
                    anchors.verticalCenter: parent.verticalCenter
                    text: page.info.listening ? "已就绪" : page.info.enabled ? "未启动" : "已关闭"
                    color: Theme.text
                    font.family: Theme.fontFamily
                    font.pixelSize: 12
                }
            }
        }
    }

    SettingsCard {
        title: "MCP 配置"
        note: "把这段配置加入 Claude Desktop、Cursor、VS Code、Cherry Studio 等支持 MCP（Model Context Protocol）的客户端，重启客户端后即可使用。"
        Item {
            width: parent.width
            height: mcpBlock.height + 28
            CodeBlock {
                id: mcpBlock
                x: 16
                y: 14
                width: parent.width - 32
                code: page.mcpJson
                copyNote: "已复制 MCP 配置"
            }
        }
    }

    SettingsCard {
        title: "命令行"
        note: "脚本与不支持 MCP 的 AI 工具可以直接调用命令行，输出均为 JSON。退出码：0 成功，1 命令出错，2 用法错误，3 桌屿未运行。"
              + (!page.info.packaged ? ""
                 : page.info.cliOnPath ? "安装目录已在 PATH 中，新打开的终端里可以直接输入 deskisle-cli。"
                 : "重新运行安装程序并勾选“把命令行工具加入 PATH”，之后在新终端里就能直接输入 deskisle-cli。")
        Item {
            width: parent.width
            height: cliBlock.height + 28
            CodeBlock {
                id: cliBlock
                x: 16
                y: 14
                width: parent.width - 32
                code: page.cli + " list                       # 全部命令\n"
                      + page.cli + " help island.create         # 某个命令的参数\n"
                      + page.cli + " desk.state                 # 当前桌面布局\n"
                      + page.cli + " island.create --kind widget --widget clock\n"
                      + page.cli + " search.query --text 报告"
                copyNote: "已复制命令示例"
            }
        }
    }

    SettingsCard {
        title: "安全与说明"
        SettingRow {
            title: "破坏性操作需要你确认"
            description: "删除收纳岛、标签或预设，删除待办或小组件，恢复快照、导入布局以及退出桌屿，都会先在桌面上弹出“来自 AI 助手”的确认卡片，你点“允许”后才会执行。"
            Glyph {
                name: "lock"
                size: 20
                color: Theme.accent
            }
        }
        SettingRow {
            title: "说明文档"
            description: "GUIDE.md 介绍全部命令、参数、小组件 SDK 与示例，也适合直接交给 AI 助手阅读。"
            GButton {
                text: "打开"
                icon: "external-link"
                compact: true
                enabled: page.info.guide !== ""
                onClicked: Desk.openItem(page.info.guide)
            }
            GButton {
                text: "复制路径"
                icon: "copy"
                compact: true
                kind: "ghost"
                onClicked: Desk.copyText(page.info.guide, "已复制文档路径")
            }
        }
        SettingRow {
            title: "自定义文件夹"
            description: page.info.custom || Custom.folderPath
            GButton {
                text: "打开"
                icon: "folder-open"
                compact: true
                onClicked: Custom.openFolder()
            }
        }
    }
}
