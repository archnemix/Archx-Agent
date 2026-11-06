# Archx Agent — test run #3

- run id: `42230781447`
- commit: `05804383b1`
- generated: 2026-11-06T14:05:58.842Z

**42/84 checks passed** — 42 failing

| suite | checks | passed | failed | duration |
| --- | ---: | ---: | ---: | ---: |
| interaction | 33 | 0 | 33 | 29s |
| visual-tour | 17 | 14 | 3 | 10s |
| visual-tour | 17 | 14 | 3 | 7s |
| visual-tour | 17 | 14 | 3 | 7s |

## Failures — interaction

- **send-flow** message round-trip through the composer
  - cannot click #input — covered by div.modal
- **empty-send** empty composer does not send
  - cannot click #btn-send — covered by div.modal
- **stop-stream** stop halts generation without losing partial text
  - cannot click #input — covered by div.modal
- **markdown** rich markdown renders as real elements
  - cannot click #input — covered by div.modal
- **code-scroll** streaming code block keeps scroll position
  - cannot click #input — covered by div.modal
- **theme-persist** theme choice persists across reload
  - cannot click [data-theme-choice="light"] — covered by div.modal
- **sidebar-switch** sidebar lists chats and switching preserves them
  - cannot click #input — covered by div.modal
- **keyboard** Enter sends; Shift+Enter keeps a newline
  - cannot click #input — covered by div.modal
- **mobile-drawer** drawer and composer work at 390 px
  - cannot click #side-toggle — covered by div.modal
- **hit-desktop-chat** hit-test chat @ desktop
  - 23 blocked control(s): [{"tag":"button","id":"","cls":"page-nav-btn active","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"}]
