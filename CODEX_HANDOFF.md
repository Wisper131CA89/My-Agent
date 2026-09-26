# My-Agent 跨设备开发交接说明

整理日期：2026-09-26（Asia/Shanghai）。本文件面向新设备上的 Codex，迁移后请先完整阅读，再检查实际代码与环境。

同日补充：原开发对话已直接将自身可见的必要信息整合到本文件。**最新产品目标是通过机械臂摄像头感知环境、识别手势并控制机械臂执行相应操作**；“全面对标 GRID”已被用户撤销，不能再用作升级验收目标。第 4 节已更正，第 11 节记录开发协作连接与迁移事项。

## 1. 交接来源与可信范围

用户要求把本项目两个 Codex 对话的必要信息整合到一个文件，以便更换设备后继续开发。

初次整理时，用户提供了另一任务的实时引用：hostId=`local`，threadId=`01a09ac8-aa22-7312-9d3e-d1b4cfc56d3f`，链接 `thread://01a09ac8-aa22-7312-9d3e-d1b4cfc56d3f?hostId=local`，但当时无法通过工具读取。用户随后回到该原开发对话，要求直接补充本文件，因此已经补入其可见的关键决定。local 引用可能依赖原设备记录，不保证迁移后可解析；新设备继续工作不以恢复该引用为前提。

本文件整合了两个对话各自可见的用户要求、代码解释、工作规范、项目文档、实际源码和本地 Git 记录。这是开发交接摘要，不是两条对话的完整导出；未记录的决定或验收结果不得自行补写为已确认事实。第 9 节中的环境检查失败来自初次整理对话；第 11 节中的连接验证来自原开发对话，二者不能混为本次重新执行的结果。

重要纠正：本对话早期解释的是 V0.2；迁移整理时实际项目已经是 **V0.4.0**。继续开发必须以当前源码为准，不能按旧解释认为计划、技能契约、MCP 和持久记忆尚未实现。

本文件不包含密钥、个人工作区内容、完整工具参数日志或私人推理。整理过程未读取 `mini-agent.toml` 或 `workspace/` 的内容。

## 2. 项目定位、目录与版本

- 原设备外层路径：`D:\Project\rai-main`，这是 RAI 参考项目目录；整理时该外层目录未识别为 Git 仓库。
- 用户自主开发项目：`mini-react-agent/`，独立 Python 包和独立 Git 仓库。
- 原设备开发目录：`D:\Project\rai-main\mini-react-agent`。新设备路径可不同，不要硬编码原设备路径。
- 包名：`mini-react-agent`；导入名：`mini_agent`；命令入口：`mini-agent` / `python -m mini_agent`。
- `pyproject.toml` 版本：`0.4.0`；Python 要求：`>=3.11`。
- 当前 HEAD：`759f3be`，`feat: add opt-in persistent memory and verified recipes for v0.4`。
- 2026-09-26 补充核实：当前分支 `feat/v0.4`，跟踪 `origin/feat/v0.4`；远端为 `https://github.com/Wisper131CA89/My-Agent.git`。没有执行 fetch，不能据本地跟踪信息推断远端当日最新状态。
- 写入本交接文件前，子项目 `git status --short` 无输出，即被 Git 跟踪的工作树干净；被忽略文件不在这个结论内。

最近提交（由新到旧）：

| 提交 | 内容 |
| --- | --- |
| `759f3be` | V0.4：显式持久记忆与经验证配方 |
| `486abcd` | V0.3：可扩展技能与本地 MCP |
| `986d987` | 长期目标调整为 GRID 公开功能 |
| `186dfb2` | 项目文档使用中文 |
| `07e1ce5` | V0.2：可靠工具执行基础 |
| `d07d4c1` | 初始上传 |

## 3. 用户最新工作偏好（优先于文档中的旧偏好）

用户最新消息明确替换此前提供的 AGENTS 指令。后续遵循：

