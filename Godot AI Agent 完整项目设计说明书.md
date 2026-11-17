# Godot AI Agent 完整项目设计说明书

**文档编号：** DOC-01-001  
**版本：** V1.0  
**文档状态：** DRAFT（初稿）  
**文档类型：** 项目总体设计说明书  
**项目名称：** Godot AI Agent  
**适用对象：** 产品规划、系统架构、软件开发、测试、项目管理和维护人员

---

# 第一章 项目概述

## 1.1 项目背景

Godot 是一款开源游戏引擎，支持 2D、3D 游戏开发，并提供场景编辑器、节点系统、资源管理、脚本系统、动画系统、物理系统和项目导出能力。

传统游戏开发需要开发人员手动完成大量工作：

- 游戏需求分析和设计。
- 游戏架构和模块规划。
- GDScript 编写。
- Scene 和 Node 创建。
- Inspector 属性配置。
- Signal 和 Group 配置。
- 游戏资源制作和导入。
- UI、动画、音效和特效制作。
- 游戏运行、调试和缺陷修复。
- 测试、构建和发布。

虽然现有 AI 编程工具可以帮助开发人员生成代码，但通常缺乏完整的 Godot 项目理解能力、编辑器操作能力、游戏开发流程管理能力和完整测试能力。

本项目计划开发一套专门面向 Godot 的 AI Agent 游戏开发系统。

系统不只是一个代码生成工具，而是一个能够理解 Godot 项目、规划游戏开发任务、调用 AI 模型、操作 Godot 编辑器、生产游戏资源、执行测试并管理完整开发流程的智能游戏开发平台。

## 1.2 项目核心目标

建立一套完整的 Godot AI Agent 系统，使用户能够：

1. 让 AI 理解已有 Godot 项目。
2. 通过自然语言提出游戏开发需求。
3. 自动分析需求并制定开发计划。
4. 调用不同专业 Agent 完成游戏开发任务。
5. 通过 Godot Editor Bridge 操作真实 Godot 编辑器。
6. 通过文件工具和 Godot 工具创建、修改项目内容。
7. 生成和管理游戏图片、音效、动画等资产。
8. 运行游戏并进行调试。
9. 自动执行测试并分析问题。
10. 通过审批和阶段验收控制开发过程。
11. 最终完成游戏构建、导出和交付。

## 1.3 产品定位

产品定位为：

**面向 Godot 的完整 AI 游戏开发 Agent 平台。**

系统由以下主要部分组成：

- Godot Editor Plugin：提供 Godot 编辑器内的操作入口。
- Local Backend：负责整个系统的业务运行、数据管理和任务调度。
- AI Agent System：负责理解、规划和执行专业开发任务。
- Model Gateway：统一管理不同 AI 模型和 Provider。
- Tool System：统一管理所有工具调用和项目操作。
- Godot Integration：负责与 Godot Editor、Runtime 和 CLI 通信。
- Asset System：负责游戏资源生成、处理、管理和导入。
- Project Intelligence：负责理解项目结构、代码和资源关系。
- Verification System：负责测试、验证、缺陷和验收。
- Workflow System：负责管理完整开发流程。

## 1.4 产品工作模式

系统支持两种主要工作模式。

### 模式 A：Development Assistant（开发辅助模式）

用户自己负责主要开发决策，AI 辅助完成具体工作。

典型使用方式：

1. 用户打开 Godot 项目。
2. 用户向 AI 描述开发需求。
3. AI 分析当前项目。
4. AI 提供实现方案。
5. 用户确认方案。
6. AI 创建 Task 并安排专业 Agent。
7. Agent 通过工具完成开发工作。
8. 系统生成变更记录。
9. 用户审批变更。
10. 系统执行测试。
11. AI 提交结果和验证报告。

该模式强调用户主导、AI 辅助。

### 模式 B：Autonomous Game Development（自主游戏开发模式）

用户提供一个完整游戏目标，系统自动规划并分阶段开发。

典型使用方式：

1. 用户描述游戏创意。
2. AI 分析游戏需求。
3. 系统识别缺失信息并向用户询问。
4. 系统生成游戏设计方案。
5. 系统制定完整开发计划。
6. 用户确认项目方案。
7. 系统开始执行第一阶段。
8. 多个专业 Agent 按照任务依赖协作。
9. 系统完成开发、资产制作和测试。
10. 系统生成阶段报告。
11. 用户验收当前阶段。
12. 用户决定继续、修改计划、暂停或终止。
13. 所有阶段完成后进行最终测试和构建交付。

该模式强调 AI 主导执行，但用户始终保留关键决策和审批权。

**重要原则：自主开发不代表 AI 拥有无限制的项目修改权限。**

## 1.5 项目支持范围

| 项目能力 | 第一阶段定位 |
|---|---|
| Godot 2D 游戏开发 | P0，优先实现 |
| Godot 3D 游戏开发 | 架构支持，后续扩展 |
| GDScript 开发 | 核心能力 |
| Scene / Node 操作 | 核心能力 |
| Inspector 属性配置 | 核心能力 |
| Signal / Group 配置 | 核心能力 |
| TileMapLayer 操作 | 核心能力 |
| Animation 操作 | 核心能力 |
| UI 开发 | 核心能力 |
| 图片生成 | P0 |
| 音效生成 | P0 |
| 背景音乐生成 | P1 |
| 复杂 3D 资产生成 | P2 |
| 游戏运行与调试 | 核心能力 |
| 自动测试 | 核心能力 |
| 桌面平台导出 | 核心交付能力 |

