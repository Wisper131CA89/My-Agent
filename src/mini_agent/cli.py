from __future__ import annotations

import argparse
import os
import sys
from contextlib import ExitStack
from pathlib import Path

from .agent import ReactAgent
from .config import AgentConfig, load_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="受工作目录限制的 ReAct 编程 Agent")
    parser.add_argument("--config", type=Path, metavar="TOML", help="显式读取的可信 TOML 配置")
    parser.add_argument("--workspace", type=Path, default=argparse.SUPPRESS)
    parser.add_argument("--model", default=argparse.SUPPRESS)
    parser.add_argument("--base-url", default=argparse.SUPPRESS)
    parser.add_argument("--max-steps", type=int, default=argparse.SUPPRESS)
    parser.add_argument("--mode", choices=("read", "edit", "run"), default=argparse.SUPPRESS)
    parser.add_argument("--allow-run", action="store_true", default=argparse.SUPPRESS)
    parser.add_argument("--log-runs", type=Path, metavar="JSONL", default=argparse.SUPPRESS)
    parser.add_argument("--show-plan", action="store_true", default=argparse.SUPPRESS)
    parser.add_argument(
        "--no-show-plan", action="store_false", dest="show_plan", default=argparse.SUPPRESS
    )
    parser.add_argument("--list-skills", action="store_true", help="列出本地技能并退出，不连接模型")
    return parser


def _make_config(args: argparse.Namespace) -> AgentConfig:
    overrides = {
        key: getattr(args, key)
        for key in (
            "workspace",
            "model",
            "base_url",
            "max_steps",
            "mode",
            "allow_run",
            "log_runs",
            "show_plan",
        )
        if hasattr(args, key)
    }
    if "mode" in overrides and "allow_run" in overrides:
        raise ValueError("--allow-run cannot be combined with --mode")
    if overrides.pop("allow_run", False):
        # The compatibility flag is a CLI override and must not inherit a
        # less-permissive mode from the selected TOML file.
        overrides["mode"] = "run"
    if args.config:
        return load_config(args.config, overrides)
    config = AgentConfig(workspace=Path.cwd())
    if not overrides:
        return config
    values = {
        "workspace": config.workspace,
        "model": config.model,
        "base_url": config.base_url,
        "max_steps": config.max_steps,
        "max_consecutive_errors": config.max_consecutive_errors,
        "max_tool_output_chars": config.max_tool_output_chars,
        "mode": config.mode,
        "allow_run": False,
        "log_runs": config.log_runs,
        "show_plan": config.show_plan,
        "mcp_servers": config.mcp_servers,
    }
    values.update(overrides)
    return AgentConfig(**values)


def _print_skills(agent: ReactAgent) -> None:
    for spec in agent.registry.skill_specs():
        print(f"{spec.name}\t{spec.permission}\t{spec.description}")


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        config = _make_config(args)
    except (OSError, ValueError, PermissionError) as exc:
        print(f"启动失败：{exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    with ExitStack() as stack:
        extra_tools = []
        try:
            if not args.list_skills:
                for server in config.mcp_servers:
                    from .mcp import MCPClient

                    client = stack.enter_context(
                        MCPClient(server, config.workspace, config.max_tool_output_chars)
                    )
                    extra_tools.extend(client.discover_tools())
            if args.list_skills:
                agent = ReactAgent(config, _OfflineModel())
                _print_skills(agent)
                return
            if not os.environ.get("DEEPSEEK_API_KEY"):
                print(
                    "启动失败：未检测到 DEEPSEEK_API_KEY；请先在当前终端设置 DeepSeek API 密钥。",
                    file=sys.stderr,
                )
                raise SystemExit(2)
            from .llm import DeepSeekChatClient

            agent = ReactAgent(
                config,
                DeepSeekChatClient(config.model, config.base_url),
                on_action=lambda text: print(f"  … {text}"),
                additional_tools=extra_tools,
            )
        except KeyboardInterrupt:
            print("启动已取消。", file=sys.stderr)
            raise SystemExit(130) from None
        except (ImportError, OSError, ValueError, PermissionError, RuntimeError):
            # Transport and plugin exceptions may embed paths, command lines,
            # server replies, or credentials.  Keep terminal startup errors
            # deliberately generic.
            print("启动失败：无法初始化受信任的本地服务。", file=sys.stderr)
            raise SystemExit(2) from None
        print("Mini ReAct Agent V0.3")
        print(f"工作目录：{config.workspace}")
        print(
            f"运行模式：{config.mode}；命令执行：{'已启用（受限）' if config.allow_run else '已禁用'}"
        )
        print("输入 /help 查看帮助，/exit 退出。")
        while True:
            try:
                user_input = input("\n你 > ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n再见。")
                return
            if user_input in {"/exit", "/quit"}:
                print("再见。")
                return
            if user_input == "/clear":
                agent.clear()
                print("会话已清空。")
                continue
            if user_input == "/plan":
                print(agent.plan_text())
                continue
            if user_input == "/skills":
                _print_skills(agent)
                continue
            if user_input == "/result":
                report = agent.last_turn
                print(f"状态：{report.stop_reason}")
                print(f"模型回答：{report.final_response or '无（本轮未得到模型最终回答）'}")
                if not report.tools:
                    print("工具执行：未执行工具")
                else:
                    print(f"工具全部成功：{'是' if report.executed_success else '否'}")
                    for item in report.tools:
                        state = "已取消" if item.cancelled else ("成功" if item.success else "失败")
                        print(f"- {item.name}：{state}")
                continue
            if user_input == "/help":
                print(
                    "输入编程任务；/plan 查看公开计划；/skills 列出技能；/result 查看上一轮执行；/clear 清空会话；/exit 退出。"
                )
                continue
            try:
                print(f"\nAgent > {agent.run_turn(user_input)}")
            except Exception:  # noqa: BLE001
                print("\n发生未预期错误；会话仍可继续。", file=sys.stderr)


class _OfflineModel:
    def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        raise RuntimeError("离线技能列表不会调用模型")
