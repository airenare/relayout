import QtQuick
import QtQuick.Controls as QQC
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// Relayout bar widget. All state lives in the relayout daemon; this widget
// only talks to it through the installed `relayout` CLI (`subscribe` for live state,
// other subcommands for edits). Arguments are always passed as arrays, never
// through a shell.
Panel {
  id: root
  moduleName: "air.relayout"
  ipcTarget: "air.relayout"

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  // From the daemon. daemonUp is false while `relayout subscribe` is not
  // connected (daemon stopped or restarting).
  property bool daemonUp: false
  property bool autoOn: false
  property string suppressed: ""
  property string app: ""
  property string active: ""
  property var layouts: []
  property var excluded: []
  // [{word, layout}] sorted by word.
  property var rules: []

  readonly property bool appExcluded: app !== "" && excluded.indexOf(app) !== -1
  readonly property bool working: daemonUp && autoOn && suppressed === ""

  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property color dim: Qt.darker(foreground, 1.55)

  property int cursorIndex: -1

  // "Add a word" form state.
  property string addLayout: ""
  property string addError: ""
  readonly property string effectiveAddLayout:
    layouts.indexOf(addLayout) !== -1 ? addLayout : (layouts.length > 0 ? String(layouts[0]) : "")

  function otherLayout(l) {
    if (layouts.length !== 2) return ""
    return String(layouts[0]) === l ? String(layouts[1]) : String(layouts[0])
  }

  // Returns an error string, or "" when the word is acceptable.
  function validateWord(w) {
    if (w === "") return "Enter a word"
    if (/\s/.test(w)) return "No spaces allowed"
    return ""
  }

  function addWord(raw) {
    var w = String(raw).trim()
    var err = root.validateWord(w)
    if (err === "" && root.effectiveAddLayout === "") err = "No layout available"
    root.addError = err
    if (err !== "") return false
    root.runPrivate("rules add " + w + " " + root.effectiveAddLayout)
    return true
  }

  function suppressedText() {
    if (suppressed === "app") return "paused: disabled for this app"
    if (suppressed === "layer") return "paused: layer-shell surface focused"
    if (suppressed === "lock") return "paused: screen locked"
    return ""
  }

  function applyState(ev) {
    root.autoOn = ev.auto === true
    root.suppressed = ev.suppressed ? String(ev.suppressed) : ""
    root.app = ev.app ? String(ev.app) : ""
    root.active = ev.active ? String(ev.active) : ""
    root.layouts = Array.isArray(ev.layouts) ? ev.layouts : []
    root.excluded = Array.isArray(ev.excluded) ? ev.excluded : []
    var list = []
    var r = ev.rules || {}
    for (var w in r) list.push({ word: w, layout: String(r[w]) })
    list.sort(function(a, b) { return a.word.localeCompare(b.word) })
    root.rules = list
  }

  // The installed CLI, by absolute path: never whatever `relayout` happens to
  // be first on PATH (the installer refuses to replace a command it did not
  // create, and this widget must not run that one).
  readonly property string cli: Quickshell.env("HOME") + "/.local/share/relayout/.venv/bin/relayout"

  // Run a relayout subcommand; calls made while one is in flight are queued.
  property var queue: []
  function run(args) {
    root.queue = root.queue.concat([{ args: args, line: "" }])
    root.pump()
  }
  // Learned words can be private: send the command on the CLI's stdin, never
  // as process arguments (visible to other local users via ps and /proc).
  function runPrivate(line) {
    root.queue = root.queue.concat([{ args: ["--stdin"], line: line }])
    root.pump()
  }
  function pump() {
    if (actionProc.running || root.queue.length === 0) return
    var next = root.queue[0]
    root.queue = root.queue.slice(1)
    actionProc.pendingLine = next.line
    actionProc.command = [root.cli].concat(next.args)
    actionProc.running = true
  }

  onOpenedChanged: {
    if (opened) Qt.callLater(function() { keyCatcher.forceActiveFocus() })
  }

  Process {
    id: watchProc
    // pdeathsig: don't leave an orphaned subscriber if the shell dies.
    command: ["setpriv", "--pdeathsig", "TERM", root.cli, "subscribe"]
    onRunningChanged: if (!running) root.daemonUp = false
    onExited: watchRestart.restart()
    stdout: SplitParser {
      onRead: function(line) {
        var ev
        try { ev = JSON.parse(line) } catch (e) { return }
        if (!ev || typeof ev !== "object") return
        root.daemonUp = true
        root.applyState(ev)
      }
    }
  }

  // The daemon may be down or restarting: quietly try again.
  Timer {
    id: watchRestart
    interval: 3000
    onTriggered: if (!watchProc.running) watchProc.running = true
  }

  Component.onCompleted: watchProc.running = true

  Process {
    id: actionProc
    property string pendingLine: ""
    stdinEnabled: true
    onStarted: if (pendingLine !== "") write(pendingLine + "\n")
    onExited: root.pump()
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "󰌌"
    dimmed: !root.working
    tooltipText: !root.daemonUp
      ? "Relayout: daemon not running"
      : "Relayout: auto-correct " + (root.autoOn ? "on" : "off")
        + (root.suppressed !== "" ? "\n" + root.suppressedText() : "")
        + "\nRight click to turn " + (root.autoOn ? "off" : "on")
    onPressed: function(b) {
      if (b === Qt.RightButton) root.run(["auto", "toggle"])
      else root.toggle()
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(320))
    contentHeight: panel.fittedContentHeight(column.implicitHeight, Style.space(700))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      blocked: wordField.activeFocus
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }

      Column {
        id: column
        width: parent.width
        spacing: Style.space(10)

        Text {
          visible: !root.daemonUp
          width: parent.width
          wrapMode: Text.Wrap
          textFormat: Text.PlainText
          text: "relayout daemon not running"
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
        }

        Toggle {
          visible: root.daemonUp
          width: parent.width
          label: "Auto-correct"
          description: root.suppressed !== "" ? root.suppressedText() : "Fix text typed in the wrong layout"
          checked: root.autoOn
          foreground: root.foreground
          fontFamily: root.fontFamily
          onClicked: root.run(["auto", root.autoOn ? "off" : "on"])
        }

        Text {
          visible: root.daemonUp
          width: parent.width
          wrapMode: Text.Wrap
          textFormat: Text.PlainText
          text: "Layout: " + (root.active !== "" ? root.active : "?")
            + (root.layouts.length > 0 ? "  (" + root.layouts.join(", ") + ")" : "")
            + "\nApp: " + (root.app !== "" ? root.app : "none")
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.bodySmall
        }

        Toggle {
          visible: root.daemonUp && root.app !== ""
          width: parent.width
          label: root.appExcluded ? "Turn on for " + root.app : "Turn off for " + root.app
          checked: !root.appExcluded
          foreground: root.foreground
          fontFamily: root.fontFamily
          onClicked: root.run(["exclude", root.appExcluded ? "rm" : "add", root.app])
        }

        PanelSeparator { visible: root.daemonUp; foreground: root.foreground }

        PanelSectionHeader {
          visible: root.daemonUp
          text: "LEARNED WORDS (" + root.rules.length + ")"
          foreground: root.foreground
          fontFamily: root.fontFamily
        }

        Item {
          visible: root.daemonUp
          width: parent.width
          height: wordField.implicitHeight

          TextField {
            id: wordField
            anchors.left: parent.left
            anchors.right: layoutChoice.left
            anchors.rightMargin: Style.space(6)
            anchors.verticalCenter: parent.verticalCenter
            placeholderText: "Add a word"
            foreground: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            onTextChanged: root.addError = ""
            onAccepted: if (root.addWord(text)) text = ""
            Keys.onEscapePressed: root.close()
          }

          Row {
            id: layoutChoice
            anchors.right: addButton.left
            anchors.rightMargin: Style.space(6)
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.space(2)

            Repeater {
              model: root.layouts
              delegate: Button {
                required property var modelData
                text: String(modelData)
                foreground: root.foreground
                fontFamily: root.fontFamily
                fontSize: Style.font.bodySmall
                horizontalPadding: Style.space(6)
                selected: root.effectiveAddLayout === String(modelData)
                onClicked: root.addLayout = String(modelData)
              }
            }
          }

          PanelActionButton {
            id: addButton
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            iconText: "󰐕"
            tooltipText: "Add word"
            foreground: root.foreground
            fontFamily: root.fontFamily
            onClicked: if (root.addWord(wordField.text)) wordField.text = ""
          }
        }

        Text {
          visible: root.daemonUp && root.addError !== ""
          width: parent.width
          wrapMode: Text.Wrap
          textFormat: Text.PlainText
          text: root.addError
          color: root.bar ? root.bar.urgent : Color.urgent
          font.family: root.fontFamily
          font.pixelSize: Style.font.bodySmall
        }

        Text {
          visible: root.daemonUp && root.addError === ""
          width: parent.width
          wrapMode: Text.Wrap
          textFormat: Text.PlainText
          text: "Word comes out in the chosen layout."
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
        }

        Text {
          visible: root.daemonUp && root.rules.length === 0
          width: parent.width
          wrapMode: Text.Wrap
          textFormat: Text.PlainText
          text: "No learned words yet."
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.bodySmall
        }

        ListView {
          id: rulesView
          visible: root.daemonUp && root.rules.length > 0
          width: parent.width
          height: Math.min(contentHeight, Style.space(280))
          clip: true
          boundsBehavior: Flickable.StopAtBounds
          interactive: contentHeight > height
          model: root.rules

          QQC.ScrollBar.vertical: QQC.ScrollBar {
            policy: rulesView.interactive ? QQC.ScrollBar.AlwaysOn : QQC.ScrollBar.AlwaysOff
          }

          delegate: CursorSurface {
            id: row
            required property int index
            required property var modelData
            width: ListView.view.width - (rulesView.interactive ? Style.space(10) : 0)
            height: Style.space(32)
            foreground: root.foreground
            hasCursor: root.cursorIndex === row.index

            property int hotButtons: 0
            readonly property bool hot: rowMouse.containsMouse || hotButtons > 0
            onHotChanged: {
              if (hot) root.cursorIndex = row.index
              else if (root.cursorIndex === row.index) root.cursorIndex = -1
            }

            MouseArea {
              id: rowMouse
              anchors.fill: parent
              hoverEnabled: true
            }

            Text {
              anchors.left: parent.left
              anchors.leftMargin: Style.space(8)
              anchors.right: tag.left
              anchors.rightMargin: Style.space(8)
              anchors.verticalCenter: parent.verticalCenter
              elide: Text.ElideRight
              textFormat: Text.PlainText
              text: row.modelData.word
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.body
            }

            Text {
              id: tag
              anchors.right: moveWord.visible ? moveWord.left : removeWord.left
              anchors.rightMargin: Style.space(6)
              anchors.verticalCenter: parent.verticalCenter
              textFormat: Text.PlainText
              text: row.modelData.layout
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.bodySmall
            }

            PanelActionButton {
              id: moveWord
              visible: root.otherLayout(row.modelData.layout) !== ""
              anchors.right: removeWord.left
              anchors.rightMargin: Style.space(2)
              anchors.verticalCenter: parent.verticalCenter
              iconText: "󰓡"
              tooltipText: "Move to " + root.otherLayout(row.modelData.layout)
              foreground: root.dim
              fontFamily: root.fontFamily
              opacity: row.hasCursor ? 1 : 0.5
              onHovered: function(on) { row.hotButtons += on ? 1 : -1 }
              onClicked: root.runPrivate("rules add " + row.modelData.word + " " + root.otherLayout(row.modelData.layout))
            }

            PanelActionButton {
              id: removeWord
              anchors.right: parent.right
              anchors.rightMargin: Style.space(6)
              anchors.verticalCenter: parent.verticalCenter
              iconText: "󰆴"
              foreground: root.dim
              hoverColor: root.bar ? root.bar.urgent : Color.urgent
              fontFamily: root.fontFamily
              opacity: row.hasCursor ? 1 : 0.5
              onHovered: function(on) { row.hotButtons += on ? 1 : -1 }
              onClicked: root.runPrivate("rules rm " + row.modelData.word)
            }
          }
        }
      }
    }
  }
}