---

# 第二章 项目总体功能规划

## 2.1 功能中心总览

系统划分为十个主要功能中心。

### 1. Project Intelligence（项目智能理解）

负责分析、理解和维护 Godot 项目的知识模型。

主要功能：

- 项目结构扫描。
- Godot 项目配置分析。
- GDScript 分析。
- Scene 文件分析。
- Node 层级分析。
- Resource 分析。
- UID 和资源引用分析。
- Signal 和 Group 关系分析。
- 游戏系统识别。
- 代码依赖关系分析。
- 资源依赖关系分析。
- 项目知识图谱。
- 影响范围分析。
- 项目变化检测。
- 项目知识更新。

### 2. Game Development（游戏开发）

负责游戏设计、程序开发、场景制作和游戏系统实现。

主要功能：

- 游戏需求分析。
- 游戏设计文档生成。
- 游戏系统设计。
- 游戏架构设计。
- Gameplay 开发。
- 玩家控制系统。
- 敌人 AI。
- 战斗系统。
- UI 系统。
- 关卡设计。
- 场景开发。
- 数据存储系统。
- 游戏交互系统。
- 动画和表现系统。
- 游戏平衡设计。
- 代码优化和重构。

### 3. Asset & Content（资源和内容生产）

负责游戏资产的生成、处理、管理和集成。

主要功能：

- 资源需求分析。
- 图片生成。
- 图片变体生成。
- Sprite Sheet 生成和切帧。
- 图像格式转换。
- 图像尺寸处理。
- 音效生成。
- 背景音乐生成。
- 动画资源制作。
- VFX 资源制作。
- 资源质量检查。
- 资源来源记录。
- 许可证管理。
- 资源版本管理。
- Godot 资源导入。
- 资源替换和引用检查。

### 4. QA & Debugging（质量保证与调试）

负责项目测试、缺陷识别和质量验证。

主要功能：

- GDScript 静态检查。
- Scene 结构检查。
- Resource 引用检查。
- Godot 导入检查。
- 游戏运行测试。
- 自动化测试。
- Runtime Debugging。
- 错误日志分析。
- 性能分析。
- Bug 定位。
- Bug 修复建议。
- 回归测试。
- 阶段验收。
- 最终质量报告。

### 5. Project Management（项目管理）

负责游戏项目和开发任务的组织管理。

主要功能：

- 项目创建和管理。
- 游戏需求管理。
- 项目计划管理。
- Task 管理。
- Task 依赖管理。
- Workflow 管理。
- 开发阶段管理。
- 任务分配。
- 任务优先级。
- 任务进度。
- ChangeSet 管理。
- 用户审批。
- 阶段验收。
- 项目报告。
- 项目历史记录。

### 6. Knowledge & Memory（知识和上下文）

负责项目知识、任务上下文和 Agent 工作上下文。

主要功能：

- Project Knowledge。
- Task Shared Context。
- Agent Private Context。
- 项目知识检索。
- 历史任务检索。
- 决策记录。
- 设计文档检索。
- 代码上下文检索。
- 资源上下文检索。
- Context Package。
- Context Budget。
- Context Revision。
- 冲突检测。
- 知识可信度管理。

### 7. AI & Agent Platform（AI 与 Agent 平台）

负责 AI 模型调用和专业 Agent 运行。

主要功能：

- Agent Registry。
- Agent Definition。
- Agent Runtime。
- Agent Instance。
- Agent Orchestration。
- Agent Handoff。
- Multi-Agent Collaboration。
- Capability Registry。
- Skill Registry。
- Context Management。
- Model Gateway。
- Model Router。
- Provider 管理。
- Token 和 Cost 管理。
- 模型健康检查。
- 模型回退策略。

### 8. Godot Integration（Godot 集成）

负责真实 Godot 环境中的操作和状态同步。

主要功能：

- Godot Editor Plugin。
- Godot Editor Bridge。
- Godot Runtime Bridge。
- Godot CLI Runner。
- Editor Session 管理。
- Runtime Session 管理。
- Scene 操作。
- Node 操作。
- Inspector 操作。
- Signal 操作。
- Group 操作。
- Resource 操作。
- Animation 操作。
- TileMap 操作。
- 游戏运行与停止。
- Debugger 操作。
- 项目状态同步。
- Godot 版本和能力检测。

### 9. Tool Platform（工具平台）

负责统一管理 AI 能够使用的所有操作工具。

主要功能：

- Tool Registry。
- Tool Definition。
- Tool Implementation。
- Tool Permission。
- Tool Execution Engine。
- Python Tool Adapter。
- Godot Editor Adapter。
- Godot Runtime Adapter。
- CLI / Process Adapter。
- External Service Adapter。
- Knowledge / Analysis Adapter。
- Tool Execution History。
- Tool Result Validation。
- Resource Lock。
- Tool Recovery。

### 10. Build & Delivery（构建与交付）

负责游戏构建、导出和最终交付。

主要功能：

- Godot Project Validation。
- Resource Import Validation。
- Build Configuration。
- Export Preset 管理。
- Godot Export。
- Artifact Management。
- Build History。
- Release Package。
- Delivery Report。
- 安装和升级。
- 发布前质量门禁。

---

# 第三章 系统总体架构

