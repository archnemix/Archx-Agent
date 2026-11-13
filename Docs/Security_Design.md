<!-- Purpose: Defines the realistic threat model and staged security gates for provider credentials and AI data. -->
# Security boundary — provider setup

## Threats and guarantees

| Threat | Planned/current control | Limit |
| --- | --- | --- |
| Keys accidentally committed, logged or placed in a plaintext config | Native OS credential store only; service/account namespaces; synthetic CI secrets; static UI errors; no fallback file | A user can still intentionally export a key outside the app. |
| Theft of encrypted credential files at rest | Windows Credential Manager, macOS Keychain, Linux Secret Service (must be available and unlocked) | An attacker in the user's unlocked session or with process access may read secrets. OS swap and crash dumps are outside app guarantees. |
| Long-lived plaintext key in our Rust state | Read only for an explicit operation; wrap the returned allocation in `Zeroizing<String>` and drop after use; avoid Debug/log output | OS vault, GUI, HTTP/TLS libraries can make their own copies. Rotating fragments in memory does not prevent process inspection. |
| Accidental paid test or leak to untrusted host | Tests require an explicit click, fixed HTTPS provider endpoints and no redirects, a 256 output-token cap, 45s timeout and redacted errors | Provider token accounting can differ; a strict total token ceiling is not guaranteed without a provider-side preflight/count. No real provider tests have run. |
| Excessive AI tool access or unintended data egress | Only explicitly submitted plain Chat can send recent session text to the selected provider; no tools, uploads or database are present | Tools/chats are deferred. Do not claim encryption of chat archives when none exist. |

The user approved the strongest *feasible* controls, not an unachievable guarantee that plaintext is never resident during HTTP authorization. Moving fragments around RAM is not an established control: the key must be reconstructable for authorized use. `src/credentials.rs` backs a user-facing Settings prototype. Synthetic tests cannot prove that a Windows user's Credential Manager, a macOS user's Keychain prompts, or a Linux desktop's Secret Service is present/unlocked. No live provider request has run in CI or this sandbox. Chat and model IDs stay in process memory only, without disk archive or database.

## OS-specific rationale

- **Windows:** use Windows Credential Manager, not a local encrypted file with an app-embedded master key. Microsoft advises collecting passwords late, discarding early and never hardcoding/logging them: <https://learn.microsoft.com/en-us/windows/win32/secbp/handling-passwords>.
- **macOS:** use Keychain generic-password items (not a promise of Secure Enclave-backed non-exportable secrets, which cannot authenticate a remote API without releasing a bearer key): <https://developer.apple.com/documentation/security/1401659-secitemadd>.
- **Linux:** use the desktop Secret Service session and fail closed if unavailable/locked; do **not** substitute the user keyutils store or a plaintext file: <https://specifications.freedesktop.org/secret-service-spec/latest/description.html>.
- Rust `keyring` 4.2 v1's platform selection is Keychain / Windows Credential Manager / zbus Secret Service. Operations and feature choices were checked against <https://github.com/open-source-cooperative/keyring-rs/blob/main/src/v1.rs>. Generic OWASP guidance emphasizes least privilege, rotation/revocation and never logging secrets: <https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html>.

## Next implementation gates

1. Validate OS-backed key-store availability and secure user entry/reveal behavior on actual Windows, macOS and Linux user sessions. Numbered key slots are normally masked; reveal starts on an explicit click, is hidden by an Instant deadline at 15 seconds and a timer drops app-owned state. Paused event loops or renderer copies prevent a cryptographic promise of exact disposal at the deadline.
2. Review the new fixed-origin API adapter and manual IDs against real provider accounts; provider catalog and stats (only where documented) remain unimplemented. A short opt-in generation test is exposed but has not been executed live. Never expose raw errors if they might echo credentials; never silently route a `:free` OpenRouter variant to a paid fallback.
3. The user reprioritized an explicit, session-only plain Chat trial. The composer can send only when the user clicks Send in Chat and has chosen a model; recent session turns are included. Define any future disk retention/export/encryption, memory consent, tool permission and provider data-processing boundaries separately before adding them.