1. 主代理用于架构、规划、权衡和最终验收，用户偏好 `gpt-6-sol`、高推理强度。
2. 简单、范围清楚的只读代码任务委派给 `code_reader`：`gpt-6-luna`、低推理强度、只读沙箱。适用文件查找、符号定位、简单调用链和证据收集；不用于修改、复杂调试或架构决策。
3. 有独立范围的实现任务，在有益时委派给 `gpt-6-sol`、`medium`。支持参数时显式指定；完整历史 fork 不允许覆盖模型时，使用有限历史或无历史并补足上下文。
4. 子代理必须报告证据、变更、测试和未解决项；主代理审查后验收。不要为一步小操作创建子代理。
5. 无法选择请求的模型或推理强度时如实说明，不能声称切换成功。Codex 自身使用的模型与 My-Agent 运行时调用的 DeepSeek 模型是两套配置。
6. 用户偏好中文、容易理解的解释；需要做事时持续完成已授权范围，避免反复确认常规步骤。

注意：磁盘上的子项目 `AGENTS.md` 仍写有 `gpt-5.6-terra` 子代理偏好，这是旧文字，与用户最新消息冲突时采用本节记录的最新要求。此交接没有修改该文件。

## 4. 产品目标与阶段边界

用户最新明确的终极目标：**Agent 通过机械臂配备的摄像头感知外界物理环境，识别人类手势，将其转换为明确指令，并控制机械臂完成相应操作。**

核心流程：摄像头画面 → 手势与环境识别 → 操作意图 → 机械臂状态及动作范围检查 → 执行动作 → 观察实际结果。

目标演变是：最小 ReAct 编程 Agent → 参考 RAI → 对标 GRID 全平台 → 收敛为摄像头手势控制机械臂。最后一项为用户最新决定。RAI、GRID 仅作为技术参考；多机器人、多用户、云集群、强化学习平台不再是最终验收的必需项，只有后续明确需要时再加入。

README 与 AGENTS 目前仍保留旧 GRID 全平台目标，与本节冲突时以用户最新目标为准。本次只更新交接文件，未同步修改那两个文件。README 旧基线核查日期为 2026-09-17；原开发对话于 2026-09-25 联网读取的官方文档索引已包含 v2.1，而 README 仍写 v2.0。以后采用具体接口或组件时重新核查，不把旧文档当作服务可用性保证。

已有参考入口：GRID 文档 `https://docs.generalrobotics.dev/`、索引 `https://docs.generalrobotics.dev/llms.txt`、架构说明 `https://www.generalrobotics.company/post/agentic-robotics`；公开仓库 `GenRobo/GRID-playground`、`GenRobo/isaac-sim-mcp`、`GenRobo/DreamControl`。

历史文档记录：GRID-playground 使用 RAIL-S、DreamControl 限制非商业研究/评估；isaac-sim-mcp 仓库说明标注 MIT。引用或集成前按当时实际许可证核查。示例仓库、客户端 SDK 和连接组件不代表完整平台后台开源。官方服务账户和 Cortex 密钥不能由 DeepSeek 密钥替代。

| 阶段 | 当前定位与目标 |
| --- | --- |
| V0.2 | 已有基础：ReAct、文件工具、权限模式、受限检查 |
| V0.3 | 已实现：显式 TOML、技能契约、公开计划、结果报告、本地 stdio MCP |
| V0.4 | 当前实现：默认关闭的持久记忆、用户管理和真实验证的组合配方 |
| V0.5 | 摄像头与少量固定手势识别；显示结果，处理连续帧、遮挡和不确定结果；不确定时不产生动作 |
| V0.6 | 手势到动作映射、人工确认、重复触发抑制、模拟机械臂；持续手势不能反复触发 |
| V0.7 | 一个真实机械臂适配器、状态读取、速度和活动范围限制、停止机制；受控执行预设动作，断连或异常时停止 |
| V0.8 | 工作台、物体与障碍物感知，相机与机械臂坐标标定；将视觉目标转换为可用位置并完成一个操作 |
| V0.9 | 动作后观察、成功判断、停止提示或有限重试；发送指令成功不能等同操作成功 |
| V1.0 | 在约定光照、距离和工作空间内，重复验收完整的手势识别与机械臂操作流程 |

