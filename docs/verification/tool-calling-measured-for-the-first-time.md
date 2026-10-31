# Historical verification: Tool calling, measured for the first time

This is a recorded run. See the [verification index](../VERIFICATION.md) for context.

## Tool calling, measured for the first time

```text
$ .venv/bin/python -m pytest tests/test_tool_probe.py -o addopts="" -q
4 passed in 3.06s

$ archx-agent models probe stub-model --capability tools
tools: passed  (called record_value with {"value": 1}, finish_reason=tool_calls)
  latency 12.4 ms
  state now verified (probe passed)

$ archx-agent models probe double --capability tools          # a runtime with no tool path
tools: failed  (ValidationError: the scripted runtime has no tool-calling path, so tool use
                 cannot be probed (evidence is not invented))
```

and a model that answers in prose while a tool is on the table:

```text
tools: failed  (MalformedOutputError: the model answered without calling the tool
                (reply: 'I would rather talk.'); tool use is not proven)
```


