<!-- Purpose: Defines the realistic threat model and staged security gates for provider credentials and AI data. -->
# Security boundary — provider setup

## Threats and guarantees

| Threat | Planned/current control | Limit |
| --- | --- | --- |
| Keys accidentally committed, logged or placed in a plaintext config | Native OS credential store only; service/account namespaces; synthetic CI secrets; static UI errors; no fallback file | A user can still intentionally export a key outside the app. |
| Theft of encrypted credential files at rest | Windows Credential Manager, macOS Keychain, Linux Secret Service (must be available and unlocked) | An attacker in the user's unlocked session or with process access may read secrets. OS swap and crash dumps are outside app guarantees. |
| Long-lived plaintext key in our Rust state | Read only for an explicit operation; wrap the returned allocation in `Zeroizing<String>` and drop after use; avoid Debug/log output | OS vault, GUI, HTTP/TLS libraries can make their own copies. Rotating fragments in memory does not prevent process inspection. |
| Accidental paid test or leak to untrusted host | Future tests must require an explicit click, fixed HTTPS provider endpoints and no redirects, small indicated budget, timeouts and redacted errors | Provider token accounting can differ; a strict total token ceiling is not guaranteed without a provider-side preflight/count. No real tests have run. |
| Excessive AI tool access or unintended data egress | No model requests or tools currently wired to Agent; later use per-tool least privilege, explicit approvals and destinations | Tools/chats are deferred. Do not claim encryption of chat archives when none exist. |

The user approved the strongest *feasible* controls, not an unachievable guarantee that plaintext is never resident during HTTP authorization. Moving fragments around RAM is not an established control: the key must be reconstructable for authorized use. `src/credentials.rs` is a vault **foundation** only. Its synthetic tests cannot prove that a Windows user's Credential Manager, a macOS user's Keychain prompts, or a Linux desktop's Secret Service is present/unlocked. No live provider requests, Settings key entry/reveal or chat storage are wired yet.

## OS-specific rationale

- **Windows:** use Windows Credential Manager, not a local encrypted file with an app-embedded master key. Microsoft advises collecting passwords late, discarding early and never hardcoding/logging them: <https://learn.microsoft.com/en-us/windows/win32/secbp/handling-passwords>.
- **macOS:** use Keychain generic-password items (not a promise of Secure Enclave-backed non-exportable secrets, which cannot authenticate a remote API without releasing a bearer key): <https://developer.apple.com/documentation/security/1401659-secitemadd>.
- **Linux:** use the desktop Secret Service session and fail closed if unavailable/locked; do **not** substitute the user keyutils store or a plaintext file: <https://specifications.freedesktop.org/secret-service-spec/latest/description.html>.
- Rust `keyring` 4.2 v1's platform selection is Keychain / Windows Credential Manager / zbus Secret Service. Operations and feature choices were checked against <https://github.com/open-source-cooperative/keyring-rs/blob/main/src/v1.rs>. Generic OWASP guidance emphasizes least privilege, rotation/revocation and never logging secrets: <https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html>.

## Next implementation gates

1. Confirm OS-backed key-store availability and secure user entry/reveal behavior across all OSes. Label saved keys without displaying them; bound reveal to **no more than** 15 seconds and clear the UI state. Do not present 15 seconds as an exact cryptographic limit or guarantee removal of copies inside the renderer.
2. Implement provider-specific fixed-origin HTTPS catalog/manual IDs, then explicit stats (only where documented) and short opt-in generation tests. Never expose raw provider errors if they might echo credentials; never silently route a `:free` OpenRouter variant to a paid fallback.
3. Only after key-handling and provider tests are reviewed should the Agent composer send anything. Define chat retention/export/encryption, memory consent, tool permission and provider data-processing boundaries with the user first.
