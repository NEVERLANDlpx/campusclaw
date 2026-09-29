## Context

现有 CampusClaw 是 Python/Flask 应用，使用 SQLite 文件 `data/app.db` 保存班级、用户、材料和知识正文，上传文件保存在 `uploads/`，Docker Compose 只包含 app 服务并挂载 `./data` 与 `./uploads`。认证通过 Flask signed cookie session 完成，服务端每次从数据库读取用户当前 `role` 和 `class_id`，材料列表、详情、下载和删除均按服务端会话班级过滤。

第四课的目标是在此基础上增加可追溯知识库检索。课程示例可能使用 Go/MySQL；本项目当前不是该技术栈。若后续必须与课程 MySQL 示例对齐，需要先写迁移方案，而不是在文档中声称已经使用 MySQL。

## Goals / Non-Goals

目标：

- 将上传后的知识正文切成可追溯 chunk。
- 在关系数据库保存 chunk 正文、位置、材料、班级和索引状态。
- 在 Qdrant 保存向量，使用同一 `chunk_id` 与关系数据库回表关联。
- 提供 keyword、vector、hybrid 三种班级隔离检索，默认 hybrid。
- 提供可追溯问答设计，答案只引用真实命中切片。

非目标：

- 本 change 不实现代码、不部署 Qdrant、不调用真实模型。
- 不修改现有第三课登录、上传、下载功能。
- 不把 Go/MySQL 当作当前项目已经实现的事实。

## Chunking

系统支持三种切分策略：

1. 自动窗口：默认每片 800 字，重叠 80 字；按字符区间滑动，避免长材料只命中局部时无法定位。
2. 自定义分隔符：教师或系统配置分隔符，例如 `\n---\n`；每段过长时继续按自动窗口拆分，过短片段可与相邻片段合并至合理长度。
3. Markdown 标题：按 `#` 到 `######` 标题层级切分，chunk 保留标题路径；标题下正文超过 800 字时继续窗口切分，重叠 80 字。

每个 chunk MUST 记录：

- `chunk_id`：稳定唯一 ID，建议 UUID 或由 `material_id + revision + ordinal` 派生。
- `class_id`
- `material_id`
- `ordinal`
- `char_start` / `char_end`
- `heading_path`（Markdown 模式可用）
- `body_text`
- `index_status`、`indexed_at`、`index_error`

## Storage

关系数据库保存可审计事实，Qdrant 保存向量索引。

关系数据库新增或等价实现：

- `knowledge_chunks(chunk_id, class_id, material_id, ordinal, char_start, char_end, heading_path, body_text, index_status, indexed_at, index_error)`
- 约束：`chunk_id` 唯一；`material_id,class_id` 必须关联同班材料；按 `class_id, material_id, ordinal` 建索引。

Qdrant collection 建议：

- 向量点 ID 使用 `chunk_id`。
- payload 至少包含 `class_id`、`material_id`、`ordinal`。
- Qdrant 查询必须使用 `class_id` filter。

SQLite 与课程 MySQL 差异：

- 当前 SQLite 适合课程单机实验，迁移简单，但全文检索、并发写入和 schema migration 能力有限。
- MySQL 更接近课程示例和多人部署，可使用事务迁移和更明确的索引管理。
- 若迁移到 MySQL，需要先把 `classes/users/materials/knowledge_entries` 和新增 `knowledge_chunks` 做 schema 对齐，再迁移数据与上传路径；迁移前后必须保持 `class_id` 授权语义一致。
- 在未迁移前，本变更按 SQLite 设计实现关系存储，避免虚构 MySQL 已存在。

## Indexing Flow

上传成功后：

1. 读取 `knowledge_entries.body_text` 和材料元数据。
2. 按材料配置或默认策略切分 chunk。
3. 在关系数据库事务中写入 chunk 与 `index_status='pending'`。
4. 调用嵌入模型生成向量。
5. upsert 到 Qdrant，点 ID 为 `chunk_id`，payload 含班级和材料信息。
6. 成功后更新 `index_status='indexed'`；失败时记录 `index_status='failed'` 和 `index_error`，不删除材料、知识正文或上传文件。

重建索引：

- 教师或维护任务可对本班某材料或全班触发重建。
- 重建先标记旧 chunk superseded 或按 revision 隔离，再写入新 chunk；避免 Qdrant 成功但关系库丢失追溯信息。
- 若 Qdrant upsert 部分失败，保留失败状态，检索时不得返回未 indexed 的 chunk。