版本编号不是发布日期。尚未实现机器人控制、视觉服务、GPU 仿真、训练平台、真机部署或多用户平台。迁移请求本身没有授权自动开始 V0.5。先恢复环境并核实 V0.4，再根据用户后续任务继续。

上述 V0.5—V1.0 是原开发对话基于最新目标给出的建议路线，尚未实现，也没有最终确定手势集合、动作映射、性能指标或硬件选型。第一个建议演示是“约定手势 → 识别 → 用户确认 → 机械臂移动到预设位置或夹爪开合 → 结果反馈”，之后再考虑指向物体并抓取。

建议职责：大模型理解任务、组合动作和解释结果；专门的视觉模块负责手势检测，机械臂控制器负责关节控制，独立机制负责停止。不要让模型输出直接绕过本地动作校验。

硬件信息待用户提供：机械臂品牌型号及控制接口、摄像头型号、摄像头位于机械臂末端还是固定支架。用户尚未确认是否有深度相机、控制 SDK、ROS 2 支持或 GPU，不得自行假定。开发环境从 Windows/Python 起步，是否引入 WSL/Linux、ROS 2 或特定仿真器须按实际设备决定。

## 5. 当前实现与代码地图

主要数据流：用户输入 → 对话历史 → 模型 + 工具 Schema → 本地权限/参数校验 → 工具执行 → 工具结果加入历史 → 再次调用模型或返回回答。

| 相对子项目路径 | 核心职责 |
| --- | --- |
| `src/mini_agent/__main__.py`、`cli.py` | 入口、CLI 参数、配置选择、交互命令、MCP 会话与状态管理 |
| `config.py` | 配置校验，命令行 > 显式 TOML > 默认值 |
| `agent.py` | `ReactAgent`、串行工具循环、计划、`last_turn`、记忆工具注册 |
| `llm.py` | DeepSeek OpenAI-compatible Chat Completions 适配 |
| `models.py` | `ToolCall`、`ModelResponse`、`ToolResult`、`ToolExecution`、`TurnReport`、`ModelClient` Protocol |
| `prompts.py` | 行为约束；不能代替本地强制校验 |
| `skills.py` | `SkillSpec`：名称、描述、参数、返回、权限、超时、版本、示例、来源 |
| `planning.py` | `PlanStep`、`update_plan`，仅公开内存计划 |
| `tools/base.py`、`tools/registry.py` | 工具契约、注册、Schema 校验、模式过滤、执行与输出限制 |
| `tools/filesystem.py`、`tools/search.py` | 六个基础工具中的文件/搜索实现 |
| `tools/paths.py` | 统一工作目录、敏感文件、链接与 Windows 路径策略 |
| `tools/command.py` | 完整命令白名单、当前解释器、超时、输出限制、进程清理 |
| `mcp.py`、`mcp_demo.py` | 受信任本地 stdio MCP 客户端及演示服务 |
| `memory.py` | 用户显式保存的经验/任务摘要及检索清理 |
| `recipes.py` | 配方管理、真实执行验证、工作区指纹与失效策略 |
| `v04_tools.py` | `search_memory`、`list_recipes`、`run_recipe` |
| `events.py` | 可选 JSONL 元数据日志，不记录正文、完整参数或推理 |

### 核心循环与证据语义

- `run_turn()` 的一个 step 是一次模型调用，单次响应可能提出多个工具；本地顺序执行。
- `messages` 保留 system/user/assistant/tool，工具结果通过 `tool_call_id` 与调用关联。
- 模型不再提出工具调用时返回回答；达到步数、连续工具错误上限或中断时停止。
- 默认 `max_steps=20`、`max_consecutive_errors=3`、工具输出限制 20,000 字符；成功工具会重置连续错误计数。
- 中止批量调用时为未执行项补 cancelled 结果，保持消息协议完整。
- V0.3 已添加 `TurnReport`。`final_response`、`stop_reason`、`executed_success` 是不同概念；排除 `update_plan` 后，必须至少有一个实际工具且所有实际工具成功，`executed_success` 才为真。
- 即便所有工具成功，也不等于用户目标已独立验收；公开计划状态同样由模型提交，不是自动证明。
- 每个新任务重置公开计划；对话历史仍保留。`/clear` 重置对话、计划和上一轮报告，不删除显式持久记忆。
- `ModelClient` Protocol 支持假模型测试或新模型适配。运行模型默认字符串为 `deepseek-v4-flash`，base URL 为 `https://api.deepseek.com`；这只是当前代码默认值，不是当前服务可用性保证。

