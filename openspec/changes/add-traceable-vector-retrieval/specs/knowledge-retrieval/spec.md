## Purpose

为本班材料提供可追溯知识切片、向量索引、检索与引用式问答；所有检索和问答必须继承现有登录会话、角色和班级隔离边界。

## ADDED Requirements

### Requirement: Traceable chunk storage

系统 MUST 将材料正文切分为可追溯 chunk，并在关系数据库中保存正文、位置和班级信息。

#### Scenario: Automatic window chunking
- **WHEN** 教师上传材料且未指定切分策略
- **THEN** 系统 MUST 默认按 800 字窗口、80 字重叠切分正文
- **AND** 每个 chunk MUST 保存 chunk_id、class_id、material_id、序号、字符起止位置和正文

#### Scenario: Custom delimiter chunking
- **WHEN** 材料配置自定义分隔符切分策略
- **THEN** 系统 MUST 优先按该分隔符拆分正文
- **AND** 对超过窗口上限的片段 MUST 继续按自动窗口拆分
- **AND** 每个 chunk 的字符区间 MUST 能映射回原材料正文

#### Scenario: Markdown heading chunking
- **WHEN** 材料使用 Markdown 标题切分策略
- **THEN** 系统 MUST 按 Markdown 标题层级生成 chunk 或标题路径
- **AND** 标题下正文超过 800 字时 MUST 继续按 80 字重叠窗口拆分

### Requirement: Relational chunks and Qdrant vectors

系统 MUST 在关系数据库保存 chunk 可追溯数据，在 Qdrant 保存向量，并用相同 chunk_id 关联。

#### Scenario: Shared chunk id
- **WHEN** 一个 chunk 被成功索引
- **THEN** 关系数据库 MUST 存在相同 chunk_id 的 chunk 记录
- **AND** Qdrant 中 MUST 存在以该 chunk_id 标识或可回溯到该 chunk_id 的向量点
- **AND** 两边记录 MUST 含一致的 class_id 与 material_id

#### Scenario: Existing SQLite baseline
- **WHEN** 设计或实现第四课检索能力
- **THEN** 文档和代码 MUST 以当前 Flask + SQLite 项目为基线
- **AND** MUST NOT 声称 Go 或 MySQL 已经是当前实现
- **AND** 若迁移到 MySQL，MUST 提供数据迁移和班级隔离保持方案

#### Scenario: Index failure is recorded
- **WHEN** 关系数据库 chunk 写入成功但嵌入或 Qdrant upsert 失败
- **THEN** 系统 MUST 保留材料、知识正文和 chunk 记录
- **AND** 对失败 chunk MUST 记录 failed 状态和错误信息
- **AND** 检索 MUST NOT 返回未成功 indexed 的向量结果

### Requirement: Retrieval modes

系统 MUST 支持 keyword、vector、hybrid 三种检索模式，并默认使用 hybrid。

#### Scenario: Keyword search does not call embeddings
- **WHEN** 已登录用户以 keyword 模式检索
- **THEN** 系统 MUST 只查询关系数据库
- **AND** MUST NOT 调用嵌入模型
- **AND** MUST NOT 访问 Qdrant

#### Scenario: Vector threshold
- **WHEN** vector 检索返回候选结果
- **THEN** 系统 MUST 丢弃相似度低于 0.35 的候选
- **AND** 低于阈值的 chunk MUST NOT 出现在响应中

#### Scenario: Hybrid uses RRF
- **WHEN** 用户未指定模式或指定 hybrid 模式检索
- **THEN** 系统 MUST 同时获取 keyword 与 vector 候选
- **AND** MUST 使用 RRF 融合排序
- **AND** RRF 参数 k MUST 为 60

#### Scenario: Qdrant unavailable
- **WHEN** Qdrant 不可用
- **THEN** keyword 模式 MUST 仍能正常返回关系数据库结果
- **AND** vector 模式 MUST 返回明确错误
- **AND** hybrid 模式若降级为 keyword MUST 在响应中标记降级原因

