# My-Agent · 最小 ReAct 编程智能体 V0.2

这是一个适合学习的最小编程 Agent。它通过结构化工具调用完成下面的循环：

```text
用户任务 → 大模型 → 工具调用 → 工具结果 → 大模型 → 最终回答
```

文件工具使用统一工作目录策略。命令执行默认关闭；开启 run 模式后，测试会执行项目代码，
该模式只用于可信项目，不具备操作系统级隔离。

## 从 V0.1 升级

在项目目录内更新虚拟环境依赖（V0.2 新增 JSON Schema 参数校验）：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -q -c pyproject.toml
```

使用完整解释器路径时不必激活虚拟环境。这个独立项目不需要 ROS 2 或 RAI 的 Bash 初始化。
原有 `--allow-run` 保留；建议新命令使用 `--mode run`。

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
接口地址：https://api.deepseek.com
模型：deepseek-v4-flash
```

可通过 `--model` 指定账户可用的其他模型，例如：

```powershell
python -m mini_agent --workspace D:\Projects\demo --model deepseek-v4-pro
```

## 使用

先创建工作目录，再设置当前窗口的密钥。密钥也可以通过不回显的交互输入设置，避免把
真实值写入 PowerShell 命令历史：

```powershell
New-Item -ItemType Directory -Force D:\AgentWorkspace\demo
$credential = New-Object System.Management.Automation.PSCredential('deepseek', (Read-Host '请输入 DeepSeek 密钥' -AsSecureString))
$env:DEEPSEEK_API_KEY = $credential.GetNetworkCredential().Password
Remove-Variable credential
```

只读模式，模型无法使用写入或执行工具：

```powershell
python -m mini_agent --workspace D:\AgentWorkspace\demo --mode read
```

只允许读取和修改代码，不允许运行命令：

```powershell
mini-agent --workspace D:\Projects\demo --mode edit
```

允许运行受限的测试/检查命令：

```powershell
mini-agent --workspace D:\Projects\demo --mode run
```

也可以直接运行模块：

```powershell
python -m mini_agent --workspace D:\Projects\demo
```

交互命令：

- `/help`：显示帮助
- `/clear`：清空当前会话
- `/exit`：退出

V0.2 会显示每次工具调用的成功/失败、耗时和受限摘要。默认不持久化会话或工具内容；
可通过 `--log-runs` 显式开启 JSONL 执行元数据记录，具体参数以 `--help` 为准。

模型客户端对网络请求设置超时与有限重试，并显式关闭 DeepSeek 思考模式，以保持
最小工具调用消息协议。模型仍能分析任务、选工具和编写代码。未增加推理内容显示或记录。

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
- 命令执行需要显式 `--mode run` 或 `--allow-run`；
- 工具只接受固定验证命令，不提供包安装、网络下载或任意 shell 入口；
- 每个命令都有超时和输出上限。

必须区分文件工具策略与运行代码的权限：pytest、项目导入和插件均可能执行代码，
这些代码仍受当前操作系统用户权限控制。移除子进程的 API Key 环境变量只是减少意外泄露，
不能阻止恶意代码通过其他途径访问系统。请勿把 run 模式用于不可信仓库。

受支持的验证操作是 pytest、compileall 和 Ruff 检查；完整允许参数由命令工具校验。
不支持直接执行 `python hello.py`、解释器 `-c`、pip 或任意外部程序。

如果要处理不可信仓库或执行不可信生成代码，仍应在专用容器或虚拟机中运行。

## 测试

```powershell
python -m pytest -q
python -m ruff check .
```

单元测试使用假模型，不会请求真实 API，也不会产生模型费用。

## 验收练习

1. 用 `--mode read` 提问“目录中有哪些文件？”并确认没有写入能力。
2. 用 `--mode edit` 要求“在当前目录创建 calculator.py 和 test_calculator.py，不运行测试”。
3. 检查生成的代码，再用 `--mode run` 要求“运行 pytest，报告真实结果，必要时修复”。
4. 查看工具的成功/失败结果；最终回答不能代替测试退出码。

真实 DeepSeek 验收需要你本地配置的密钥并会产生 API 费用；离线测试通过不代表实时服务
的模型权限、余额或网络可用性已验证。

开发规范见 [AGENTS.md](AGENTS.md)，版本变更见 [CHANGELOG.md](CHANGELOG.md)。
