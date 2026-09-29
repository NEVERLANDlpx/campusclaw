## Why

CampusClaw 当前已经提供登录、班级隔离、txt/md 上传、材料列表、知识正文入库和受保护下载。知识正文目前仅存于 SQLite 的 `knowledge_entries.body_text`，用户只能打开材料详情逐篇阅读，无法在本班材料内做可追溯检索，也没有按引用片段回答问题的能力。

第四课需要把“上传后的知识库”推进到可检索、可追溯、可审计的阶段：先将材料正文切成带位置的知识切片，再为切片建立向量索引，最后在 keyword、vector、hybrid 三种模式下检索本班内容，并在问答时只引用真实命中的切片。

## What Changes

- 增加知识切片能力，支持自动窗口、自定义分隔符和 Markdown 标题三种切分策略。
- 在关系数据库保存切片正文、材料关联、班级、序号和字符区间；在 Qdrant 保存向量，双方通过相同 `chunk_id` 关联。
- 增加 keyword、vector、hybrid 三种检索模式，默认 hybrid；hybrid 使用 RRF 排序。
- 增加本班可追溯检索 API，结果返回材料标题、切片序号、字符区间、原文摘录和原材料访问入口。
- 规划 `POST /api/ask`：仅在本班检索命中切片后调用生成模型，答案必须用 `[1]`、`[2]` 标注真实出处；无命中时不调用模型。
- 增加索引失败、Qdrant 故障、重建索引、空查询、跨班检索和客户端伪造 `class_id` 的安全处理。

## Current Baseline

本项目当前是 Python/Flask + SQLite + bcrypt，Docker Compose 运行单个 app 服务并挂载 `./data` 和 `./uploads`。现有表包含 `materials` 与 `knowledge_entries`，但没有知识切片表、Qdrant 服务、嵌入模型调用、向量索引或 `/api/ask`。课程示例中可能出现 Go/MySQL 方案，本变更不会把它当作当前已实现事实；需要在 design 中说明与当前 SQLite 方案的差异和迁移路径。

## Capabilities

### New Capabilities

- `knowledge-retrieval`: 按班级隔离的可追溯知识切片、索引、检索和引用式问答。

### Modified Capabilities

- `auth-upload`: 上传成功后除写入 `knowledge_entries` 外，还需要触发或排队知识切片与向量索引；索引失败不得破坏既有材料和正文。

## Non-goals

本变更仅提交第四课规约，不实现完整 RAG 服务，不部署 Qdrant，不调用真实生成模型，不迁移生产数据库，不改变第三课已有登录、上传、下载和班级隔离行为，不执行 Git commit 或 push。

## Impact

后续实现会新增数据库迁移、切片表、索引状态、Qdrant 配置、检索/问答 API、后台重建索引任务、测试与运行说明。需要继续保持服务端班级隔离和可审计证据，不能把前端隐藏参数或客户端 `class_id` 当作授权依据。
