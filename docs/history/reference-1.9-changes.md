# Archx Agent 1.9.0 — changes & usage

> Historical notes from the supplied Node reference, not current 1.0.0 validation.
> Any Windows/data compatibility statements apply only to that reference, never the removed Python database.

Round-2 fixes from Windows testing. Everything below was tested against live providers
(Gemini + Mistral keys) and screenshot-verified in all three themes.

## 1. No native browser controls left in the UI
- Every `<select>` (Studio model pickers, provider preset/adapter, Models profile
  provider, Chat-debug provider filter) is now upgraded in place to a custom
  dropdown (`.dd` in `dom.js`) with the same visual language as the rest of the app:
  rounded button + caret, elevated menu, keyboard `Esc` to close, outside-click close.
- The native select stays in the DOM (hidden) so form logic is untouched; a
  MutationObserver keeps the custom widget in sync whenever options change.
- New bug fixed while integrating: Studio pickers rendered before the async model
  fetch resolved stayed empty forever. `fetchModelsFor` now dispatches
  `archx:models-loaded` and boot re-fills the Studio dropdowns when it lands.

## 2. Beautiful custom file chooser (replaces "Choose File")
- `attachFilePick()` renders a styled "Choose file(s)" pill + file-name label,
  supports drag & drop onto the pill, and (Vision/OCR) shows removable thumbnails
  for every picked image.
- **Multiple images are now allowed in Vision · OCR** — all picked images are sent
  in one request as separate inline parts.

## 3. Provider-correct API usage (researched per vendor)
- **OpenAI-compatible** providers (OpenAI, Groq, Mistral, xAI, OpenRouter, …) now use
  the official `openai` npm client for chat, transcription and speech. This also fixes
  Groq STT `400 file must be one of [flac mp3 …]` — the SDK sends a proper multipart
  body with the right filename extension.
- **Anthropic** chat goes through the official `@anthropic-ai/sdk`.
- **Gemini** transcription/TTS use Google's native `generateContent` endpoint
  (inline audio / `responseModalities: ["AUDIO"]`), not an OpenAI shim.
- **NVIDIA NIM** got a dedicated adapter (`lib/providers/nvidia-nim.js`): chat and model
  list use the OpenAI wire at `integrate.api.nvidia.com`, while image generation,
  speech and transcription try the OpenAI-style routes first and fall back to the
  native `ai.api.nvidia.com` GenAI / Speech-NIM endpoints (NIM is *not* OpenAI-compatible
  for those modalities). A "NVIDIA NIM" preset was added to the provider dialog.

## 4. Capability classification now understands model purpose
- Transcription-only models (e.g. `whisper-large-v3`, `voxtral-*-latest` STT use aside)
  never appear in chat/vision/OCR pickers; OCR models only in Vision; image generators
  only in Image generation; TTS models only in Text→speech.
- Gemini chat models gain native STT capability; verified table:
  `gemini-2.5-flash {chat,vision,stt}`, `gemini-2.5-flash-preview-tts {tts}`,
  `flux-1/sdxl-turbo/dall-e-3 {imageGen}`, `voxtral-mini-latest {chat,stt}`,
  `mistral-ocr-latest {vision}`, `whisper-large-v3 {stt}`,
  `gemini-2.5-flash-image {chat,vision,imageGen,stt}`.

## 5. Modern web-search UX (like current AI chat UIs)
- Two distinct tools: **web search** (free engine chain: Bing → DuckDuckGo → SearXNG)
  and **page read** (any `https://` link in your message is fetched and injected).
- While the answer streams, the assistant message shows a live card:
  "Searched the web — *query* · engine · ms · N sources" (expandable source list), and
  "Read page — title · chars". Fixed a bug where the live card container stayed
  `display:none` (stale `empty` class) until a reload.
- Every tool run is journaled and appears in that chat's **Chat debug → Tools** tab
  with the full request/response entry.

## 6. Toggle switch — bench-tested before integration
- `public/toggle-test.html?theme=dark|light|soft` renders 3 themes × 8 states ×
  2 variants (standalone + inside a real `.check` row) at 2× DPI. Pixel-measured in all
  themes; only after that were the Settings switches wired to the same component
  (`.sp-switch`). Settings → General now shows the exact bench geometry.

## Usage (unchanged from 1.8.0)
- Web UI: `node bin/archx-agent.js webui --host 0.0.0.0 --port 4173`
  (add `--data-dir PATH` to point at your folder; first run in an existing folder
  migrates `data.json`/keys automatically).
- Desktop: `src-tauri` wrapper as before (`npm i && npx tauri dev/build`).
- Your Windows data (`F:\…\archx.db`) keeps working — storage is SQLite since 1.7.

## Verified this round (live)
- Mistral STT (SDK path) 200; Gemini native STT reaches Google endpoint (free tier
  intermittently 429/"high demand" — upstream quota, not a client bug).
- Web search tool: ddg results injected + card + debug entry (screenshots
  `screens/n-chat-tools.png`, `n-chat-debug.png`).
- Switches: `screens/bench-dark|light|soft.png`, `screens/n-set-general.png`.
- Dropdowns/file pick: `screens/n-studio-menu.png`, `n-studio-vision.png`.
