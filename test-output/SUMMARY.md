# Archx Agent — test run #5

- run id: `42233781764`
- commit: `9be02bf8a4`
- generated: 2026-11-06T14:26:22.029Z

**65/84 checks passed** — 19 failing

| suite | checks | passed | failed | duration |
| --- | ---: | ---: | ---: | ---: |
| interaction | 33 | 23 | 10 | 31s |
| visual-tour | 17 | 14 | 3 | 8s |
| visual-tour | 17 | 14 | 3 | 8s |
| visual-tour | 17 | 14 | 3 | 7s |

## Failures — interaction

- **send-flow** message round-trip through the composer
  - Protocol error (Input.dispatchMouseEvent): Invalid parameters Failed to deserialize params.x - BINDINGS: double value expected at position 58
- **empty-send** empty composer does not send
  - Protocol error (Input.dispatchMouseEvent): Invalid parameters Failed to deserialize params.x - BINDINGS: double value expected at position 58
- **stop-stream** stop halts generation without losing partial text
  - Protocol error (Input.dispatchMouseEvent): Invalid parameters Failed to deserialize params.x - BINDINGS: double value expected at position 58
- **markdown** rich markdown renders as real elements
  - Protocol error (Input.dispatchMouseEvent): Invalid parameters Failed to deserialize params.x - BINDINGS: double value expected at position 58
- **code-scroll** streaming code block keeps scroll position
  - Protocol error (Input.dispatchMouseEvent): Invalid parameters Failed to deserialize params.x - BINDINGS: double value expected at position 58
- **theme-persist** theme choice persists across reload
  - Protocol error (Input.dispatchMouseEvent): Invalid parameters Failed to deserialize params.x - BINDINGS: double value expected at position 58
- **sidebar-switch** sidebar lists chats and switching preserves them
  - Protocol error (Input.dispatchMouseEvent): Invalid parameters Failed to deserialize params.x - BINDINGS: double value expected at position 58
- **keyboard** Enter sends; Shift+Enter keeps a newline
  - Protocol error (Input.dispatchMouseEvent): Invalid parameters Failed to deserialize params.x - BINDINGS: double value expected at position 58
- **mobile-drawer** drawer and composer work at 390 px
  - Protocol error (Input.dispatchMouseEvent): Invalid parameters Failed to deserialize params.x - BINDINGS: double value expected at position 58
- **hit-mobile-chat** hit-test chat @ mobile
  - 1 blocked control(s): [{"tag":"button","id":"","cls":"chip","coveredBy":"footer.composer-wrap"}]

## Failures — visual-tour

- **desktop-theme-light** light theme applies at desktop
  - Protocol error (Input.dispatchMouseEvent): Invalid parameters Failed to deserialize params.x - BINDINGS: double value expected at position 58
- **desktop-theme-soft** soft theme applies at desktop
  - Protocol error (Input.dispatchMouseEvent): Invalid parameters Failed to deserialize params.x - BINDINGS: double value expected at position 58
- **desktop-theme-dark** dark theme applies at desktop
  - Protocol error (Input.dispatchMouseEvent): Invalid parameters Failed to deserialize params.x - BINDINGS: double value expected at position 58

## Failures — visual-tour

- **laptop-theme-light** light theme applies at laptop
  - Protocol error (Input.dispatchMouseEvent): Invalid parameters Failed to deserialize params.x - BINDINGS: double value expected at position 58
- **laptop-theme-soft** soft theme applies at laptop
  - Protocol error (Input.dispatchMouseEvent): Invalid parameters Failed to deserialize params.x - BINDINGS: double value expected at position 58
- **laptop-theme-dark** dark theme applies at laptop
  - Protocol error (Input.dispatchMouseEvent): Invalid parameters Failed to deserialize params.x - BINDINGS: double value expected at position 58

## Failures — visual-tour

- **mobile-theme-light** light theme applies at mobile
  - Protocol error (Input.dispatchMouseEvent): Invalid parameters Failed to deserialize params.x - BINDINGS: double value expected at position 58
- **mobile-theme-soft** soft theme applies at mobile
  - Protocol error (Input.dispatchMouseEvent): Invalid parameters Failed to deserialize params.x - BINDINGS: double value expected at position 58
- **mobile-theme-dark** dark theme applies at mobile
  - Protocol error (Input.dispatchMouseEvent): Invalid parameters Failed to deserialize params.x - BINDINGS: double value expected at position 58

_No screenshots were produced._

# Job outcomes

- **api**: success
- **visual**: failure
- **interaction**: failure
