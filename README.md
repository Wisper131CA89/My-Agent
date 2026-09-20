# My-Agent · 最小 ReAct 编程智能体 V0.4

这是一个适合学习的最小编程 Agent。它通过结构化工具调用完成下面的循环：

```text
用户任务 → 大模型 → 工具调用 → 工具结果 → 大模型 → 最终回答
```

文件工具使用统一工作目录策略。命令执行默认关闭；开启 run 模式后，测试会执行项目代码，
该模式只用于可信项目，不具备操作系统级隔离。

## 终极目标与升级路线

项目终极目标调整为：**实现与 General Robotics GRID 已公开功能一致的机器人智能体与开发平台**。从自然语言任务出发，调用与组合技能、生成代码，在仿真中验证和修正，积累可复用的经验，最终通过统一接口部署到真实机器人。

以下是功能目标，不代表当前 V0.4 已实现。RAI 继续作为机器人集成的参考项目；主要功能对标改为 GRID。核查日期：2026-09-17。官方文档当前以 v2.0 为入口；后续调整功能基线时应记录差异。

### 对标项目与公开代码

- [GRID 官方介绍](https://docs.generalrobotics.dev/)：机器人接入、仿真及真机会话、统一机器人接口、云端 AI 调用。
- [官方智能体架构说明](https://www.generalrobotics.company/post/agentic-robotics)：工具调用与代码生成两种执行方式、MCP 技能组合、仿真迭代、观察记忆和操作记忆。这是架构与演示说明，不等于每项能力都可以通过当前公开 SDK 独立部署。
- [官方 CLI 文档](https://docs.generalrobotics.dev/v2.0/cli/reference)：会话创建、查询与停止、机器人接入、集群切换及诊断。
- [官方文档索引](https://docs.generalrobotics.dev/llms.txt)：包含强化学习训练、策略推理、遥操作、ROS 2 通信和传感器等页面。
- [GRID-playground](https://github.com/GenRobo/GRID-playground)：公开的示例 Notebook、配置和资源；可参考机器人控制、AI 调用与数据采集流程，不是完整平台源码。
- [GRID-playground 许可证](https://github.com/GenRobo/GRID-playground/blob/main/LICENSE)：RAIL-S，授权含非商业用途与使用限制。不能按 MIT 或 Apache-2.0 的条件直接复用，引用或移植前需核查条款。
- [isaac-sim-mcp](https://github.com/GenRobo/isaac-sim-mcp)：公开的 Isaac Sim MCP 服务与扩展，仓库说明标注 MIT；可参考仿真播放控制、机器人检查、关节控制和日志采集。它是独立连接组件，不是 GRID 平台后台。
- [DreamControl](https://github.com/GenRobo/DreamControl)：公开的人形机器人轨迹生成、训练与仿真到真机研究代码；[其许可证](https://github.com/GenRobo/DreamControl/blob/main/LICENSE)限制为非商业研究或评估用途，不是完整 GRID 智能体实现。
- [Cortex SDK 文档](https://docs.generalrobotics.dev/v2.0/python-api/grid-cortex-client/overview)及 [PyPI 包](https://pypi.org/project/grid-cortex-client/)：客户端可安装，但客户端发布不代表云端推理服务和平台后台已开源；本次没有确认完整平台源码仓库。

官方当前安装说明要求组织集群访问，Windows 使用 WSL；这与现有 My-Agent 的 Windows 原生命令行不同。使用官方服务的路线还需要账户、独立的 Cortex 密钥及服务权限，DeepSeek 密钥不能替代。参见[官方安装说明](https://docs.generalrobotics.dev/v2.0/get-started/installation)。

### 功能基线与验收方向

| 功能领域 | My-Agent 的目标 | 验收方向 |
| --- | --- | --- |
| 任务与技能编排 | 分析任务、给出计划，工具调用与代码生成协作 | 完成多步骤任务，报告真实结果，失败后修正 |
| 技能库与 MCP | 技能具备参数、结果、约束、示例和版本；支持发现与组合 | 接入外部技能，经验证的组合可保存并再次调用 |
| 感知、规划与控制 | 接入检测、分割、深度、视觉理解、抓取及动作策略 | 从传感器观测得到可验证的感知结果，再生成受约束的动作 |
| 统一机器人接口 | 为机械臂、移动机械臂、轮式、四足、人形和无人机提供适配 | 同类任务可在仿真与真机之间切换；不同形态使用各自能力接口 |
| 仿真验证 | 场景与会话管理、执行观测、失败反馈和代码修正 | 多个固定测试场景有成功率、碰撞与超时指标 |
| 记忆与经验 | 保存观察、任务经历、技能结果和操作指南，按任务检索 | 重启后检索到有来源的经验，复用已验证技能 |
| 数据、训练与推理 | 传感器采集、合成数据、训练任务与策略版本管理 | 从数据记录到训练、评估、策略推理的流程可复现 |
| 开发与部署平台 | CLI、Notebook/IDE、可视化、真机部署和执行监控 | 会话可管理，部署可追踪与回滚，异常可停止 |
| 集群与团队管理 | 机器人注册、共享、认证、远端模型与计算资源调度 | 多用户、多机器人运行时，权限和资源记录可审计 |

这些验收方向是本项目的工程规划；完整功能一致还需要逐项场景测试，不能用一个演示任务代替。不同硬件、模型和服务的性能另行测量。

### 分阶段升级

| 阶段 | 主要交付 | 阶段验收 |
| --- | --- | --- |
| V0.2：已完成基础 | ReAct 循环、文件工具、权限模式、受限检查与离线测试 | 已有离线测试通过；真实模型调用单独验证 |
| V0.3：已完成 | 配置文件、技能注册与描述、计划和执行结果、独立 MCP 客户端模块 | 增加一个技能无需修改核心循环；连接一个受控 MCP 服务；只读模式不能调用修改类技能 |
| V0.4：当前版本 | 经测试的组合技能、任务记录、经验检索、来源和清理机制 | 重启后能检索并复用技能；未通过验证的代码不能自动成为可信技能 |
| V0.5：感知与机器人抽象 | 视觉服务适配、通用状态/图像/动作数据类型、模拟机器人和动作权限 | 根据录制图像或模拟传感器结果生成动作；能力缺失或参数越界时拒绝执行 |
| V0.6：首个仿真闭环 | 一个轻量场景，再接入一个可用的 3D 仿真后端；观测、执行、评分和修正 | 在仿真中完成寻找目标与避障，记录失败、修复和重复测试结果 |
| V0.7：多形态仿真与数据 | 扩展机械臂抓取和移动任务，增加场景配置、传感器记录及数据导出 | 至少覆盖机械臂和移动机器人；数据可回放，技能迁移差异有记录 |
| V0.8：训练与策略服务 | 训练配置、任务管理、策略推理、模型与技能版本 | 一个小型策略的训练与评估可复现，可比较版本并回退 |
| V0.9：真机与开发界面 | 一个真机适配器、动作审批和急停、Notebook/可视化、部署及执行监控 | 先在仿真通过，再在受控真机完成任务；断连和异常触发安全停止 |
| V1.0：平台功能验收 | 多用户、多机器人、远端模型服务、资源与会话管理；补齐各形态适配 | 按功能基线逐项验收并列出缺项；未通过时不得宣布与 GRID 功能一致 |

阶段版本是规划编号，不是发布日期。训练、3D 仿真和真机阶段按实测确定 Linux/WSL、GPU、设备和服务要求。模块可接入成熟组件，不需要从头编写物理引擎或训练所有基础模型。

### V0.3 已完成范围

先完成可扩展技能基础：增加 `SkillSpec`（名称、参数、返回值、权限、超时、版本及示例）和配置加载，将现有六个工具按统一描述注册；增加独立的 MCP 客户端模块，先连接本地受控服务，再按权限过滤外部工具。任务计划和执行结果应能显示，但不保存模型私有推理。

验收时完成“发现技能 → 校验参数与权限 → 执行 → 返回结果”的流程，覆盖外部服务断连、超时和权限拒绝。现有 V0.2 文件保护继续生效。这是历史范围；持久记忆已在 V0.4 增加，GPU 仿真和真机接入仍属于后续阶段。

## V0.3 历史升级说明

在项目目录内更新虚拟环境依赖（已有 V0.2 环境不需要为 V0.3 新增第三方依赖）：

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

### V0.3 显式配置、计划与 MCP

程序**不会**自动搜索或读取工作目录中的配置。使用配置时必须显式传入 `--config`；命令行
选项优先于文件，文件优先于内置默认值。TOML 中未知字段、错误类型或不合法数值会被拒绝，
并且配置不接受 API Key、令牌或密码等秘密字段。`workspace` 的相对路径以 TOML 文件所在
目录为基准。可复制 [mini-agent.example.toml](mini-agent.example.toml)：

```powershell
Copy-Item .\mini-agent.example.toml .\mini-agent.toml
New-Item -ItemType Directory -Force .\workspace
python -m mini_agent --config .\mini-agent.toml
# 显式选项覆盖 TOML
python -m mini_agent --config .\mini-agent.toml --mode read --no-show-plan
python -m mini_agent --config .\mini-agent.toml --list-skills
```

会话内 `/plan` 显示模型通过 `update_plan` 工具提交的简短公开步骤；程序不显示或记录
`reasoning_content`，只展示模型提交的简短行动计划；
`/skills` 列出当前权限模式实际可用的技能（外部 MCP 工具仅在已经连接的正常会话中出现）；
`--list-skills` 始终只列出离线内置技能，不连接 MCP 或模型。`/result` 将模型的最后回答、
停止状态与真实工具执行是否全部成功分开显示；仅更新计划不算实际任务执行成功。计划只保存在
内存中，并会在每个新任务开始时重置（`/clear` 同样会清空）。计划状态是模型提交的公开进度，
不是程序对任务完成的验证。

MCP 仅实现受控的**本地 stdio** 工具子集：以 UTF-8、每行一条 JSON-RPC 消息启动由配置明确
指定的进程，完成 initialize/initialized 和 tools/list/tools/call 生命周期。参考官方
[stdio transport](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)、
[lifecycle](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle) 与
[tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)。不支持 HTTP、OAuth、
resources 或 prompts。`tool_permissions` 是本地能力边界，服务器声明的 annotations 不会增加
权限；启动外部进程本身仍是对该程序的信任，不等同于授予其中每个工具权限。超时元数据会
约束 MCP 传输请求；普通进程内技能的 metadata 超时不能安全地强行中断任意 Python 代码。

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

V0.3 会显示每次工具调用的成功/失败、耗时和受限摘要。默认不持久化会话或工具内容；
可通过 `--log-runs` 显式开启 JSONL 执行元数据记录，具体参数以 `--help` 为准。

模型客户端对网络请求设置超时与有限重试，并显式关闭 DeepSeek 思考模式，以保持
最小工具调用消息协议。模型仍能分析任务、选工具和编写代码。未增加推理内容显示或记录。

### 添加可信本地技能

不要从配置动态导入 Python 代码。应用集成方应在自己的启动代码中显式构造 `Tool` 子类，并以
`additional_tools` 传给 `ReactAgent`；每个自定义工具都必须覆盖 `skill_spec()`，声明完整的
`SkillSpec` 契约。下面的只读示例无需改变 Agent 循环：

```python
from mini_agent import ReactAgent
from mini_agent.skills import SkillSpec
from mini_agent.models import ToolResult
from mini_agent.tools import Tool

class StatusTool(Tool):
    name = "status"
    description = "Read a trusted local status value."
    parameters = {"type": "object", "additionalProperties": False}

    def skill_spec(self):
        return SkillSpec(self.name, self.description, self.parameters, "Status text.",
                         "read", 5, "1.0", [], "local")

    def execute(self, arguments):
        return ToolResult(True, "ready")

agent = ReactAgent(config, model_client, additional_tools=[StatusTool(config.workspace)])
```

注册表会校验 JSON Schema、名称、权限和超时，并按 `read` / `edit` / `run` 模式过滤；没有显式
`read` 契约的自定义工具默认按 `run` 权限处理。

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

## V0.4：显式记忆与经验证配方

默认不会创建状态目录，也不会持久化用户提示、模型回答、源码、完整工具参数或密钥。只有传入
`--memory`（或显式 TOML `memory_enabled = true`）后，用户输入 `/remember`、`/save-task` 或配方
管理命令才会写入工作目录 `.mini-agent/memory.json` 和 `.mini-agent/recipes.json`。`/clear` 仅清空
当前会话，不会删除这些显式保存的资料。

Windows 下可在一次会话保存、重启后检索：

```powershell
mini-agent --workspace D:\AgentWorkspace\demo --memory
# 在交互界面：/remember pytest 失败时先阅读第一条错误并运行小范围测试
# 退出后重新启动：
mini-agent --workspace D:\AgentWorkspace\demo --memory --mode read
# 在交互界面：/memory pytest
```

也可把开关放入显式配置文件：

```toml
[agent]
workspace = "./workspace"
mode = "run"
memory_enabled = true
```

交互命令包括 `/remember TEXT`、`/memory [query]`、`/forget ID` 和 `/save-task TEXT`。后者只保存用户
提供的任务摘要，加上上一轮停止状态和工具名成功/失败元数据；不会保存模型最终代码或回答。
`/recipe-create NAME JSON_STEPS`、`/recipes`、`/recipe-verify NAME`、`/recipe-run NAME`、`/recipe-forget NAME`
直接由用户 CLI 管理，不需要模型批准。配方最多 8 步，且只允许 `read_file`、`list_files`、`search_text` 与
`run_command`；验证和运行会实际执行步骤，至少一个 `run_command` 成功才标记为已验证。

例如已存在 `calculator.py` 与 `test_calculator.py` 时，下面是一个先查看、再运行实际 pytest 的两步组合（必须在 `--mode run --memory` 中创建和验证）：

```text
/recipe-create inspect_then_test [{"tool":"read_file","arguments":{"path":"calculator.py"}},{"tool":"run_command","arguments":{"command":["python","-m","pytest","-q","test_calculator.py"]}}]
/recipe-verify inspect_then_test
/recipe-run inspect_then_test
```

`search_memory` 和 `list_recipes` 是只读模型工具；返回的记忆是**不可信历史资料**，不会进入 system
提示，也不能指示模型改变权限。`run_recipe` 是 run 权限工具，只能运行已验证的配方。模型没有创建、
验证或删除配方的工具，也不会把任意生成代码自动学习成技能。只读模式只能检索记忆或列出配方，不能保存、
创建、验证或运行配方。

配方验证会对工作目录做内容指纹；为保持可预测的资源上限，最多扫描 1,000 个文件和 2 MB，并排除
受保护路径与缓存（包括 `.mini-agent`）。工作目录变化会使配方失效，需重新验证。状态 JSON 仅适合单
会话本地使用，没有多进程锁、共享同步或多用户协调保证。