### Requirement: Class-scoped retrieval authorization

系统 MUST 仅从已验证登录会话获取 class_id，并在所有检索阶段执行班级过滤。

#### Scenario: Forged class id is ignored
- **WHEN** A 班用户在 query、body 或 header 中伪造 class_id 为 B 班
- **THEN** keyword SQL MUST 仍按 A 班过滤
- **AND** Qdrant 查询 MUST 仍按 A 班 payload filter 执行
- **AND** 数据库回表 MUST 仍按 A 班过滤

#### Scenario: Cross-class unique content is empty
- **WHEN** A 班用户检索只存在于 B 班材料中的独有内容
- **THEN** 响应 MUST 为空结果或“资料中未找到相关内容”
- **AND** 响应 MUST NOT 包含 B 班标题、正文摘录、chunk_id、material_id 或文件路径

#### Scenario: Vector hit backfill is class checked
- **WHEN** Qdrant 返回 chunk_id 候选
- **THEN** 系统 MUST 使用 chunk_id 与 session.class_id 回表查询
- **AND** 不属于 session.class_id 的 chunk MUST 被丢弃

### Requirement: Traceable retrieval response

系统 MUST 为每条检索命中返回可追溯出处。

#### Scenario: Result contains source fields
- **WHEN** 检索命中一个 chunk
- **THEN** 响应 MUST 包含材料标题、chunk 序号、字符区间、原文摘录和原材料访问入口
- **AND** 原材料访问入口 MUST 指向当前用户可访问的本班材料

#### Scenario: Excerpt comes from real chunk
- **WHEN** 响应返回 excerpt
- **THEN** excerpt MUST 来自关系数据库中对应 chunk 的 body_text
- **AND** excerpt MUST NOT 是生成模型编造或改写的引用文本

### Requirement: Grounded ask endpoint

系统 MUST 只在本班检索得到 chunk 后调用生成模型，并用真实出处标注答案。

#### Scenario: Ask with hits cites real chunks
- **WHEN** 已登录用户调用 POST /api/ask 且本班 hybrid 检索命中 chunk
- **THEN** 系统 MAY 调用生成模型
- **AND** 答案中的 `[1]`、`[2]` 等引用 MUST 对应响应 sources 中的真实 chunk
- **AND** 每个 source MUST 包含材料标题、chunk 序号、字符区间、摘录和材料入口

#### Scenario: Ask with no hits does not call model
- **WHEN** POST /api/ask 的本班检索没有命中 chunk
- **THEN** 系统 MUST 返回“资料中未找到相关内容”
- **AND** MUST NOT 调用生成模型
- **AND** MUST NOT 编造引用或材料标题

#### Scenario: Empty question
- **WHEN** 用户提交空问题或仅空白字符
- **THEN** 系统 MUST 返回 400
- **AND** MUST NOT 调用嵌入模型、Qdrant 或生成模型

### Requirement: Index rebuild and operational safety

系统 MUST 支持安全重建索引，并在异常时保持现有材料和班级隔离。

#### Scenario: Rebuild one material
- **WHEN** 教师或维护任务重建本班某材料索引
- **THEN** 系统 MUST 只重建该材料所属班级的 chunk 与向量
- **AND** 重建不得删除原材料、上传文件或知识正文

#### Scenario: Rebuild is idempotent
- **WHEN** 同一材料重复执行重建索引
- **THEN** 系统 MUST NOT 产生跨班 chunk 或跨班 Qdrant payload
- **AND** 最新 indexed chunk MUST 能通过 chunk_id 回表到同班材料

#### Scenario: Retrieval hides operational details
- **WHEN** 索引失败、Qdrant 故障或跨班候选被丢弃
- **THEN** 普通用户响应 MUST NOT 泄漏服务器路径、Qdrant 内部错误堆栈或他班 payload
- **AND** 服务端日志或教师状态接口 MAY 记录受控错误摘要