## 3.1 架构设计原则

系统遵循以下原则：

1. 模块化设计。
2. 单一状态所有权。
3. 模块间通过公开接口通信。
4. 禁止跨模块直接访问 Repository。
5. 禁止循环依赖。
6. 所有项目操作统一通过 Tool System。
7. 所有写入操作受权限、审批和变更管理约束。
8. Agent 不直接调用 AI Provider API。
9. Godot Editor 状态必须来自真实 Editor。
10. 文件系统、Editor 和 Runtime 状态必须分别管理。
11. 任务、工作流、Agent 和验证状态独立管理。
12. 关键操作需要可追踪、可恢复和可验证。
13. 默认本地优先。
14. 支持多个 Godot 项目和多个 Editor 实例。
15. 不允许未经验证的结果被标记为成功。

## 3.2 八层系统架构

系统采用八层逻辑架构。

### 第一层：用户交互层

负责用户与系统之间的交互。

包括：

- Godot Editor Plugin UI。
- AI Assistant Panel。
- Chat Interface。
- Task Dashboard。
- Workflow Dashboard。
- Agent Monitoring。
- Approval Interface。
- Project Overview。
- Asset Browser。
- QA Dashboard。
- Settings Interface。

### 第二层：应用协调层

负责组织和协调业务操作。

包括：

- Application Controller。
- Project Manager。
- Task System。
- Workflow Engine。
- Orchestrator。
- Approval System。
- ChangeSet Manager。
- Phase Manager。
- Recovery Coordinator。

### 第三层：Agent 执行层

负责运行专业 Agent。

包括：

- Agent Registry。
- Agent Definition Manager。
- Agent Runtime。
- Agent Instance Manager。
- Agent Scheduler。
- Multi-Agent Collaboration。
- Handoff Manager。
- Agent Context Manager。
- Agent Execution Monitor。

### 第四层：AI 服务层

负责模型调用和 AI 能力管理。

包括：

- Model Gateway。
- Model Router。
- Provider Manager。
- Model Capability Registry。
- Text & Tool Service。
- Multimodal Service。
- Token & Cost Manager。
- Model Health Monitor。
- Model Evaluation。

### 第五层：领域业务层

负责项目的核心业务能力。

包括：

- Project Intelligence。
- Context System。
- Game Development。
- Asset Management。
- Asset Generation。
- QA & Verification。
- Build & Release。
- Knowledge Management。

### 第六层：工具执行层

负责统一执行所有操作。

包括：

- Tool Registry。
- Tool Execution Engine。
- Permission Enforcement。
- Python Tool Adapter。
- Godot Editor Adapter。
- Godot Runtime Adapter。
- CLI Adapter。
- External Service Adapter。
- Knowledge Adapter。

### 第七层：Godot 集成层

负责连接真实 Godot 环境。

包括：

- Godot Editor Plugin。
- Editor Bridge。
- Runtime Bridge。
- CLI Runner。
- Filesystem Adapter。
- Version Adapter。
- Capability Detector。
- Project State Synchronization。

### 第八层：Backend 基础设施层

负责系统底层运行和数据管理。

包括：

- Backend Process。
- Lifecycle Manager。
- Module Interface Registry。
- Service Container。
- SQLite Database。
- Repository Layer。
- Event System。
- Internal Message Bus。
- Outbox Dispatcher。
- Artifact Storage。
- Configuration Manager。
- Secrets Manager。
- Security Policy Engine。
- Logging。
- Metrics。
- Tracing。

## 3.3 系统部署结构

系统第一阶段采用 Desktop Local 部署方式。

主要组成：

1. Godot Editor Plugin。
2. Local Backend。
3. SQLite Primary Database。
4. Project Intelligence Index。
5. Artifact Storage。
6. Godot Editor Bridge。
7. Godot Runtime Bridge。
8. Godot CLI Runner。
9. External AI Providers。

Backend 采用单进程模块化架构。模块在逻辑上独立，通过受控接口通信，第一阶段不拆分为多个微服务。

一个 Backend 可以服务多个 Godot 项目和多个 Editor 实例。

每个项目独立管理：

- Project Identity。
- Project Knowledge。
- Project Configuration。
- Project Task。
- Project Workflow。
- Project Agent Context。
- Project ChangeSet。
- Project Resource Lock。
- Project Approval。
- Project Asset Registry。

不同项目之间不得未经授权共享项目数据、上下文和写入权限。

## 3.4 进程与会话关系

系统严格区分：

- Backend Process。
- Editor Instance。
- Editor Session。
- Runtime Process。
- Runtime Session。
- Probe Connection。

Backend 的生命周期不依赖 Godot Editor。

Godot Editor 关闭或插件卸载，不会自动关闭 Backend。

不依赖 Editor 的后台任务可以继续执行；依赖 Editor 的任务暂停并等待重新连接。

Backend 负责自己的启动、健康检查、恢复和受控关闭。

## 3.5 核心业务调用链

用户请求进入系统后，典型调用路径如下：

