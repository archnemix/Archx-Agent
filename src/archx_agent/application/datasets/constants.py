"""Vocabulary and defaults for dataset preparation."""

from __future__ import annotations


TEXT_SUFFIXES = (
    ".txt",
    ".md",
    ".markdown",
    ".rst",
    ".json",
    ".jsonl",
    ".csv",
    ".tsv",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".html",
    ".css",
    ".sql",
    ".sh",
    ".c",
    ".h",
    ".cc",
    ".cpp",
    ".go",
    ".rs",
    ".java",
    ".rb",
    ".php",
    ".log",
    ".tex",
)

RULES = {
    "drop_empty": "the file is empty",
    "drop_binary": "not a text file this build can parse",
    "min_chars": "fewer characters than the min_chars rule allows",
    "dedupe": "the same content is already in the dataset from an earlier path",
    "strip": "leading and trailing whitespace was trimmed",
    "require_license": "the dataset's license is unknown, so nothing may be published from it",
}

LEAK_TEXT = "the same text (ignoring whitespace and case) appears in two splits"
