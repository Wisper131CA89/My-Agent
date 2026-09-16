# Changelog

## 0.2.0

- Add read/edit/run permission modes and retain `--allow-run` compatibility.
- Validate tool arguments locally against JSON Schema and return structured errors.
- Recover tool-call message state after failures and cancellation.
- Apply consistent workspace, sensitive-file, and link checks across file and search tools.
- Bound file reads, search work, tool output, and command execution.
- Use approved verification command grammar and the running Python interpreter.
- Remove model credentials from child process environments.
- Display actual tool outcomes and support opt-in metadata-only JSONL run records.
- Explicitly use DeepSeek non-thinking mode for the minimal tool-calling loop.
- Add offline regression tests and Windows-oriented setup guidance.

Run mode executes trusted project code and is not an OS sandbox. Live provider behavior is not
established by offline tests; a real API smoke test is a separate check.