- **hit-desktop-studio** hit-test studio @ desktop
  - 15 blocked control(s): [{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn active","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"}]
- **hit-desktop-memory** hit-test memory @ desktop
  - 13 blocked control(s): [{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn active","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"}]
- **hit-desktop-debug** hit-test debug @ desktop
  - 28 blocked control(s): [{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn active","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"}]
- **hit-desktop-settings-general** hit-test settings:general @ desktop
  - 27 blocked control(s): [{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn active","coveredBy":"div.modal"}]
- **hit-desktop-settings-providers** hit-test settings:providers @ desktop
  - 26 blocked control(s): [{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn active","coveredBy":"div.modal"}]
- **hit-desktop-settings-models** hit-test settings:models @ desktop
  - 25 blocked control(s): [{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn active","coveredBy":"div.modal"}]
- **hit-desktop-settings-danger** hit-test settings:danger @ desktop
  - 22 blocked control(s): [{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn active","coveredBy":"div.modal"}]
- **hit-laptop-chat** hit-test chat @ laptop
  - 23 blocked control(s): [{"tag":"button","id":"","cls":"page-nav-btn active","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"}]
- **hit-laptop-studio** hit-test studio @ laptop
  - 15 blocked control(s): [{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn active","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"}]
- **hit-laptop-memory** hit-test memory @ laptop
  - 13 blocked control(s): [{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn active","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"}]
- **hit-laptop-debug** hit-test debug @ laptop
  - 27 blocked control(s): [{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn active","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"}]
- **hit-laptop-settings-general** hit-test settings:general @ laptop
  - 24 blocked control(s): [{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn active","coveredBy":"div.modal"}]
- **hit-laptop-settings-providers** hit-test settings:providers @ laptop
  - 26 blocked control(s): [{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn active","coveredBy":"div.modal"}]
- **hit-laptop-settings-models** hit-test settings:models @ laptop
  - 25 blocked control(s): [{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn active","coveredBy":"div.modal"}]
- **hit-laptop-settings-danger** hit-test settings:danger @ laptop
  - 22 blocked control(s): [{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"page-nav-btn active","coveredBy":"div.modal"}]
- **hit-mobile-chat** hit-test chat @ mobile
  - 13 blocked control(s): [{"tag":"button","id":"side-toggle","cls":"icon-btn","coveredBy":"div.modal"},{"tag":"button","id":"model-btn","cls":"model-btn","coveredBy":"div.modal"},{"tag":"button","id":"profile-btn","cls":"model-btn profile-btn","coveredBy":"div.modal"},{"tag":"button","id":"system-prompt-btn","cls":"model-btn system-prompt-btn","coveredBy":"div.modal"},{"tag":"button","id":"chat-debug-btn","cls":"btn ghost","coveredBy":"div.modal-head"}]
- **hit-mobile-studio** hit-test studio @ mobile
  - 9 blocked control(s): [{"tag":"button","id":"","cls":"icon-btn page-side-toggle","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"studio-tab active","coveredBy":"p.hint"},{"tag":"button","id":"","cls":"studio-tab","coveredBy":"p.hint"},{"tag":"button","id":"","cls":"studio-tab","coveredBy":"p.hint"},{"tag":"button","id":"","cls":"studio-tab","coveredBy":"p.hint"}]
- **hit-mobile-memory** hit-test memory @ mobile
  - 6 blocked control(s): [{"tag":"button","id":"","cls":"icon-btn page-side-toggle","coveredBy":"div.modal"},{"tag":"button","id":"mem-refresh","cls":"btn","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"btn tiny","coveredBy":"input."},{"tag":"button","id":"","cls":"btn tiny","coveredBy":"span."},{"tag":"button","id":"","cls":"btn tiny","coveredBy":"div.modal-body"}]
- **hit-mobile-debug** hit-test debug @ mobile
  - 17 blocked control(s): [{"tag":"button","id":"","cls":"icon-btn page-side-toggle","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"dbg-category active","coveredBy":"h3."},{"tag":"button","id":"","cls":"dbg-category","coveredBy":"h3."},{"tag":"button","id":"","cls":"dbg-category","coveredBy":"h3."},{"tag":"button","id":"","cls":"dbg-category","coveredBy":"p.hint"}]
- **hit-mobile-settings-general** hit-test settings:general @ mobile
  - 14 blocked control(s): [{"tag":"button","id":"","cls":"icon-btn page-side-toggle","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"set-nav-btn active","coveredBy":"p.hint"},{"tag":"button","id":"","cls":"set-nav-btn","coveredBy":"p.hint"},{"tag":"button","id":"","cls":"set-nav-btn","coveredBy":"p.hint"},{"tag":"button","id":"","cls":"set-nav-btn","coveredBy":"p.hint"}]
- **hit-mobile-settings-providers** hit-test settings:providers @ mobile
  - 13 blocked control(s): [{"tag":"button","id":"","cls":"icon-btn page-side-toggle","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"set-nav-btn","coveredBy":"p.hint"},{"tag":"button","id":"","cls":"set-nav-btn","coveredBy":"p.hint"},{"tag":"button","id":"","cls":"set-nav-btn","coveredBy":"p.hint"},{"tag":"button","id":"","cls":"set-nav-btn active","coveredBy":"p.hint"}]
- **hit-mobile-settings-models** hit-test settings:models @ mobile
  - 14 blocked control(s): [{"tag":"button","id":"","cls":"icon-btn page-side-toggle","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"set-nav-btn","coveredBy":"p.hint"},{"tag":"button","id":"","cls":"set-nav-btn","coveredBy":"p.hint"},{"tag":"button","id":"","cls":"set-nav-btn","coveredBy":"p.hint"},{"tag":"button","id":"","cls":"set-nav-btn","coveredBy":"p.hint"}]
- **hit-mobile-settings-danger** hit-test settings:danger @ mobile
  - 11 blocked control(s): [{"tag":"button","id":"","cls":"icon-btn page-side-toggle","coveredBy":"div.modal"},{"tag":"button","id":"","cls":"set-nav-btn","coveredBy":"p.hint"},{"tag":"button","id":"","cls":"set-nav-btn","coveredBy":"p.hint"},{"tag":"button","id":"","cls":"set-nav-btn","coveredBy":"p.hint"},{"tag":"button","id":"","cls":"set-nav-btn","coveredBy":"p.hint"}]

## Failures — visual-tour

- **desktop-theme-light** light theme applies at desktop
  - cannot click [data-theme-choice="light"] — covered by div.modal
- **desktop-theme-soft** soft theme applies at desktop
  - cannot click [data-theme-choice="soft"] — covered by div.modal
- **desktop-theme-dark** dark theme applies at desktop
  - cannot click [data-theme-choice="dark"] — covered by div.modal

## Failures — visual-tour

- **laptop-theme-light** light theme applies at laptop
  - cannot click [data-theme-choice="light"] — covered by div.modal
- **laptop-theme-soft** soft theme applies at laptop
  - cannot click [data-theme-choice="soft"] — covered by div.modal
- **laptop-theme-dark** dark theme applies at laptop
  - cannot click [data-theme-choice="dark"] — covered by div.modal

## Failures — visual-tour

- **mobile-theme-light** light theme applies at mobile
  - cannot click [data-theme-choice="light"] — covered by button.btn
- **mobile-theme-soft** soft theme applies at mobile
  - cannot click [data-theme-choice="soft"] — covered by div.modal
- **mobile-theme-dark** dark theme applies at mobile
  - cannot click [data-theme-choice="dark"] — covered by button.btn

_No screenshots were produced._

# Job outcomes

- **api**: failure
- **visual**: failure
- **interaction**: failure
