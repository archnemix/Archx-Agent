"""Composition root.

This is the **only** layer that reads the environment, resolves configuration,
acquires resources and wires managers to adapters. Everything below it receives
what it needs through its constructor.
"""
