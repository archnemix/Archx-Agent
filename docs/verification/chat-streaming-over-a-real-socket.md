# Historical verification: Chat streaming, over a real socket

This is a recorded run. See the [verification index](../VERIFICATION.md) for context.

## Chat streaming, over a real socket

```text
$ .venv/bin/python -m pytest tests/test_gui_stream.py -o addopts="" -q
8 passed in 4.05s

$ ./scripts/acceptance_m29.sh
[ok]   the stream is server-sent events = text/event-stream; charset=utf-8
[ok]   it sends more than one chunk, then a done frame = yes
[ok]   and exactly one done frame = 1
[ok]   the text the page paints adds up to the stored reply = 1
[ok]   a stream needs a credential, and says so = 403
M29 acceptance: 60 checks passed
```

The raw frames, from a real request:

```text
$ curl -sN -X POST -H 'X-Archx-Token: dbg' -H 'Content-Type: application/json' \
    -d '{"message":"stream this one"}' http://127.0.0.1:8498/api/chat/stream
event: chunk
data: {"text": "[SIMULATED] "}

event: chunk
data: {"text": "I received 3 words. "}

event: done
data: {"conversation_id": "conv_0001m616df3k...", "task": {"id": "tk_...", ...}, "text": "..."}
```

Writing those tests caught a real breakage at once: the new `SSEStream` dataclass had been inserted
*above* `Response.encode`, leaving the method on the wrong class, so every JSON response in the
application raised `AttributeError` — including 401s and 404s. Eight new tests found it in four
seconds. (The same class of mistake as run #2's duplicate `concurrency`: an edit that looks
additive and is not.)