### V0.3 技能、配置与 MCP

- 不自动读取工作目录配置；必须指定 `--config`。TOML 相对 workspace 以 TOML 所在目录为基准。
- 配置拒绝未知/错误字段和秘密字段；只通过环境变量读取模型密钥。
- `--list-skills` 离线列出内置技能，不连接模型或 MCP；会话 `/skills` 可包含已经连接的外部技能。
- 自定义可信本地 `Tool` 经 `additional_tools` 注入，不通过配置动态导入任意 Python。
- 外部工具权限采信本地 `tool_permissions`，不采信服务器 annotations 授予新权限。
- MCP 支持本地 stdio 的 initialize/initialized、tools/list、tools/call；不支持 HTTP、OAuth、resources、prompts。
- 启动 MCP 进程是对该程序的信任；技能权限过滤不是进程沙箱。普通进程内 Python 技能的超时 metadata 不等于可强制中断。

### V0.4 记忆与配方

- 默认 `memory_enabled=false`；只有 `--memory` 或显式 TOML 开启后才构造状态存储。
- 状态位于用户 workspace 的 `.mini-agent/memory.json` 和 `.mini-agent/recipes.json`；这是运行时 Agent 状态，不是 Codex 对话历史。
- 不自动保存用户提示、模型回答、源码、完整工具参数或密钥。`/save-task TEXT` 保存用户提供摘要及受限上一轮执行元数据。
- 记忆工具返回不可信历史资料，不提升为 system 指令，不能改变权限。
- 配方由用户 CLI 创建、验证、清理；模型只能检索/列出，并在 run 模式运行已验证配方。
- 配方最多 8 步，只允许 `read_file`、`list_files`、`search_text`、`run_command`。真实验证要求至少一次成功 `run_command`，不能仅凭模型声称通过。
- 工作目录内容指纹变化使配方失效，需重新验证。扫描上限 1,000 文件和 2 MB，排除受保护路径、缓存及 `.mini-agent`。
- 状态 JSON 面向本地单会话，没有多进程锁、共享同步或多用户保证。
- 当前记忆检索采用大小写归一化后的文本/词项匹配，不是向量或语义检索；配方验证只证明规定检查曾执行成功，不证明任意任务的语义正确性。

## 6. 必须保持的开发与访问约束

- 默认修改范围为 `mini-react-agent/`；未明确扩大范围不要修改上层 RAI。
- 子项目独立运行，不需要 ROS 2、colcon、RAI `setup_shell.sh`。只有实际开发/运行 RAI 包时才遵循外层 ROS 环境规范。
- 文档用中文，小补丁，先读相关实现和测试；公共接口用类型标注，内部数据优先 dataclass。
- `read` 仅读取/检索；`edit` 加创建修改；`run` 再加受限执行。默认 edit，不是默认 read。
- 每次访问目标都校验工作目录边界；拒绝敏感文件、链接、受保护目录和路径别名绕过。
- `write_file` 默认拒绝覆盖，但支持显式 `overwrite=true`；`apply_patch` 是唯一匹配的精确旧文本替换，不是任意 unified diff 解析器。
- 不提供递归删除、不受限制 Shell、包安装或任意脚本执行工具。
- `run_command` 使用参数数组、`shell=False`，允许受限的 pytest、compileall、Ruff check，校验完整参数。不允许 `python -c`、直接 `python hello.py` 或 pip。
- 子进程不传递模型 API 密钥；pytest 会执行代码，run 模式不是操作系统级沙箱。
- 未明确授权不安装软件、访问网络、改变系统配置或启动后台服务；新设备依赖安装需要在用户已授权的环境准备范围内进行。
- 新机器人/仿真/模型服务使用独立适配与权限，不以放宽命令白名单实现。未来真机必须有动作限幅、超时、急停与人工批准。
- 每个工具调用必须有结果，包括取消项；日志只记有上限的元数据。
- 单元测试使用假模型，不调用付费 API；测试文件用临时目录，不操作用户真实数据。
- 改行为时增加相关测试，运行针对性及环境允许的完整测试；只把实际成功的检查报告为通过。提交采用 Conventional Commits。

