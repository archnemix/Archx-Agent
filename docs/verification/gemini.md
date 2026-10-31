# Historical verification: Gemini acceptance transcript

This is a recorded run. See the [verification index](../VERIFICATION.md) for context.

## Gemini acceptance transcript

Run in this sandbox on the branch above. The vendor's host is unreachable from here (see below),
so the client is driven against `scripts/gemini_protocol_stub.py` on a real socket, and the
acceptance script starts and stops that stub across eight failure modes.

```text
$ ./scripts/acceptance_gemini.sh
### a Gemini model is registered with a *reference*, never the key
[ok]   add-gemini exits 0 = 0
[ok]   the runtime is gemini = 1
[ok]   the reference is reported, not the key = 1
[ok]   the key is not in the CLI output = 0
[ok]   the model row stores the reference = secret://env/GEMINI_API_KEY
[ok]   a literal key exits 2 = 2
[ok]   it says credentials must be a reference = 1
### the probe is a measurement: it calls the endpoint and records the outcome
[ok]   the probe passed = 1
[ok]   the capability is now verified = True
### a chat turn goes through the socket and comes back parsed
[ok]   the reply is the stub's, parsed out of candidates[0].content.parts = 1
[ok]   the reply is not labelled simulated = 0
[ok]   usage was parsed from usageMetadata into the task record = True
### the errors are classified, not collapsed into one another
[ok]   a 401 is an auth failure = 1
[ok]   a plain 429 is a rate limit = 1
[ok]   an exhausted quota is named separately from a burst limit = 1
[ok]   an unknown model is model-not-found = 1
[ok]   a content-policy block is not an empty reply = 1
[ok]   an empty candidate list is a malformed output, not a silent success = 1
[ok]   a 500 is a provider outage = 1
[ok]   the endpoint recovers: the next call succeeds = 1
[ok]   the echoed key is not shown = 0
[ok]   the redaction is visible, not silent = 1
### the consent ladder: a remote endpoint is refused until every rung is climbed
[ok]   rung 1: model.local_only refuses the first call = 1
[ok]   rung 2: an unregistered endpoint is refused = 1
[ok]   and the hint names the right template for a Gemini model = 1
[ok]   rung 3: unknown privacy terms are refused = 1
[ok]   rung 4: missing consent is refused = 1
[ok]   the ladder is open, so the call now reaches the network layer = 1
[ok]   and the refusal is about the network, not about consent = 0
### the GUI exposes the same ladder, and refuses the same things
[ok]   the cloud model carries four rungs = consent,consent_policy,privacy,provider
[ok]   every rung reads passed once the ladder is climbed = True
[ok]   a literal key posted to the GUI is refused = 400
[ok]   a chat through the GUI returns the parsed reply = True
[ok]   the key is not served to the browser = 0
### the key never landed anywhere it could be read back
[ok]   no file under the home holds the key = 0
[ok]   the workspace database does not contain it = 0
[ok]   the trace does not contain it = 0

Gemini acceptance: 60 checks passed
```

The rung-by-rung refusals are the exact wording the CLI prints, so the transcript doubles as
documentation of the ladder:

```text
error: model 'cloud' cannot be used: remote policy: refusing to send data to a remote endpoint:
       model.local_only is true. Register the endpoint as a provider and set model.local_only=false deliberately.
error: model 'cloud' cannot be used: remote policy: the endpoint https://generativelanguage.googleapis.com
       is not a registered provider. Add it with `archx-agent providers add <name> --template google` …
error: model 'cloud' cannot be used: remote policy: privacy terms are unknown; confirm them with
       `archx-agent providers confirm prov_… --data-leaves-device yes|no`
error: model 'cloud' cannot be used: remote policy: this provider receives your data remotely;
       record explicit consent with `archx-agent providers consent prov_…` before use
```

### The browser side

```text
$ ARCHX_JSDOM_DIR=/tmp/domtest node scripts/gui_smoke.mjs
smoke ok: 10 tabs, 4 gate rows, form posts, no page errors
```

The harness loads the shipped `index.html` + `app.js` in jsdom against a fake server, clicks
every refresh control, opens the Models view, asserts four ladder rows with only the buttons
that can act (no `Record consent` before a provider exists), submits the Connect Gemini form
and checks that it posted and cleared the reference field. jsdom is not a project dependency;
the script says so and exits 2 with the install line if it is missing.

### The whole suite

```text
$ .venv/bin/python -m pytest -o addopts="" -q
1190 passed in 253.19s

$ ./scripts/acceptance_m29.sh
M29 acceptance: 55 checks passed

$ ./scripts/acceptance_m30.sh
M30 acceptance: 90 checks passed

$ ./scripts/acceptance_research_close.sh
Research closure acceptance: 35 checks passed
```

### What could not be verified here

The sandbox's egress filter accepts the TCP connection to `generativelanguage.googleapis.com:443`
and then closes the TLS handshake (`SSLZeroReturnError`), and does the same for
`www.google.com`; `api.github.com` answers normally, so this is the filter and not a local
misconfiguration. A real key could therefore not complete a live call, and no document in this
repository claims one was made. What is proven is the client's half of the protocol, byte for
byte, against a server that speaks it - plus every gate, error path and redaction around it.

