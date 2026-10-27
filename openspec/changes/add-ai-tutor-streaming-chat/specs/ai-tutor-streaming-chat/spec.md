## Purpose

提供基于本班知识库证据的 AI 学习助手，支持教师 Prompt、教师控制的 AI 技能、可追溯 citation、SSE 流式回答和会话保存。

## ADDED Requirements

### Requirement: Server-side AI gateway configuration

系统 MUST 仅在 Flask 服务端读取 embedding/chat 网关配置，并不得把 API Key 返回给浏览器。

#### Scenario: Embedding dimension check
- **WHEN** 服务端配置了 `EMBEDDING_BASE_URL`、`EMBEDDING_API_KEY`、`EMBEDDING_MODEL` 和 `EMBEDDING_DIM`
- **THEN** 启动时 MUST 通过真实 embedding 响应检查向量长度
- **AND** 长度不一致 MUST 报清晰错误

#### Scenario: Secrets stay server-side
- **WHEN** 浏览器访问 AI 问答、材料或设置 API
- **THEN** 响应 MUST NOT 包含 `EMBEDDING_API_KEY`、`CHAT_API_KEY`、JWT secret 或 access token 明文

### Requirement: SQLite traceable knowledge index

系统 MUST 在 SQLite 保存知识条目、知识切片和 chunk embedding，并记录索引状态。

#### Scenario: Upload indexes chunks
- **WHEN** 教师上传 UTF-8 txt/md 材料成功
- **THEN** 系统 MUST 保留原材料逻辑并写入 `knowledge_entries`
- **AND** MUST 生成 `knowledge_chunks`
- **AND** MUST 对每个 chunk 调用 embedding API 并保存到 `knowledge_chunk_embeddings`
- **AND** 成功 chunk MUST 标记为 ready，失败 chunk MUST 标记为 failed 且材料仍可阅读

#### Scenario: Rebuild existing materials
- **WHEN** 维护者运行历史索引重建脚本
- **THEN** 系统 MUST 为已有正常 txt/md 材料重建 chunk 和 embedding
- **AND** MUST NOT 删除数据库材料、知识正文或上传文件

### Requirement: Class-scoped retrieval

系统 MUST 支持 keyword、vector、hybrid 检索，并在所有阶段使用服务端身份 class_id。

#### Scenario: Keyword search
- **WHEN** 已认证用户以 keyword 模式检索
- **THEN** 系统 MUST 只查询当前班级 ready chunk
- **AND** MUST NOT 调用 embedding 或 chat gateway

#### Scenario: Vector search
- **WHEN** 已认证用户以 vector 模式检索
- **THEN** 系统 MUST 对 query 调用 embedding
- **AND** MUST 仅与当前班级 ready chunk embedding 计算 cosine similarity
- **AND** MUST 丢弃低于 0.35 的候选

#### Scenario: Hybrid search
- **WHEN** 已认证用户未指定模式或指定 hybrid
- **THEN** 系统 MUST 融合 keyword 与 vector 排名
- **AND** MUST 使用 RRF k=60

#### Scenario: Forged class id ignored
- **WHEN** A 班用户在 query、body 或 header 伪造 B 班 class_id
- **THEN** 检索仍 MUST 只使用 A 班 class_id
- **AND** 响应 MUST NOT 泄露 B 班正文、标题、citation 或 chunk id

### Requirement: Teacher prompt and controlled skill

系统 MUST 支持本班教师修改助手 Prompt 和 solving guidance 技能开关，学生不能修改。

#### Scenario: Teacher updates prompt
- **WHEN** 本班教师 PUT `/api/assistant/prompt`
- **THEN** 系统 MUST 保存本班 Prompt
- **AND** 下一轮问答 MUST 使用新 Prompt

#### Scenario: Student cannot edit prompt or skill
- **WHEN** 学生 PUT Prompt 或 solving guidance skill
- **THEN** 系统 MUST 返回 403
- **AND** 本班配置 MUST 不变

#### Scenario: Skill instruction is server controlled
- **WHEN** solving guidance 开启
- **THEN** 模型输入 MUST 包含服务端 Skill instruction
- **AND** 学生请求体中的 `skill_enabled` MUST NOT 改变该开关

### Requirement: Grounded AI ask

系统 MUST 只在本班检索命中真实 chunk 后调用 chat gateway，并返回服务端构造的 citations。

#### Scenario: No hits
- **WHEN** 本班 hybrid 检索无命中
- **THEN** 系统 MUST 不调用 chat gateway
- **AND** MUST 返回“资料中未找到相关内容”
- **AND** citations MUST 为空数组

#### Scenario: Hits call chat with evidence
- **WHEN** 本班检索命中 chunk
- **THEN** 系统 MUST 最多取前 4 条 evidence 调用 chat gateway
- **AND** evidence MUST 包含真实 material title、chunk id、chunk index、offsets 和 chunk excerpt
- **AND** 响应 citations MUST 由服务端根据 hits 构造，顺序与 `[1]`、`[2]` 一致

### Requirement: SSE streaming and conversation storage

系统 MUST 使用 SSE 返回回答，并保存每轮用户问题和最终助手回答。

#### Scenario: SSE events
- **WHEN** 已认证用户 POST `/api/assistant/ask`
- **THEN** 响应 Content-Type MUST 为 `text/event-stream`
- **AND** 至少 MUST 输出 `delta`、`citations`、`done` 事件

#### Scenario: Conversation owner check
- **WHEN** 用户读取历史会话
- **THEN** 系统 MUST 校验 conversation.user_id 与 class_id
- **AND** 其他学生或其他班级用户 MUST 读取失败
