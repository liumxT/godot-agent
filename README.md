# Godot AI Agent

面向 Godot 的本地优先 AI 游戏开发平台。

用户通过 Godot 编辑器插件提出开发需求，本地 Backend 理解项目结构与代码，
经 Agent 规划、工具系统受控修改、用户审批后完成编辑器同步、运行验证，
并最终产出可交付的桌面构建。

## 当前状态

E0 阶段（项目基础设施与工程规范）。

- [x] 技术栈决策（ADR-001 / ADR-002 / ADR-003）
- [x] E0-T01 仓库初始化
- [ ] E0-T02 技术栈与运行环境（打包 spike 待完成）
- [x] E0-T03 Backend 骨架
- [x] E0-T04 Godot Plugin 骨架
- [x] E0-T05 Shared Contracts
- [ ] E0-T06 数据库规范
- [ ] E0-T07 配置与 Secrets
- [ ] E0-T08 日志与异常
- [ ] E0-T09 CI
- [ ] E0-T10 工程文档

## 技术基线

| 项 | 版本 |
| --- | --- |
| Godot | 4.5.1（GDScript-only） |
| Backend | Python 3.14 + FastAPI |
| 数据库 | SQLite（WAL） |
| 通信 | 本地 WebSocket + HTTP（仅 127.0.0.1） |

详见 [技术决策记录](docs/06-decisions/README.md)。

## 仓库结构

```
apps/backend/            Local Backend（Python）
apps/godot-plugin/       Godot Editor Plugin（GDScript）
packages/contracts/      跨进程契约（JSON Schema）
docs/                    工程文档与 ADR
scripts/                 工程脚本
tests/                   集成测试与测试夹具
config/                  分环境配置
```

## 文档

- [项目设计说明书](Godot%20AI%20Agent%20完整项目设计说明书.md)
- [开发实施计划](Godot%20AI%20Agent%20完整开发实施计划.md)
- [测试与质量保证计划](Godot%20AI%20Agent%20全项目测试与质量保证计划.md)
- [全局实施蓝图](实施蓝图.md)
- [E0–E12 阶段细分](完整开发计划细分/)

## 开发约定

见 [CONTRIBUTING.md](CONTRIBUTING.md)。