1. 用户通过 Godot Plugin 提交需求。
2. Application Controller 接收请求。
3. Project Manager 确定目标项目。
4. Project Intelligence 提供项目理解结果。
5. Task System 创建 Task。
6. Workflow Engine 根据需求组织执行流程。
7. Orchestrator 选择合适的 Agent。
8. Agent Runtime 启动 Agent Instance。
9. Agent 请求 Context System 组织上下文。
10. Agent 通过 Model Gateway 调用模型。
11. Agent 需要操作项目时向 Tool System 提交 Tool Call。
12. Tool System 验证权限、风险、审批和资源锁。
13. 对应 Adapter 执行实际操作。
14. Godot Integration 与真实 Editor、Runtime 或文件系统交互。
15. Tool System 验证操作结果。
16. ChangeSet Manager 记录变更。
17. Verification System 执行测试。
18. Task System 根据执行结果和业务规则更新 Task 状态。
19. Workflow Engine 根据节点和阶段规则决定后续流程。
20. 系统向用户报告执行结果。

---

# 第四章 核心业务系统

## 4.1 Project Management System

负责管理整个游戏项目。

主要实体：

- Project。
- Project Configuration。
- Project Member。
- Project Requirement。
- Project Plan。
- Project Phase。
- Project Decision。
- Project Report。

每个项目具有独立身份和生命周期。

项目创建后，系统应当完成：

1. Godot 项目路径确认。
2. Godot 版本检测。
3. 项目结构扫描。
4. 项目配置分析。
5. Project Intelligence 初始化。
6. 项目知识建立。
7. 项目能力检测。
8. 项目状态初始化。

## 4.2 Task System

Task System 是任务状态的唯一权威。

负责：

- Task 创建。
- Task 规划。
- Task 分解。
- Task 依赖管理。
- Task 调度请求。
- Task 暂停。
- Task 恢复。
- Task 取消。
- Task 重试。
- Task Attempt 管理。
- Task 结果汇总。

Task 与 TaskAttempt 分离。

每次真正的新尝试创建新的 Attempt，保留之前的执行历史。

暂停、恢复和取消必须经过 Task System。

取消不等于自动回滚已经发生的项目变更。

## 4.3 Workflow Engine

负责管理多步骤和多阶段工作流程。

支持：

- 顺序执行。
- 并行执行。
- 条件分支。
- 失败阻断。
- 有限制的循环重试。
- 用户确认。
- 用户审批。
- 阶段验收。
- 暂停和恢复。
- 补偿流程。
- 重新规划。
- Workflow 版本管理。

Workflow Definition 和 Workflow Instance 分离。

运行中的 Instance 固定使用创建时的 Definition 版本。

Workflow 节点类型包括：

- SYSTEM。
- AGENT。
- CONTROL。
- HUMAN。

Workflow 不直接执行 Godot 操作。所有实际操作必须通过 Tool System。

## 4.4 Orchestrator

Orchestrator 是多 Agent 调度和协作的唯一协调入口。

负责：

- Agent 能力匹配。
- Agent 权限检查。
- Agent 可用性检查。
- 任务分配。
- Agent Handoff。
- 协作计划。
- 并行执行管理。
- 资源冲突处理。
- 子任务结果汇总。
- 协作失败恢复。

Agent 不允许绕过 Orchestrator 直接委派其他 Agent。

Agent 不能因为自身角色是 Lead 就自动获得项目写入权限。

## 4.5 Agent Runtime

负责专业 Agent 的实际执行。

每个 Agent Definition 包含：

- Identity。
- Role。
- Capabilities。
- Skills。
- Tools。
- Permissions。
- Model。
- Context。
- Instructions。
- Interface。
- Execution。
- Validation。

每个运行实例固定使用启动时的 Agent Definition 版本和权限快照。

Agent 执行受以下预算约束：

- Iteration Budget。
- Token Budget。
- Time Budget。
- Tool Call Budget。
- Cost Budget。
- Retry Budget。

系统使用 Checkpoint 和 Event Log 保存可恢复执行状态，但不保存模型隐藏推理过程。

## 4.6 Context System

Context System 负责组织 Agent 执行时需要的上下文。

分为三类：

1. Project Knowledge。
2. Task Shared Context。
3. Agent Private Context。

支持：

- Context Reference。
- Context Revision。
- Context Budget。
- Context Lifecycle。
- Context Conflict Resolver。
- PINNED。
- NORMAL。
- EXCLUDED。

用户固定的 Context 不得被系统静默移除。

Context 采集不代表文件读取授权，也不代表写入项目授权。

## 4.7 Project Intelligence

负责理解 Godot 项目并维护项目知识。

采用：

- 确定性 Parser。
- Godot 结构解析器。
- GDScript 分析。
- Scene 解析。
- Resource 分析。
- AI Analyzer。
- Entity & Relationship。
- Full-text Search。
- Vector Index。

确定性 Parser 提供的事实优先，AI Analyzer 的推断必须与事实分开保存。

知识实体需要记录：

- Stable ID。
- Version。
- Content Hash。
- Source。
- Confidence。
- Provenance。

项目知识索引可以重建，不作为项目原始文件的唯一存储。

---

# 第五章 AI Model 与 Provider 系统

## 5.1 Model Gateway

所有 Agent 的模型调用必须通过 Model Gateway。

Agent 不得直接调用第三方模型厂商 API。

Model Gateway 负责：

- 请求标准化。
- Provider 选择。
- Model 选择。
- Capability 检查。
- 数据授权检查。
- 请求路由。
- Token 预算。
- Cost 预算。
- 超时控制。
- 失败处理。
- Fallback。
- 结果标准化。
- 调用记录。

## 5.2 Provider、Model 和 Deployment

三者独立管理：

- Provider：模型服务提供商。
- Model：模型能力和身份。
- Deployment：实际可调用的模型部署实例。