## 7. 迁移时要复制什么

推荐保留整个 `rai-main` 项目目录，尤其 `mini-react-agent/` 的源码、测试、README、AGENTS、CHANGELOG、`pyproject.toml`、示例配置、本文件和隐藏 `.git/`。若只继续独立 My-Agent，可只复制完整 `mini-react-agent/`；RAI 参考代码可后续另行获取。

新设备重新创建虚拟环境；不要依赖复制来的 `.venv`。缓存和 `.pytest-*`、`.test-runs*` 不需要迁移。

下面内容被 `.gitignore` 忽略，单靠 Git 不会迁移：`mini-agent.toml`、`workspace/`、`.mini-agent/`、`.env*`、虚拟环境和测试缓存。若需保留自定义配置、练习代码或经验/配方，单独选择复制对应内容；原文件未被本交接读取。密钥在新设备重新配置，不写入本文件或版本库。

保留 `.git/` 才能保留提交历史；本交接没有创建提交、推送远端或打迁移包。Codex 的另一个对话全文、全局设置、skills、plugins 和登录状态不属于本项目源码，不能指望复制代码自动带过去。

本机 Git 出现所有权检查时，整理采用命令级 `git -c safe.directory=D:/Project/rai-main/mini-react-agent -C mini-react-agent ...` 读取，没有修改全局 Git 配置。新设备按实际可信目录处理，不复制旧绝对路径设置。

## 8. 新设备恢复步骤与命令

