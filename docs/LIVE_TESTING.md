# Testing the live application

## Normal preview

The Arena preview uses port **4173** and the existing separate Node data folder.
Enter provider keys only in Settings → Providers. This sandbox cannot generally
reach external model services, so it cannot proxy a Cloudflare model URL merely
because that URL was created by GitHub Actions.

## Current session

The verified 4-bit session is running in
[GitHub run 41207241054](https://github.com/archnemix/Archx-Agent/actions/runs/41207241054).
[Download the current preview link](https://github.com/archnemix/Archx-Agent/actions/runs/41207241054/artifacts/13045360924),
open `preview-link.txt` in the ZIP, then open its authenticated Cloudflare link.
The small model is preselected; no API key is needed. Use this runner-hosted app,
not the normal sandbox preview, for real inference.

The session started around 13:51 UTC on 31 October 2026 and stays up for 90 minutes
unless cancelled. It is disposable shared test hosting, not a permanent endpoint.
[Real-model evidence](https://github.com/archnemix/Archx-Agent/actions/runs/41207241054/artifacts/13044539980)
contains loaded quantization metadata, the actual two-turn conversation and a browser
screenshot. Real inference, streamed browser replies, final-save acknowledgement,
persisted reload and test-chat cleanup passed before publishing the link. The
transcript is evidence of returned answers, not a claim that the tiny model's
reasoning or recall is high-quality. Prior session links are superseded.

## Temporary real-model session

The requested GitHub Actions job runs the **whole application** with models on a
fresh runner and tunnels the application through Cloudflare. Your browser connects
to that app directly, avoiding the sandbox as a model proxy.

Open the run's **preview-link** artifact and its `preview-link.txt`. Open the
`https://….trycloudflare.com/unlock?token=…` link in that file. It sets an HttpOnly
session cookie and redirects to the app. Services run on loopback; only the guarded
app is tunnelled. The session shuts down after the selected duration (maximum 90
minutes), and runner data is disposable. Export anything you need before it expires.

**This repository is public. Treat the artifact/link as a shared test-session link,
not private hosting. Do not enter valuable keys, private documents or personal data.**
The token guards casual unauthenticated access, not everyone who can read artifacts.
The runner disables changing storage locations and standalone web-tool routes;
this does not constitute a production security certification.

### What you can actually test

| Model/engine | Type | How to test |
|---|---|---|
| `smollm2-135m-q4` | Real SmolLM2 **135M**, Q4_K_M GGUF loaded through Ollama | Select it in Chat and ask a short question. It is intentionally tiny and limited, not a high-quality assistant. |
| `qwen3:0.6b` | Real reasoning model through Ollama | Select it in Chat, enable showing thinking, and ask a short reasoning question. Thinking comes from the model's native `thinking` field. |
| `tts-espeak` | Real eSpeak synthesis, not a neural TTS model | Studio → Speech. Enter text and play/download the WAV. |
| `whisper-tiny` | Real Whisper tiny, CPU/int8 | Studio → Transcription. Upload speech audio and compare the transcript. |
| `ocr-tesseract` | Real Tesseract OCR, not general image understanding | Studio → Vision/OCR. Upload an image with legible text. Blank images can return no text. |
| `image-fixture-not-generation` | **Fixed image fixture**, not AI generation | Studio → Image. Any prompt returns the same labelled image to test delivery, preview, download and library deletion. |

The small model is 135M, not 125M. Its Q4_K_M file comes from the published
[QuantFactory SmolLM2 model files](https://huggingface.co/QuantFactory/SmolLM2-135M-Instruct-GGUF/tree/main).
No fake reasoning or fixture is substituted for the real chat/reasoning models.
General visual understanding and real image generation are not provided by this session.
CPU reasoning can take time. The model check requires nonempty actual thinking and
answers, speech audio transcribed by Whisper, and OCR of a generated text image
before publishing a link. It does not prove model quality or every app interaction.

To start another session from GitHub, use Actions → Node baseline → Run workflow,
select this session branch, enable `preview`, and choose 10–90 minutes. Normal pushes
do not start model sessions. An explicitly marked `[model-preview]` commit on this
session branch can also start a session. Integration workflow-dispatch permission
was denied in this environment, so the requested session used that push trigger.

## Memory and privacy checks

- Search and browse Conversations, Messages, Saved knowledge and Artifacts.
- Select a row to read it; delete just that item after confirmation.
- Message deletion also removes matching branch copies and clears the conversation's
  derived context, embeddings and request logs. It does not erase unrelated messages.
- File deletion removes the owned library file and its database record. Files outside
  the media directory, including symlinks to external targets, are refused.
- New Studio image/speech outputs are saved into Artifacts when storage is enabled.
  Earlier outputs that were never saved cannot be recovered by this page.
- Fenced code blocks are also browsable/deletable artifacts within their messages.
- Add/edit/delete saved knowledge. This is library management, not a claim of complete
  semantic retrieval or automatic use of every saved memory by the chat model.
- Temporary chats never enter the library, server conversation state or request logs.
  Switching to another conversation, starting another chat or turning Temp off discards
  them. While you stay in one, its conversation is visible in browser memory only.
- Repeated New chat clicks reuse one matching empty Simple Mode draft; drafts are not
  persisted. Advanced-mode conversations remain locked to their mode.

Library search is live text search over saved content, including thinking, not an
embedding index. Paging limits the returned rows; searching still scans the loaded
chat collection. Very large datasets need indexed SQL search in a later scalability
pass rather than an unsupported claim of unlimited-scale indexing.
