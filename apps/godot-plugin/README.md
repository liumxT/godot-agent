# Godot Plugin（E0 骨架）

Godot Editor Plugin，采用 GDScript，基线 Godot 4.5.1。

## 结构

```
addons/godot_ai_agent/
├── plugin.cfg        插件声明（名称、版本、入口脚本）
├── plugin.gd         入口：版本校验、面板注册/释放
├── core/             日志等基础能力
├── ui/               Dock 面板
├── bridge/           Editor/Runtime Bridge（E3）
├── services/         插件侧服务（E3）
├── models/           数据模型
├── resources/        资源与主题
└── utilities/        工具函数
```

## 安装与启用

方式一（开发宿主工程）：直接打开 `apps/godot-plugin`，插件已在该工程的
`project.godot` 中启用。

方式二（安装到其他工程）：把 `addons/godot_ai_agent` 复制到目标工程的
`addons/` 下，在「项目设置 → 插件」中启用「Godot AI Agent」。

## 约束

- 本阶段不实现 Editor Bridge、Session、Heartbeat。
- 插件不得在未经授权的情况下修改项目资源。
- 所有日志必须经 `core/logger.gd`，禁止直接 `print`。