在新设备的 `mini-react-agent` 目录执行。以下是待执行步骤，不能当作已验证成功记录：

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -q -c pyproject.toml
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mini_agent --help
.\.venv\Scripts\python.exe -m mini_agent --list-skills
```

Linux 使用 `.venv/bin/python` 对应替换上述解释器路径。这些依赖没有精确锁定到同一版本，迁移后应记录实际 Python/依赖版本与检查结果。

只在需要配置时使用示例：

```powershell
# 若已有自己的 mini-agent.toml，先检查，不要覆盖。
Copy-Item .\mini-agent.example.toml .\mini-agent.toml
New-Item -ItemType Directory -Force .\workspace
.\.venv\Scripts\python.exe -m mini_agent --config .\mini-agent.toml --list-skills
```

示例配置包含本地 `mcp_demo` 启动项。离线列技能不会启动它；正常交互使用该配置时可能启动，先确认本地启动项可信。更改 workspace 和其他路径为新设备实际位置。

真实调用前，重新设置环境变量 `DEEPSEEK_API_KEY`，先确认账户、模型、网络和付费调用授权。不要在终端输出密钥或把真实值写进命令历史/文档。

常用入口与命令：

- 启动：`python -m mini_agent --workspace <已有目录> --mode read|edit|run`。
- 配置：`--config <TOML>`；记忆：`--memory` / `--no-memory`；计划显示：`--show-plan` / `--no-show-plan`。
- 会话：`/help`、`/clear`、`/exit`、`/plan`、`/skills`、`/result`。
- 记忆：`/remember TEXT`、`/memory [query]`、`/forget ID`、`/save-task TEXT`。
- 配方：`/recipe-create NAME JSON_STEPS`、`/recipes`、`/recipe-verify NAME`、`/recipe-run NAME`、`/recipe-forget NAME`。

在新工作目录中重新验证配方，不把从旧设备复制的验证标记视为新环境验收。

## 9. 验证记录与待处理项

本次成功核实：版本文件、目录结构、核心源码、README/CHANGELOG/AGENTS、Git 提交历史及写交接前的 tracked 工作树状态。

2026-09-26 尝试执行以下现有虚拟环境命令，均在启动解释器时失败，并没有真正运行测试或 Ruff：

```text
.venv\Scripts\python.exe -m pytest -q -c pyproject.toml
.venv\Scripts\python.exe -m ruff check .
Unable to create process using ...Python312\python.exe
```

现有 `.venv` 引用了原用户目录中的基础 Python，当前执行环境无法启动；不能据此判定源码有测试失败，也不能报告测试通过。这进一步说明迁移后必须重建环境。

历史 README 称此前离线测试通过，但本次没有取得对应历史执行输出。真实 DeepSeek、真实外部 MCP 服务及机器人环境均未在本次验收。不得补写通过数量、服务可用性或性能结果。

已有测试模块涵盖：agent、CLI、config、LLM、events、registry、skills、paths、filesystem、search、command、MCP、V0.3 agent/CLI、memory、recipes、V0.4 integration。重新安装后运行整个子项目 tests。

当前已知边界：累计对话历史尚无上下文压缩/token 预算；工具串行执行；没有独立用户目标验收器；没有完整聊天恢复；本地状态无并发保证；普通进程内技能超时不能强制停止；MCP 仅本地 stdio 子集。V0.4 经验/配方能力不等于完整机器人技能学习平台。

新设备最先处理：核对目录/HEAD → 重建环境 → 离线测试与 Ruff → 离线 CLI 检查 → 核查本地配置/状态迁移 → 在授权后做真实模型验证。再与用户确定下一阶段具体范围。

## 10. 给新设备 Codex 的启动提示词

将下面内容发送给新设备 Codex：

> 请完整阅读项目 `mini-react-agent/CODEX_HANDOFF.md`，再读取 `mini-react-agent/AGENTS.md`、`README.md`、`CHANGELOG.md` 和 `pyproject.toml`；如果已经打开子项目根目录，使用对应相对路径。以当前 V0.4.0 源码为准，遵循交接文件记录的用户最新模型与委派偏好，不沿用旧 gpt-5.6-terra 文字。最新目标是摄像头感知环境、识别手势并控制机械臂，README/AGENTS 中全面对标 GRID 的目标已经过时。先核实迁移后的路径、Git 状态和环境；该独立项目无需 ROS 2。按现有授权准备环境并运行离线测试、Ruff 和 CLI 检查，报告真实结果，不调用付费 API 或自动推进 V0.5。允许用户手动输入、确认和参与配置。ChatGPT 联通是可选开发辅助，不是启动 My-Agent 的前提；旧设备连接不保证迁移后有效。硬件信息尚缺，遇到无法确认的决定需明确指出，不要编造历史。

## 11. 原开发对话补充：协作方式、连接与待办

### 用户偏好与历史验收

- 用户是软件新手，原设备已安装 Python 3.12；新设备的 Python 和系统情况仍需检查。解释应使用中文，并提供可执行的分步操作。
- 用户要求决策与推理由主代理的当前选定模型负责，适合委派的代码实现由子代理完成；具体最新模型偏好见第 3 节。这是 Codex 开发分工，不代表 My-Agent 当前已实现多个模型或运行时子代理调度。
- 用户明确说“不必实现完全的全自动，有些输入内容等操作可以交给我来”。可以让用户在 ChatGPT 输入任务、复制交接摘要、完成登录配置或确认动作，无需为了减少手动输入而扩大工程范围。
- 用户曾明确反馈“V0.3 测试已完成，无误”；没有提供完整测试输出。V0.4 已开发并给过测试方案，但本对话没有同等明确的用户 V0.4 验收反馈，不能把 V0.3 的反馈移作 V0.4 验收。
- 最初运行截图表明 Agent 创建了 `hello.py`，但因命令执行禁用而未能运行。这是早期记录；当前 V0.4 的命令白名单本来也不支持直接运行 `python hello.py`，不能通过简单启用 run 模式承诺能运行任意脚本。
- 版本开发沿用独立分支习惯，如 `feat/v0.4`；尚未创建 V0.5 分支。升级计划与目标更正本身没有实现新版本。

### ChatGPT「Codex联通」连接记录

2026-09-23，用户要求把本项目接入现有 ChatGPT 项目「Codex联通」。当日通过原设备上的 `codex-with-chatgpt` 技能完成配置，并做了实际文件读取验证。

- ChatGPT 项目：`https://chatgpt.com/g/g-p-6ab3c6ed61ac8191b6bccc254ea446cd/project`。
- 已验证对话：`https://chatgpt.com/g/g-p-6ab3c6ed61ac8191b6bccc254ea446cd-codexlian-tong/c/6ab3d38a-a114-83e9-8a6c-6c76d932efbf`。
- 连接器名称：`Codex with ChatGPT · mini-react-agent`；当时工作区标识：`c078fdbb556f`。
- 已验证：工作区为 `mini-react-agent`；ChatGPT 实际读取 `README.md` 第一行 `# My-Agent · 最小 ReAct 编程智能体 V0.4`，以及 `pyproject.toml` 的 `version = "0.4.0"`；已保存验证后的对话入口。原设备当日连接健康检查通过。
- 已知问题：连接器的 `workspace_info` 和 `git_status` 返回 `isRepo: false`，而本地 Git 确认存在仓库及 `feat/v0.4` 分支。原因没有查明；不能把连接器输出当作仓库不存在，也不能声称 Git 审查链路已验证。
- 2026-09-26 本次本地 Git 默认调用又出现所有权检查错误，使用仅当前命令生效的 `safe.directory` 后可读取。它是可供排查的线索，尚不能证明是原连接器误报的根因；没有更改全局 Git 设置。
- 当日使用临时公网连接地址，用户未提供 Cloudflare 账户/域名。地址与旧设备后台进程相关，重启或迁移可能失效。本文件不复制临时配对码、访问令牌或旧公网入口。
- ChatGPT 项目当时已设置仅限项目记忆，并加入只使用对应工作区连接器的协作说明。该状态是历史验证，不是对新设备或当前在线状态的保证。

