# Using Archx Agent

## Install and open

Use Node.js 22.5 or newer, run `npm ci`, then `npm start`. There is no pip installation
or Python virtual environment in this implementation. The CLI prints its URL and
normally opens your browser. Use `npm start -- --no-open` to open it yourself.

## Connect your model

1. Open Settings → Providers and choose a preset or enter your server endpoint.
2. For Ollama, use `http://127.0.0.1:11434/v1`; local Ollama normally needs no key.
3. Save the provider, fetch its models, and add the models you want available.
4. Choose the provider and model from Chat's top-left picker. Send a message.

Use Stop or Escape to stop generation. Thinking appears only when returned by the
provider. Expand code/table/thinking panels while reading; the renderer preserves
those surfaces as tokens arrive. Use New content to return to the latest output.
Edit/resend and Regenerate keep alternate continuations in the branch menu.

## Research and advanced controls

The Web toggle searches from your question and displays search/source cards. This
uses external search engines and sends your query to them. It is not yet the complete
autonomous research workflow. Debug is separate from normal conversation. Settings
contains generation controls, prompts, providers, models, profiles and storage.

## Data and upgrades

Use a separate test data folder and back up existing data before an upgrade. Never
reuse the former Python workspace as this Node app's database. There is no importer
for that format. Temporary chats/memory-only mode do not survive a server restart.
Keep the default loopback bind. The inherited server has no complete remote-user
security boundary; `--host 0.0.0.0` is not a safe public deployment configuration.