模型能力必须经过检测和登记。

UNKNOWN 不得视为支持。

## 5.3 模型选择策略

用户明确指定模型时，优先遵循用户指定。

模型不可用时，不得静默切换到其他模型，除非已经存在明确授权的回退策略。

预算系统负责：

- Token 使用统计。
- Cost 统计。
- Budget Reservation。
- Cost Ledger。
- Provider Pricing。
- 预算预警。
- 超预算阻止。

## 5.4 多模态支持

系统架构支持：

- 文本输入输出。
- 图片输入输出。
- 音频输入输出。
- 视频输入。
- 多模态内容分析。
- 时间轴与证据关联。

具体能力由模型和 Provider 的实际 Capability 决定。

---

# 第六章 Tool System 与项目操作

## 6.1 Tool System 定位

Tool System 是所有项目操作的统一安全执行入口。

任何 Agent、Workflow 或业务模块都不能直接绕过 Tool System 修改 Godot 项目。

## 6.2 Tool 分类

工具副作用分为：

1. READ_ONLY。
2. EDITOR_STATE_MUTATION。
3. PROJECT_FILE_MUTATION。
4. RUNTIME_STATE_MUTATION。
5. PROCESS_CONTROL。
6. EXTERNAL_DATA_TRANSFER。

## 6.3 Tool 执行流程

统一执行流程：

1. 接收 Tool Request。
2. 验证 Tool Definition。
3. 验证参数。
4. 检查调用者身份。
5. 检查权限。
6. 评估操作风险。
7. 检查审批状态。
8. 检查资源锁。
9. 持久化执行意图。
10. 执行操作。
11. 检查副作用。
12. 验证操作结果。
13. 保存执行记录。
14. 发布执行事件。

## 6.4 Tool 执行状态

包括：

- ACCEPTED。
- VALIDATING。
- QUEUED。
- RUNNING。
- WAITING。
- SUCCEEDED。
- SUCCEEDED_WITH_WARNINGS。
- FAILED。
- TIMEOUT。
- CANCELLED。
- UNKNOWN。

副作用状态独立记录：

- NO_EFFECT。
- EFFECT_APPLIED。
- PARTIAL_EFFECT。
- EFFECT_UNKNOWN。

UNKNOWN 表示实际结果不确定，不允许直接盲目重试非幂等操作。

## 6.5 Python Tool Adapter

负责安全文件操作和受控脚本工具。

第一阶段禁止 Agent 直接执行任意 Python。

所有文件写入必须经过：

- 路径授权。
- 权限检查。
- 风险评估。
- 审批检查。
- Resource Lock。
- 文件哈希。
- 备份。
- 临时文件写入。
- 写入验证。
- 原子替换。
- Godot Editor 同步。
- Project Intelligence 同步。
- 审计记录。

## 6.6 Godot Tool Adapter

负责调用真实 Godot Editor 和 Runtime 能力。

主要分为：

- Godot Editor Adapter。
- Godot Runtime Adapter。
- Godot CLI Adapter。

工具能力包括 Scene、Node、Inspector、Signal、Group、Resource、Animation、TileMap、运行、停止、调试和项目导出。

直接编辑 `.tscn` 文件不能代替完整的 Godot Editor 操作能力。

---

# 第七章 Godot Integration 系统

## 7.1 Godot Editor Plugin

插件是用户进入系统的主要入口。

负责：

- UI。
- Backend Discovery。
- Backend Authentication。
- Session Management。
- Heartbeat。
- Project Binding。
- Editor State Reporting。
- Tool Request。
- Event Subscription。
- Snapshot Recovery。
- Connection Recovery。

插件卸载或 Editor 关闭，不自动关闭 Backend。

## 7.2 Editor Bridge

采用本机 WebSocket 通信。

安全措施：

- Loopback Binding。
- 随机端口。
- Challenge-Response。
- Session Token。
- 统一消息 Envelope。
- 持久事件。
- Snapshot + Event 恢复。

## 7.3 Runtime Bridge

负责连接实际运行的游戏实例。

采用 Runtime Probe 主动连接 Backend。

每个 Runtime Session 独立认证。

支持 At-least-once 消息传递、Snapshot 和 Event Recovery。

## 7.4 Godot CLI Runner

支持六种执行模式：

- EDITOR。
- STANDALONE。
- HEADLESS。
- TEST。
- IMPORT。
- BUILD。

Process Identity 和 Runtime Session 独立管理。

## 7.5 Project State Synchronization

必须分别管理：

- Disk State。
- Editor State。
- Runtime State。

对应版本：

- disk_version。
- editor_state_version。
- runtime_state_version。
- project_state_revision。

Backend 不得自行假设 Editor 当前状态。

与未保存资源相关的写入操作必须暂停或进入冲突处理。

无关资源可以在满足权限和资源锁条件时继续处理。

---

# 第八章 Asset Generation 与管理系统

## 8.1 Asset System 定位

Asset System 负责从资源需求到 Godot 集成的完整资产生产流程。

八个子系统：

1. Asset Request & Planning。
2. Asset Generation System。
3. External Provider Integration。
4. Asset Processing Pipeline。
5. Asset Registry & Version Management。
6. Asset Provenance & License Governance。
7. Godot Asset Import & Integration。
8. Asset Verification & Quality Control。

## 8.2 资产数据模型

主要实体：