## Retrieval Modes

`GET /api/knowledge/search` 或等价 API 接受 `q`、`mode`、`limit` 等参数。`class_id` 若由客户端传入必须忽略。

- keyword：只查关系数据库，不调用嵌入模型，不访问 Qdrant。按 `class_id` 和文本匹配过滤，返回 chunk。
- vector：调用嵌入模型得到查询向量，查 Qdrant，必须带 `class_id` filter；向量相似度阈值为 0.35，低于阈值的命中丢弃；再用 chunk_id 回表，并再次按 `class_id` 过滤。
- hybrid：默认模式，同时执行 keyword 和 vector。两路候选使用 Reciprocal Rank Fusion，`k=60`，分数为 `sum(1 / (60 + rank))`。融合后按分数排序，再回表确认班级和可追溯字段。

Qdrant 不可用时：

- keyword 模式仍正常工作。
- vector 模式返回明确 503 或等价错误。
- hybrid 模式可降级为 keyword，并在响应中标记 `degraded: true` 和原因；不能悄悄声称进行了向量检索。

## Authorization And Isolation

班级 ID 仅从已验证的登录会话获取：

- keyword SQL 必须 `WHERE class_id = session.class_id`。
- Qdrant 查询必须设置 `class_id` payload filter。
- Qdrant 命中后的数据库回表必须再次 `WHERE chunk_id IN (...) AND class_id = session.class_id`。
- 客户端伪造 `class_id`、材料 ID 或 Qdrant payload 不得改变授权范围。
- A 班账号检索 B 班独有内容时应返回空结果或“资料中未找到相关内容”，不得暴露 B 班标题、正文、chunk_id 或材料路径。

## Traceable Results

每条命中返回：

- `citation_id`，例如 `[1]`
- `chunk_id`
- `material_id`
- `material_title`
- `chunk_ordinal`
- `char_start` / `char_end`
- `excerpt`
- `score`
- `source_url`，例如 `/materials/<material_id>`

摘录必须来自 `knowledge_chunks.body_text` 的真实内容，长度可限制但不能改写为模型生成文本。

## Ask Flow

`POST /api/ask` 的输入至少包含 `question`，可选 `mode`，默认 hybrid。

流程：

1. 验证登录会话。
2. 空问题返回 400，不检索、不调用模型。
3. 按本班执行 hybrid 检索。
4. 若没有本班 chunk 命中，返回“资料中未找到相关内容”，不得调用生成模型。
5. 若有命中，将真实 chunk 摘录和 citation_id 作为上下文调用生成模型。
6. 输出答案必须用 `[1]`、`[2]` 标注出处；每个引用必须对应响应中的真实 chunk。
7. 模型输出不得引用不存在的编号；若模型生成了无效引用，服务端应过滤、重试或返回受控错误。

## Error Handling

- 索引失败：材料仍可阅读；检索只返回 indexed chunk；教师界面或 API 能看到失败状态和可重建入口。
- Qdrant 故障：keyword 正常；vector 失败；hybrid 可降级并显式声明。
- 嵌入模型故障：keyword 正常；vector/hybrid 的向量部分失败，按上条处理。
- 重建索引：必须幂等；同一材料重复重建不产生跨班污染。
- 空查询：400，且不调用嵌入或生成模型。
- 跨班检索：返回空或 404/403 等固定语义，不泄漏他班内容。

## Risks / Trade-offs

- SQLite 可先支持课程实验，但 chunk 数量增大后 keyword 查询性能有限；后续可评估 SQLite FTS 或 MySQL。
- Qdrant 与关系数据库是双写系统，需要索引状态和重建任务处理不一致。
- 生成模型可能产生幻觉引用，必须由服务端验证引用编号。
- hybrid 降级要透明，否则验收时难以判断实际是否调用了向量检索。

## Migration Plan

1. 增加 `knowledge_chunks` 表和索引状态字段。
2. 为既有 `knowledge_entries` 批量生成 chunk，初始状态 pending。
3. 配置 Qdrant collection 和嵌入模型参数。
4. 后台或命令行重建向量索引。
5. 增加检索 API 与问答 API。
6. 增加从 SQLite 到 MySQL 的可选迁移说明，仅在课程或部署要求时执行。

## Open Questions

- 嵌入模型供应商、向量维度和 Qdrant collection 名称尚未确定。
- 第四课是否要求必须迁移 MySQL，还是允许在 Flask/SQLite 项目上完成等价能力，需要以课程平台最终要求为准。
