# Mini ReAct Agent

这是一个适合学习的最小编程 Agent。它通过结构化工具调用完成下面的循环：

```text
用户任务 → 大模型 → 工具调用 → 工具结果 → 大模型 → 最终回答
```

它只允许访问启动时指定的工作目录。命令执行默认关闭；即使开启，也只接受有限的开发
命令，并且不通过 shell 执行。

## 环境准备

需要 Python 3.11 或更高版本。推荐在本目录创建虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

本项目默认使用 DeepSeek 官方 API。先在 DeepSeek 开放平台创建 API Key，然后只通过环境
变量设置：

```powershell
$env:DEEPSEEK_API_KEY = "你的DeepSeek密钥"
```

不要把密钥写入源码、`AGENTS.md`、README 或提交到 Git。

默认配置为：

```text
Base URL: https://api.deepseek.com
Model: deepseek-v4-flash
```

也可以在启动时选择能力更强、成本更高的模型：

```powershell
python -m mini_agent --workspace D:\Projects\demo --model deepseek-v4-pro
```

## 使用

只允许读取和修改代码，不允许运行命令：

```powershell
mini-agent --workspace D:\Projects\demo
```

允许运行受限的测试/检查命令：

```powershell
mini-agent --workspace D:\Projects\demo --allow-run
```

也可以直接运行模块：

```powershell
python -m mini_agent --workspace D:\Projects\demo
```

交互命令：

- `/help`：显示帮助
- `/clear`：清空当前会话
- `/exit`：退出

## 内置工具

- `list_files`：查看目录结构
- `read_file`：分段读取文本文件
- `search_text`：搜索文本或代码
- `write_file`：创建新文本文件，默认拒绝覆盖
- `apply_patch`：用唯一匹配的旧文本局部替换
- `run_command`：可选的受限命令执行

## 安全边界

这是教学型安全边界，不等于操作系统级沙箱：

- 路径解析后必须仍位于工作目录中；
- 拒绝 `.env`、私钥、证书和常见凭据文件；
- 忽略 `.git`、虚拟环境、缓存、构建目录和 `node_modules`；
- 不提供删除工具；
- 命令不经过 PowerShell、CMD 或 Bash；
- 命令执行需要显式 `--allow-run`；
- 禁止包安装、网络命令和任意可执行文件；
- 每个命令都有超时和输出上限。

如果要处理不可信仓库或执行不可信生成代码，仍应在专用容器或虚拟机中运行。

## 测试

```powershell
python -m pytest -q
python -m ruff check .
```

单元测试使用假模型，不会请求真实 API，也不会产生模型费用。