- Asset。
- Asset Version。
- Asset File。
- Generation Job。
- Processing Job。
- Import Job。
- Asset Relationship。
- Asset Provenance。
- Asset License Record。

## 8.3 资产生产流程

Asset Request  
→ Asset Specification  
→ Generation Job  
→ Provider / Model Call  
→ Raw Asset Collection  
→ Processing Job  
→ Quality Validation  
→ Provenance & License Review  
→ Asset Registry  
→ Asset Version Candidate  
→ ChangeSet & Approval  
→ Godot Project Import  
→ Scene / Resource Integration  
→ Verification  
→ Accepted Asset Version。

## 8.4 资产治理规则

必须区分：

- 生成成功不代表质量合格。
- 处理成功不代表许可证合格。
- 资产登记不代表允许写入项目。
- Godot 导入成功不代表场景集成成功。
- Agent 完成不代表 Verification 通过。

License 为 UNKNOWN 或 PENDING_REVIEW 的资产不能自动进入正式交付集合。

资产更新不得静默覆盖已有引用版本。

资产删除默认支持恢复，永久清理需要单独授权。

## 8.5 资产优先级

P0：

- 2D 图片生成。
- 图片变体。
- 图片格式、尺寸和透明通道处理。
- Sprite Sheet 切帧。
- 2D 音效生成和导入。
- Asset Registry。
- 基础版本管理。
- Provenance 和 License 基础治理。
- Godot Import Pipeline。

P1：

- 背景音乐。
- 复杂动画。
- 批量变体。
- 风格一致性。
- 高级优化和质量检查。

P2：

- 视频。
- 3D 模型和材质。
- 高级骨骼动画。

---

# 第九章 Verification、QA 与交付系统

## 9.1 Verification System

Verification System 是验证结果的唯一权威。

负责：

- Requirement Traceability。
- Acceptance Criteria。
- Test Case。
- Test Execution。
- Test Environment。
- Evidence Management。
- Defect Management。
- Regression。
- Phase Review。
- Release Gate。

Agent 或 QA 执行器不能单方面宣布 Task 成功。

Verification 不直接修改 Task 状态，而是向 Task System 提供验证结果。

## 9.2 六层验证体系

1. Operation Verification：操作是否成功。
2. Structural Verification：项目结构是否正确。
3. Static Verification：代码和静态检查。
4. Runtime Verification：游戏实际运行验证。
5. Integration & Regression Verification：集成和回归。
6. Requirement & Phase Acceptance：需求和阶段验收。

## 9.3 缺陷管理

缺陷状态需要完整记录：

- OPEN。
- TRIAGED。
- ASSIGNED。
- IN_PROGRESS。
- FIXED。
- READY_FOR_RETEST。
- VERIFIED。
- CLOSED。
- REOPENED。
- DEFERRED。

修复 Bug 不代表 Bug 自动关闭。

必须重新验证，并关联原始缺陷和修复变更。

## 9.4 Build 与 Release

必须区分：

- Build。
- Export。
- Package。
- Release。

导出成功不代表发布成功。

发布前必须检查：

- 项目结构。
- 资源导入。
- 许可证。
- Scene 和 Resource 引用。
- 自动测试。
- Runtime 验证。
- 构建产物完整性。
- 发布配置。
- 最终验收状态。

## 9.5 用户阶段验收

自主开发每个阶段结束后：

1. 系统整理完成内容。
2. 汇总测试结果。
3. 汇总未解决缺陷。
4. 提交阶段报告。
5. 等待用户验收。
6. 用户决定继续、修改计划、暂停或终止。

Phase ACCEPTED 才能进入下一阶段。

---

# 第十章 38 个专业 Agent

系统第一阶段规划 38 个专业 Agent。

## 10.1 P0 Agent（15 个）

1. game_designer。
2. gameplay_designer。
3. level_designer。
4. game_architect。
5. gameplay_programmer。
6. ui_developer。
7. scene_developer。
8. inspector_property_specialist。
9. tilemap_level_specialist。
10. godot_resource_specialist。
11. godot_integration_specialist。
12. 2d_artist。
13. ui_ux_designer。
14. animation_specialist。
15. qa_engineer。

## 10.2 P1 Agent（18 个）

1. game_systems_designer。
2. game_balance_designer。
3. game_systems_programmer。
4. data_save_programmer。
5. performance_optimization_engineer。
6. code_quality_refactoring_engineer。
7. signal_interaction_specialist。
8. editor_automation_specialist。
9. art_director。
10. 2d_technical_artist。
11. audio_designer。
12. vfx_artist。
13. asset_pipeline_specialist。
14. lighting_rendering_artist。
15. ui_motion_designer。
16. test_automation_engineer。
17. project_planning_delivery_agent。
18. build_release_engineer。

## 10.3 P2 Agent（5 个）

1. narrative_designer。
2. 3d_artist。
3. 3d_technical_artist。
4. cinematic_designer。
5. post_processing_artist。

Agent 优先级代表产品能力建设优先级，不直接代表开发任务执行顺序。

---

# 第十一章 数据、接口和基础设施

## 11.1 Backend 运行架构

第一阶段采用单进程模块化 Backend。

包含：

- Module Interface Registry。
- Service Container。
- Lifecycle Manager。
- Runtime Supervisor。
- Internal Message Bus。
- Event Store。
- Outbox Dispatcher。
- Recovery Coordinator。

