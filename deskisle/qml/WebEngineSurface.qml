// QtWebEngine backend for development on Linux / macOS (WebView2 is used on
// Windows).  Loaded only when DESKISLE_WEBENGINE_READY is set, so a missing
// QtWebEngine never breaks the UI.
import QtQuick
import QtWebEngine

WebEngineView {
    id: web
    property var view: null
    property var island: null
    property bool started: false

    backgroundColor: view && view.transparent ? "transparent" : "white"
    settings.showScrollBars: true
    settings.localContentCanAccessFileUrls: true
    settings.localContentCanAccessRemoteUrls: true

    function report(extra) {
        if (!view) {
            return
        }
        var m = { title: web.title, url: web.url.toString(), loading: web.loading,
                  canBack: web.canGoBack, canForward: web.canGoForward, zoom: web.zoomFactor }
        if (extra) {
            for (var k in extra) {
                m[k] = extra[k]
            }
        }
        view.report(m)
    }
    function start() {
        if (!started && view && view.source !== "") {
            started = true
            web.url = view.source
        }
    }
    onViewChanged: start()
    Component.onCompleted: start()

    Connections {
        target: web.view
        function onCommand(name, value) {
            if (name === "navigate") {
                web.url = value
            } else if (name === "reload") {
                web.reload()
            } else if (name === "back") {
                web.goBack()
            } else if (name === "forward") {
                web.goForward()
            } else if (name === "stop") {
                web.stop()
            } else if (name === "zoom") {
                web.zoomFactor = Number(value) || 1
            }
        }
        function onChanged() { web.start() }
    }
    onTitleChanged: report()
    onUrlChanged: report()
    onCanGoBackChanged: report()
    onCanGoForwardChanged: report()
    onLoadingChanged: (info) => {
        if (info.status === WebEngineLoadingInfo.LoadStartedStatus) {
            report({ loading: true, status: "" })
        } else if (info.status === WebEngineLoadingInfo.LoadSucceededStatus) {
            report({ loading: false, status: "", loaded: true })
        } else if (info.status === WebEngineLoadingInfo.LoadFailedStatus) {
            report({ loading: false, status: "页面加载失败（" + info.errorCode + "）" })
        } else {
            report({ loading: false })
        }
    }
    onNewWindowRequested: (request) => Qt.openUrlExternally(request.requestedUrl)
}
