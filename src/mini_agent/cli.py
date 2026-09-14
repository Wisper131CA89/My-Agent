from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .agent import ReactAgent
from .config import AgentConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Workspace-confined ReAct coding agent")
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--model", default="deepseek-v4-flash")
    parser.add_argument("--base-url", default="https://api.deepseek.com")
    parser.add_argument("--max-steps", type=int, default=20)
    parser.add_argument("--allow-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        from .llm import DeepSeekChatClient

        config = AgentConfig(
            workspace=args.workspace,
            model=args.model,
            base_url=args.base_url,
            max_steps=args.max_steps,
            allow_run=args.allow_run,
        )
        client = DeepSeekChatClient(config.model, config.base_url)
    except (ImportError, OSError, ValueError) as exc:
        print(f"启动失败：{exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    agent = ReactAgent(config, client, on_action=lambda text: print(f"  … {text}"))
    print("Mini ReAct Agent")
    print(f"工作目录：{config.workspace}")
    print(f"命令执行：{'已启用（受限）' if config.allow_run else '已禁用'}")
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
        if user_input == "/help":
            print("输入编程任务；/clear 清空会话；/exit 退出。")
            continue
        try:
            print(f"\nAgent > {agent.run_turn(user_input)}")
        except Exception as exc:
            print(f"\n模型调用失败：{type(exc).__name__}: {exc}", file=sys.stderr)