## 11.2 数据存储

采用：

1. SQLite Primary Database。
2. Project Intelligence Index。
3. File Artifact Storage。
4. 独立 Secrets Storage。

SQLite 使用 WAL 模式。

模块通过自己的 Repository 访问数据，不允许其他模块直接访问内部 Repository。

Project Intelligence Index 可以独立重建。

## 11.3 统一数据身份

采用 UUIDv7 作为 Backend 实体 ID 的主要生成方案。

需要区分：

- Entity Identity。
- Execution Identity。
- Version Identity。
- Godot UID。
- File Path。

Godot UID 不得替代 Backend 实体 ID。

路径也不能作为永久稳定身份。

## 11.4 Event System

事件用于表达已经发生的事实。

采用：

- 持久化 Event。
- Internal Message Bus。
- Outbox Dispatcher。
- Inbox Idempotency。
- Dead Letter。
- Event Replay。
- Aggregate Ordering。
- Gap Detection。

支持：

- DELIVERY_REPLAY。
- PROJECTION_REBUILD。
- STATE_RECONCILIATION。

事件重放不能自动重新执行项目写入、工具调用或恢复已经失效的审批。

## 11.5 Module Interface Registry

模块间所有公开接口需要登记：

- Module ID。
- Interface ID。
- Schema ID。
- Version。
- Request Schema。
- Response Schema。
- Error Contract。
- Event Contract。
- Permission。
- Timeout。
- Retry。
- Idempotency。
- Compatibility。

## 11.6 API 类型

系统提供：

- REST API。
- WebSocket API。
- Streaming API。
- Async Job API。
- Event API。

API Gateway 负责外部客户端接入。

Unified Invocation Gateway 负责统一内部调用规范和执行上下文。

两者职责不能混淆。

---

# 第十二章 安全与权限管理

## 12.1 安全目标

系统必须保护：

- 用户数据。
- Godot 项目文件。
- 模型 Provider 凭证。
- 外部服务凭证。
- 项目资源。
- Agent 执行权限。
- Tool 执行权限。
- 用户审批状态。
- 运行环境。

## 12.2 权限模型

采用 RBAC + ABAC + Capability。

权限分层：

1. Agent Definition Permission。
2. Agent Instance Permission。
3. Tool Execution Authorization。

Instance 权限不能超过 Definition 权限。

系统安全策略拥有最高约束权。

UNKNOWN 默认拒绝。

## 12.3 独立授权

以下授权相互独立：

- Tool Permission。
- ChangeSet Approval。
- Runtime Mutation Authorization。
- External Data Authorization。
- Provider Spend Authorization。

用户批准某项项目变更，不代表同时批准外部数据上传、运行时操作或模型付费。

## 12.4 ChangeSet

所有项目写入必须经过 ChangeSet 管理。

ChangeSet 记录：

- 变更文件。
- 变更内容。
- 变更原因。
- 变更来源。
- 变更范围。
- 风险等级。
- 文件哈希。
- 审批状态。
- 执行结果。

审批绑定变更哈希。

如果变更范围或哈希变化，必须重新审批。

---

# 第十三章 并发、异常和恢复

## 13.1 资源锁

支持：

- File Lock。
- Scene Lock。
- Resource Lock。
- Project Lock。

默认同一资源只能由一个写入任务持有写锁。

资源锁采用租约机制和 Fencing Token。

锁获取顺序统一，降低死锁风险。

## 13.2 并发策略

- 只读任务可以并发。
- 项目写入默认串行。
- 不同资源的写入在确认安全后可以有限并发。
- Editor 与 Python 文件操作必须纳入统一锁管理。
- 多 Agent 任务必须遵循 DAG、资源锁和 ChangeSet 范围。

## 13.3 故障恢复

系统必须处理：

- Backend Crash。
- Godot Editor Crash。
- Plugin Disconnect。
- Runtime Crash。
- Model Timeout。
- Provider Failure。
- Tool Timeout。
- Database Failure。
- Partial File Write。
- Agent Failure。
- Workflow Interruption。

恢复时必须核实：

- 数据库状态。
- Event Log。
- Tool 副作用。
- Agent Checkpoint。
- Workflow 状态。
- Task 状态。
- 资源锁。
- Godot Editor 状态。
- Godot Runtime 状态。

UNKNOWN 不允许盲目重试。

## 13.4 Graceful Shutdown

Backend 受控关闭时：

1. 停止接收新的任务。
2. 停止新的执行调度。
3. 通知运行中的任务。
4. 在安全点暂停可暂停任务。
5. 保存 Checkpoint。
6. 持久化状态。
7. 关闭事件派发。
8. 关闭数据库。
9. 释放进程资源。
10. 写入关闭记录。

---

# 第十四章 非功能需求

系统必须具备：

- 本地优先能力。
- 多项目隔离。
- 多 Editor 支持。
- 稳定运行。
- 可恢复执行。
- 可追踪执行历史。
- 安全的文件访问。
- 安全的凭证管理。
- 可扩展 Agent。
- 可扩展 Tool。
- 可扩展 Model Provider。
- 可扩展 Asset Provider。
- 可测试性。
- 可维护性。
- 向后兼容能力。
- 可升级能力。
- 完整日志和审计。

性能、并发数量、资源使用量和响应时间的量化目标，需要在工程实施阶段通过目标设备基准测试确定，不在缺乏依据时虚构指标。

---

