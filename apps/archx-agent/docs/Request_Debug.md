# Request debug

Request debug lists recorded provider requests, including model, key slot number, timing, request and response sizes, status and outcome. It does not intentionally store prompt text, model replies or key text. Provider error messages are redacted, but review an export before sharing it.

Select an entry for the stage and owner. **Request** means the app rejected input; **transport** means the network request failed or timed out; **HTTP** means a provider returned a status; **parse** means the response could not be read; **bounds** means an app safety limit stopped the response. A timeout belongs to the app, not a provider quota; a request that timed out or was cancelled may still be billed.

The first explanation can be dismissed with **OK, got it**. Use **Help** on the Debug page to read it again. **Export** saves a text report, **Reload** reloads the saved journal, and **Clear** deletes the journal. The journal retains at most 200 entries; older entries are removed when the limit is reached.
