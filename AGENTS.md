# AGENTS.md

## Scope

These instructions apply to every file under `mini-react-agent/`.
Do not modify files outside this directory unless the user explicitly expands the scope.

This is the independent My-Agent Python project. Its own tests and commands run on Windows or
Linux without ROS 2, colcon, or the parent RAI shell setup. The parent RAI runtime prerequisites
apply to RAI packages, not to this independent project.

## Delegation

- Keep architecture, trade-offs, final review, and acceptance with the primary agent.
- Use the user's currently selected primary model when explicitly requested for the task.
- Delegate bounded implementation work to `gpt-5.6-terra` with medium reasoning effort when useful.
- Report unavailable model selections rather than claiming an unperformed model switch.
- Assign disjoint file ownership and review subagent changes before acceptance.

## Product goal

Build a small, understandable command-line ReAct coding agent. It may inspect and edit only a
user-selected workspace. The first priority is correctness and safety; cleverness and feature count
come later.

## Required behavior

- Explain important decisions in plain language suitable for a beginner.
- Inspect relevant code before editing it. Never invent the contents of an unread file.
- Keep model access, the agent loop, tools, and the CLI in separate modules.
- Prefer small, reviewable patches over broad rewrites.
- Preserve public behavior unless the requested change explicitly alters it.
- Use type hints for public functions and dataclasses for internal data transfer objects.
- Never hard-code API keys, tokens, passwords, or user-specific absolute paths. DeepSeek credentials
  must be read from `DEEPSEEK_API_KEY`.
- Read secrets only from environment variables. Never print or log secret values.
- Treat model-produced tool names and arguments as untrusted input.

## Filesystem safety contract

- Every filesystem target must be resolved and verified to remain inside the configured workspace.
- Do not follow a symlink to a target outside the workspace.
- Refuse access to secret-like files such as `.env`, private keys, credentials, and certificates.
- `write_file` creates new files by default and must refuse accidental overwrite.
- Modify an existing file with an exact, uniquely matching patch whenever practical.
- Do not implement recursive deletion or an unrestricted shell tool.

## Command execution contract

- Command execution is disabled unless the user starts the app with `--mode run` or the legacy
  `--allow-run` alias. Read mode must never expose mutation tools.
- Execute argument arrays without a shell (`shell=False`).
- Allow only explicitly listed development commands.
- Apply a timeout and output-size limit to every subprocess.
- Validate the complete command and arguments, not only the executable prefix.
- Do not pass model API credentials to subprocesses.
- Pytest executes project code: run mode is for trusted code, not an operating-system sandbox.
- Never install packages, access the network, change system configuration, or launch background
  services without explicit user authorization.

## Development workflow

1. Read the relevant implementation and tests.
2. State the smallest intended change.
3. Make the change with `apply_patch`.
4. Run the narrowest relevant tests first.
5. Run the complete project test suite before handoff when the environment permits.
6. Report changed files, checks run, failures, and anything not verified.

## Commands

Run from `mini-react-agent/`:

```powershell
python -m pytest -q
python -m ruff check .
python -m mini_agent --help
```

Do not claim a command passed unless it was actually executed successfully.

## Testing requirements

- Add or update tests for every behavior change.
- Use a fake model in unit tests; normal tests must never call a paid API.
- Path-containment and secret-file rules require explicit negative tests.
- Tests must not read or modify the user's real files.
- Use pytest temporary directories for filesystem tests.
- All tools must enforce the same workspace policy, including each file read by search.
- Tool arguments must be validated locally before execution.
- Every assistant tool call must receive a result, including cancelled calls after failure.
- Cover failure recovery across subsequent turns and attempts to bypass policy.
- Execution logs contain bounded metadata, not source contents, full arguments, keys, or reasoning.

## Definition of done

A change is complete only when its behavior is implemented, relevant tests pass, documentation is
updated when user-facing behavior changed, and remaining limitations are disclosed.
