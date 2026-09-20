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
    memory = parser.add_mutually_exclusive_group()
    memory.add_argument(
        "--memory",
        action="store_true",
        dest="memory_enabled",
        default=argparse.SUPPRESS,
        help="显式启用本地经验与配方持久化",
    )
    memory.add_argument(
        "--no-memory",
        action="store_false",
        dest="memory_enabled",
        default=argparse.SUPPRESS,
        help="禁用本地经验与配方持久化（默认）",
    )
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
            "memory_enabled",
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
        "memory_enabled": config.memory_enabled,
        "mcp_servers": config.mcp_servers,
    }
    values.update(overrides)
    return AgentConfig(**values)


def _print_skills(agent: ReactAgent) -> None:
    for spec in agent.registry.skill_specs():
        print(f"{spec.name}\t{spec.permission}\t{spec.description}")


def _state_enabled(agent: ReactAgent) -> bool:
    if agent.memory_store is None or agent.recipe_manager is None:
        print("持久记忆未启用；请在启动时传入 --memory 或在 TOML 设置 memory_enabled = true。")
        return False
    return True


def _can_mutate_state(agent: ReactAgent) -> bool:
    if not _state_enabled(agent):
        return False
    if agent.config.mode == "read":
        print("只读模式只能检索已保存内容，不能修改、验证或执行配方。")
        return False
    return True


def _print_records(records: object) -> None:
    if not isinstance(records, list) or not records:
        print("没有匹配的已保存记录。")
        return
    for record in records:
        if not isinstance(record, dict):
            continue
        print(
            f"- {record.get('id', 'unknown')} [{record.get('source', 'unknown')}] "
            f"{record.get('text', '')}"
        )


def _save_task_text(agent: ReactAgent, text: str) -> str:
    """Create an explicit, metadata-only task record; never save the model answer."""
    report = agent.last_turn
    tool_summary = (
        ", ".join(
            f"{item.name}:{'ok' if item.success else ('cancelled' if item.cancelled else 'failed')}"
            for item in report.tools
        )
        or "no_tools"
    )
    status = report.stop_reason if report.stop_reason != "cleared" else "no_completed_turn"
    return f"任务摘要：{text}\n停止状态：{status}\n工具元数据：{tool_summary}"


def _handle_state_command(agent: ReactAgent, user_input: str) -> bool:
    """Handle V0.4 commands.  Return true once the line has been consumed."""
    command, _, remainder = user_input.partition(" ")
    text = remainder.strip()
    try:
        if command == "/remember":
            if not _can_mutate_state(agent):
                return True
            if not text:
                print("用法：/remember TEXT")
                return True
            record = agent.memory_store.remember(text, source="user")  # type: ignore[union-attr]
            print(f"已保存经验：{record.get('id', 'unknown')}")
            return True
        if command == "/memory":
            if not _state_enabled(agent):
                return True
            _print_records(agent.memory_store.search(text, limit=10))  # type: ignore[union-attr]
            return True
        if command == "/forget":
            if not _can_mutate_state(agent):
                return True
            if not text:
                print("用法：/forget ID")
            elif agent.memory_store.forget(text):  # type: ignore[union-attr]
                print("已删除经验。")
            else:
                print("没有找到该经验。")
            return True
        if command == "/save-task":
            if not _can_mutate_state(agent):
                return True
            if not text:
                print("用法：/save-task TEXT")
                return True
            record = agent.memory_store.remember(  # type: ignore[union-attr]
                _save_task_text(agent, text), source="task"
            )
            print(f"已保存任务摘要：{record.get('id', 'unknown')}")
            return True
        if command == "/recipes":
            if not _state_enabled(agent):
                return True
            for recipe in agent.recipe_manager.list():  # type: ignore[union-attr]
                if isinstance(recipe, dict):
                    state = "已验证" if recipe.get("verified") else "未验证"
                    print(f"- {recipe.get('name', 'unknown')}（{state}）")
            return True
        if command == "/recipe-create":
            if not _can_mutate_state(agent):
                return True
            name, separator, raw_steps = text.partition(" ")
            if not name or not separator:
                print("用法：/recipe-create NAME JSON_STEPS")
                return True
            import json

            steps = json.loads(raw_steps)
            recipe = agent.recipe_manager.create(name, steps)  # type: ignore[union-attr]
            print(f"已创建配方：{recipe.get('name', name)}；请先使用 /recipe-verify。")
            return True
        if command == "/recipe-verify":
            if not _can_mutate_state(agent):
                return True
            if not text:
                print("用法：/recipe-verify NAME")
                return True
            result = agent.recipe_manager.verify(text)  # type: ignore[union-attr]
            if result.success:
                print("配方验证成功。")
            else:
                print(f"配方验证失败：{result.error_code or 'failed'}；请修复后重新验证。")
            return True
        if command == "/recipe-run":
            if not _can_mutate_state(agent):
                return True
            if agent.config.mode != "run":
                print("运行配方需要 --mode run。")
                return True
            if not text:
                print("用法：/recipe-run NAME")
                return True
            result = agent.recipe_manager.run(text)  # type: ignore[union-attr]
            if result.success:
                print(result.content)
            else:
                print(f"配方运行失败：{result.error_code or 'failed'}；可能需要重新验证。")
            return True
        if command == "/recipe-forget":
            if not _can_mutate_state(agent):
                return True
            if not text:
                print("用法：/recipe-forget NAME")
            elif agent.recipe_manager.forget(text):  # type: ignore[union-attr]
                print("已删除配方。")
            else:
                print("没有找到该配方。")
            return True
    except KeyboardInterrupt:
        print("持久状态操作已取消；会话仍可继续。")
        return True
    except Exception:  # noqa: BLE001 - persisted state must never break the REPL.
        print("持久状态操作失败；会话仍可继续。", file=sys.stderr)
        return True
    return False


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
        print("Mini ReAct Agent V0.4")
        print(f"工作目录：{config.workspace}")
        print(
            f"运行模式：{config.mode}；命令执行：{'已启用（受限）' if config.allow_run else '已禁用'}"
        )
        print(f"持久记忆：{'已启用' if config.memory_enabled else '未启用（默认）'}")
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
            if _handle_state_command(agent, user_input):
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
                    "输入编程任务；/plan、/skills、/result、/clear；持久化：/remember、/memory、/forget、/save-task、/recipes、/recipe-create、/recipe-verify、/recipe-run、/recipe-forget；/exit 退出。"
                )
                continue
            try:
                print(f"\nAgent > {agent.run_turn(user_input)}")
            except Exception:  # noqa: BLE001
                print("\n发生未预期错误；会话仍可继续。", file=sys.stderr)


class _OfflineModel:
    def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        raise RuntimeError("离线技能列表不会调用模型")
