// Body of a file island: the active tab's icons.  Folder ("portal") tabs show
// a path bar with up / home / breadcrumbs / open in Explorer, and drops move
// real files into the folder; reference tabs only keep links.
import QtQuick

Item {
    id: body
    property var island: null
    readonly property var proxy: island ? island.proxy : null
    readonly property string uid: island ? island.uid : ""
    readonly property var activeTab: {
        var list = proxy ? proxy.tabs : []
        for (var i = 0; i < list.length; i++) {
            if (list[i].id === proxy.activeTab) {
                return list[i]
            }
        }
        return list.length ? list[0] : null
    }
    readonly property bool portalTab: !!activeTab && !!activeTab.portal
    readonly property string container: "island:" + uid + ":" + (activeTab ? activeTab.id : "")
    readonly property var crumbs: {
        if (!proxy || !portalTab) {
            return []
        }
        var root = proxy.portalRoot.replace(/[\\\/]+$/, "")
        var path = proxy.portalPath.replace(/[\\\/]+$/, "")
        var sep = root.indexOf("\\") >= 0 ? "\\" : "/"
        var rootName = root.split(/[\\\/]/).pop() || root
        var out = [{ label: rootName, path: "" }]
        if (path.length > root.length && path.toLowerCase().indexOf(root.toLowerCase()) === 0) {
            var rest = path.substring(root.length).replace(/^[\\\/]+/, "").split(/[\\\/]/)
            var acc = root
            for (var i = 0; i < rest.length; i++) {
                if (rest[i] === "") {
                    continue
                }
                acc = acc + sep + rest[i]
                out.push({ label: rest[i], path: acc })
            }
        }
        if (out.length > 4) {
            out = [out[0], { label: "…", path: out[out.length - 3].path }].concat(out.slice(out.length - 2))
        }
        return out
    }

    function reveal(path) {
        grid.reveal(path)
    }
    function reload() {
        Desk.action("scan", {})
    }

    // Path bar (folder tabs) ---------------------------------------------------------------------------
    Item {
        id: pathBar
        visible: body.portalTab
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.leftMargin: 8
        anchors.rightMargin: 8
        height: visible ? 30 : 0
        Row {
            id: navRow
            anchors.verticalCenter: parent.verticalCenter
            spacing: 0
            IconButton {
                icon: "arrow-up"
                tip: "上一级"
                size: 26
                iconSize: 15
                enabled: !!body.proxy && body.proxy.portalCanUp
                opacity: enabled ? 1 : 0.35
                onClicked: Desk.act(body.uid, "portalUp", {})
            }
        }
        Row {
            anchors.left: navRow.right
            anchors.leftMargin: 4
            anchors.right: openBtn.left
            anchors.rightMargin: 4
            anchors.verticalCenter: parent.verticalCenter
            spacing: 2
            clip: true
            Repeater {
                model: body.crumbs
                delegate: Row {
                    id: crumb
                    required property var modelData
                    required property int index
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 2
                    Glyph {
                        visible: crumb.index > 0
                        anchors.verticalCenter: parent.verticalCenter
                        name: "chevron-right"
                        size: 12
                        color: Theme.textFaint
                    }
                    Rectangle {
                        anchors.verticalCenter: parent.verticalCenter
                        width: crumbText.implicitWidth + 12
                        height: 22
                        radius: 6
                        color: crumbMouse.containsMouse ? Theme.hover : "transparent"
                        Text {
                            id: crumbText
                            anchors.centerIn: parent
                            text: crumb.modelData.label
                            color: crumb.index === body.crumbs.length - 1 ? Theme.text : Theme.textDim
                            font.family: Theme.fontFamily
                            font.pixelSize: 12
                            font.weight: crumb.index === body.crumbs.length - 1 ? Font.DemiBold : Font.Normal
                        }
                        MouseArea {
                            id: crumbMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                if (crumb.modelData.path === "") {
                                    Desk.act(body.uid, "portalHome", {})
                                } else {
                                    Desk.act(body.uid, "portalOpen", { path: crumb.modelData.path })
                                }
                            }
                        }
                    }
                }
            }
        }
        IconButton {
            id: openBtn
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            icon: "external-link"
            tip: "在资源管理器中打开"
            size: 26
            iconSize: 15
            onClicked: Desk.openItem(body.proxy.portalPath)
        }
        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 1
            color: Theme.hairline
        }
    }

    // Icons ------------------------------------------------------------------------------------------
    IconGrid {
        id: grid
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: pathBar.bottom
        anchors.bottom: parent.bottom
        anchors.leftMargin: 4
        anchors.rightMargin: 4
        anchors.bottomMargin: 6
        island: body.island
        model: body.proxy ? body.proxy.itemsModel : null
        container: body.container
        portal: body.portalTab
        emptyText: body.portalTab && body.proxy && body.proxy.portalMissing
                   ? "找不到这个文件夹\n它可能被移动或删除了，或者所在的磁盘没有连接"
                   : body.portalTab ? "这个文件夹是空的\n可以把文件拖进来（会真正移动文件）"
                                    : "把桌面上的文件拖到这里\n只保存引用，原文件不会被移动"
        emptyIcon: body.portalTab && body.proxy && body.proxy.portalMissing ? "alert-triangle"
                   : body.portalTab ? "folder-open" : "download"
        onActivated: (path) => Desk.openInIsland(body.container, path)
        onBlankMenu: (gx, gy) => App.popupMenuAt("island", body.uid, {}, gx, gy)
    }
}
