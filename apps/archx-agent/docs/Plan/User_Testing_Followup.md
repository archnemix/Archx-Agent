# User testing follow-up

Status: in progress. Items remain open until implemented and verified, including a rebuilt Windows executable.

- [ ] Explain the four keep/drop columns and clarify Agent memory versus Runtime memory; ensure descriptions match actual behavior.
- [ ] Fix the Request debug explanation overflowing the bottom, make its first-time notice dismissible and not repeated, and provide accessible documentation.
- [ ] Investigate and fix incorrect selected states and behavior of the four Agent memory options and audit other option groups.
- [ ] Record all model-test requests and retries in Request debug without recording secrets or prompts.
- [ ] Pace model tests, sequentially and slowly with one key, distributing work across multiple keys with safe per-key pacing. Respect cancellation and provider errors.
- [ ] Show reasoning of up to five displayed lines without a nested scrollbar, accounting for wrapping and window width; scroll longer reasoning.
- [ ] Provide a model information view and a provider/free-tier listing based on the source list, including source, refresh timing, and warnings that information may be outdated.
- [ ] Keep the current chat viewport stable while streaming unless the user follows the tail or selects Jump to latest.
- [ ] Validate memory behavior with realistic synthetic data on GitHub Actions, checking actual loading and releasing, and report the limits of the measurements honestly.
- [ ] Run relevant tests and GUI checks; rebuild, commit and provide the Windows executable.
- [ ] Replace the Agent memory section with a Memory category and Runtime memory subsection, leaving room for other kinds of memory.
- [ ] Add per-model context settings with source-labelled known limits, optional user caps, and explicit handling of unknown or stale limits.
- [ ] Add configurable request/token rate limits (RPM/TPM), respecting provider and account scope; never promise an exact count without the provider's tokenizer or usage report.
- [ ] Design and implement safe context compaction: ask the user before requesting a summary, preserve recent messages in full, retain the original transcript, make summary failures visible, and account for summary request limits and cost.

## Known limitations while this work is in progress

- The current chat request builder silently limits context to the latest 12 completed turns. Per-model limits, approval for summary requests, and summary-based compaction are **not implemented**. Original transcripts remain stored; do not treat older turns as sent.
- Runtime cache stage transitions are not applied automatically yet; the screen calls this out. Debug journal and key-health rows are deliberately non-interactive until they can be unloaded safely.
- RSS review measures the process on Linux and checks a synthetic cache is emptied; allocator retention means process RSS may not fall immediately when a cache is dropped.
- The community free-tier list is informational and may be stale. It does not enforce account RPM or TPM limits.
- A green check on one commit or a previous Windows EXE does not validate later changes. Rebuild after all requested work is finished.
