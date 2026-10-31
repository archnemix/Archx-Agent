"""External systems: model runtimes, providers, tools, MCP, sandboxes, media.

Adapters may import ``helpers`` only. They never write to the database and never
make permission decisions - they report capability and failure, and the
application layer decides.
"""