# 第十五章 最终验收 Demo

## 15.1 Demo 项目

第一阶段采用 2D Platformer 作为完整端到端验收项目。

Demo 不是单纯展示界面，而是验证整套 AI Agent 系统能否真实完成 Godot 游戏开发。

## 15.2 游戏内容

### 玩家系统

- 玩家移动。
- 玩家跳跃。
- 玩家攻击。
- 玩家受伤。
- 玩家死亡。
- 玩家重生。

### 关卡系统

- TileMapLayer 地图。
- 地面和平台。
- 碰撞区域。
- 陷阱。
- 关卡起点和终点。

### 敌人系统

- 敌人巡逻。
- 敌人发现玩家。
- 敌人攻击。
- 敌人受伤。
- 敌人死亡。

### 游戏系统

- 玩家生命值。
- 收集物。
- 计分系统。
- 游戏状态管理。
- 暂停。
- 游戏结束。
- 胜利结算。

### UI 系统

- 主菜单。
- HUD。
- 生命显示。
- 计分显示。
- 暂停菜单。
- 游戏结束界面。

### 表现系统

- 动画。
- 特效。
- 音效。
- 基础背景。

### 工程验收

- 项目结构正确。
- Scene 和 Node 正确。
- Resource 引用完整。
- 游戏能够运行。
- 自动化测试通过。
- 缺陷得到处理。
- 可以完成桌面平台导出。
- 生成最终项目报告。

允许在第一阶段使用占位美术资源，重点验证系统完整开发闭环。

## 15.3 端到端系统验收

用户提出游戏需求后，系统必须能够：

1. 理解需求。
2. 分析项目。
3. 生成游戏设计。
4. 规划任务。
5. 调度专业 Agent。
6. 创建游戏代码。
7. 创建 Scene 和 Node。
8. 配置 Godot 属性。
9. 创建游戏资源。
10. 集成资源。
11. 运行游戏。
12. 测试游戏。
13. 修复问题。
14. 执行回归测试。
15. 提交阶段报告。
16. 完成用户验收。
17. 构建和导出游戏。

---

# 第十六章 项目开发阶段概览

项目开发划分为十三个阶段：

| 阶段 | 名称 |
|---|---|
| E0 | Project Foundation |
| E1 | Backend Core |
| E2 | Backend Services |
| E3 | Godot Integration |
| E4 | Project & Workflow Systems |
| E5 | AI & Tool Foundation |
| E6 | Agent Runtime |
| E7 | Multi-Agent & Game Development |
| E8 | Asset Pipeline |
| E9 | Verification & QA |
| E10 | Build & Release |
| E11 | Platformer Demo |
| E12 | Productization |

各阶段的具体开发任务、依赖关系、文件结构、实施步骤、交付物和验收标准，以第二份《完整开发实施计划》为准。

各阶段的测试案例、测试数据、自动化执行、回归策略和发布门禁，以第三份《全项目测试与质量保证计划》为准。

---

# 第十七章 项目最终交付内容

最终项目交付包括：

## 17.1 软件交付

- Godot Editor Plugin。
- Local Backend。
- AI Agent Runtime。
- Model Gateway。
- Tool Platform。
- Project Intelligence。
- Project Management。
- Workflow System。
- Context System。
- Asset System。
- Verification System。
- Build & Release System。

## 17.2 配套内容

- 安装程序或安装包。
- 配置管理。
- Provider 配置。
- Agent Definition。
- Skill Definition。
- Tool Definition。
- 项目模板。
- Demo 项目。
- 自动化测试。
- 数据迁移工具。
- 日志和诊断工具。

## 17.3 文档交付

最终以三份核心文档为主：

1. 《Godot AI Agent 完整项目设计说明书》。
2. 《Godot AI Agent 完整开发实施计划》。
3. 《Godot AI Agent 全项目测试与质量保证计划》。

必要的 API、数据结构、接口 Schema 和 Agent/Tool 定义作为这些文档的附录或配套工程规范，不再取代三份主文档。

---

# 第十八章 设计基线与未完成事项

## 18.1 已确认的设计基线

本说明书整合了此前讨论的：

- G01：Godot Plugin 与 Backend 生命周期。
- G02：Task、Workflow、Agent 状态与生命周期。
- G03：Multi-Agent Collaboration。
- G04：Project Intelligence & Context。
- G05：Asset Generation & Management。
- G06：Verification、QA、Delivery & Release。
- G07：Global Architecture & Cross-Module Governance。

这些设计作为本项目当前架构基线。

## 18.2 后续工程细化事项

下列内容需要在开发实施计划和具体工程设计中进一步确定：

- 具体技术栈及依赖版本。
- 完整代码仓库目录。
- 所有模块接口和 Schema。
- 数据库完整表结构。
- API 完整参数和返回值。
- 全部 Agent Definition。
- 全部 Tool Definition。
- Godot 各版本的具体兼容矩阵。
- 量化性能目标。
- 目标部署设备要求。
- 安装、升级和回滚的具体实现。
- 自动化测试环境与测试数据。

## 18.3 文档状态说明

本文件是项目总体设计说明书初稿。

DRAFT 不代表软件功能已经实现，也不代表所有具体实现参数已经确定。

后续经过完整审查和确认后，才能升级为 APPROVED 或 BASELINE。

---

**文档结束**

**下一份关联文件：DOC-02-001《Godot AI Agent 完整开发实施计划》**