// Now playing panel opened from the bar's mini player.  Tall enough for the
// audio line and two short lyric lines under the transport controls.
import QtQuick

Item {
    id: panel
    property var host: null
    implicitWidth: 440
    implicitHeight: 246

    MediaWidget {
        anchors.fill: parent
        anchors.margins: 6
    }
}