这条连接用于开发期间的规划和评审；My-Agent 自身仍通过配置的 DeepSeek API 运行，两者独立。它也不同于源码中的本地 stdio MCP 客户端，不能因此宣称 My-Agent 已支持 OAuth/远端 HTTP MCP。

迁移后可保留相同 ChatGPT 项目，但原设备的技能、桥接程序、连接器会话、登录与后台进程不会随 Git 仓库自动迁移。先检查新设备是否有相应技能和工具，再按实际环境恢复，并重新验证它读取的是新设备项目文件。不要依赖原设备绝对路径或同时维护指向不同设备却无法区分的连接。若暂不恢复，用户可以手动在 ChatGPT 与 Codex 之间传递需求和审查摘要，照常开发。

### 新设备后续顺序与本次文件状态

1. 按第 8、9 节恢复 V0.4 环境并记录真实检查结果。
2. 后续维护文档时，将 README/AGENTS 的旧产品目标和 AGENTS 的旧子代理模型偏好同步为本文件记录的最新决定。
3. 如需使用 ChatGPT 联通，恢复连接并分别验证文件读取与 Git 状态；它不阻塞本地 Agent 开发。
4. 获取机械臂、摄像头及安装位置资料，然后细化 V0.5 的手势集合、识别模块、测试素材和验收标准；不要自行采购或接入真机。

本次补充只修改 `CODEX_HANDOFF.md`，保留原交接中的源码说明和环境失败记录；未修改程序、创建分支、提交或推送。补充前本地 Git 显示该文件为未跟踪文件 `?? CODEX_HANDOFF.md`。因此，仅在新设备克隆现有远端仓库不会自动获得本文件：迁移时需直接复制本文件，或后续在用户授权的提交/推送流程中将其纳入版本库。
