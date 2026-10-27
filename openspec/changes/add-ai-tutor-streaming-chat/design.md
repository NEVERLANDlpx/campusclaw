## Context

CampusClaw 当前是 Flask 应用，SQLite 位于 `data/app.db`，上传文件位于 `uploads/`。API 已要求 Bearer JWT Token，后端每次从数据库重读用户角色与班级。第5课在此基础上提供可运行的 RAG 问答。

## Decisions

1. 继续使用 SQLite。新增 `knowledge_chunks`、`knowledge_chunk_embeddings`、`assistant_prompts`、`assistant_skill_settings`、`assistant_conversations`、`assistant_messages`。
2. chunk 默认约 800 字，overlap 约 80 字，优先在空行、换行、句号和英文句点附近截断。
3. 向量以 JSON 数组保存到 `knowledge_chunk_embeddings.embedding`。检索由 `app/knowledge.py` 的 `SQLiteVectorStore` 执行 cosine similarity，阈值 0.35。
4. `keyword` 只查 SQLite ready chunk，不调用 embedding。为中文无空格问题增加 CJK 2 字符片段评分。
5. `vector` 调用课程 embedding 网关，限定当前班级 ready chunk 和 embedding dim。
6. `hybrid` 默认执行 keyword + vector，并使用 RRF k=60 融合；embedding 故障时可降级到 keyword 并返回 degraded metadata。
7. 所有 class_id 均来自 Bearer Token 对应用户，忽略 query/body/header 中伪造的 class_id。
8. Prompt 和 Skill 配置以 class_id 为键。学生只能 GET，PUT 仅教师可用。
9. 问答 API 使用 SSE。当前 chat client 调用 OpenAI 兼容 `/chat/completions` 非流式响应后，由 Flask 服务端按片段输出 SSE；若后续课程网关确认支持 `stream=true`，可在 `ChatClient` 内替换为真实上游流式透传。
10. 无检索命中时固定返回“资料中未找到相关内容”，不调用 chat gateway。
11. citation 数据只由服务端根据 hits 构造，正文摘录来自 `knowledge_chunks.chunk_text`，模型不得生成材料标题或 chunk id。

## Data Flow

上传：教师 Bearer Token → 服务端读取 user/class_id → 校验文件 → 写 materials/knowledge_entries/lectures → 切片 → 调 embedding → 写向量表并标记 ready 或 failed。

检索：Bearer Token → 服务端 class_id → keyword/vector/hybrid → 回表再次按 class_id 校验 → 返回真实 chunk 摘录。

问答：Bearer Token → class_id/user_id → Prompt/Skill → hybrid retrieval → 无命中固定回复；有命中构造 evidence → 调 chat gateway → SSE delta/citations/done → 保存 user/assistant 消息。

## Configuration

环境变量仅在 Flask 服务端读取：

- `EMBEDDING_BASE_URL`
- `EMBEDDING_API_KEY`
- `EMBEDDING_MODEL`
- `EMBEDDING_DIM`
- `CHAT_BASE_URL`
- `CHAT_API_KEY`
- `CHAT_MODEL`

若 embedding 与 chat 网关相同，可配置相同 URL/key，但代码仍使用独立 client 和模型配置。

## Security

API Key 不返回前端，不写 README，不写日志。错误响应只给受控消息。A 班用户检索 B 班独有内容返回空或无命中固定文本，不泄露 B 班标题、正文、chunk id 或 material id。

## Migration Plan

启动/初始化执行 `CREATE TABLE IF NOT EXISTS` 并补充 `knowledge_entries` 时间列。已有材料通过 `scripts/rebuild_knowledge_index.py` 重建索引。该脚本只处理正常 txt/md 材料，失败记录 chunk 状态，不删除原文件。

## Risks / Trade-offs

SQLite JSON 向量适合小规模课程验收，数据量扩大后性能有限。vector store 已独立封装，后续可替换为 Qdrant：接口边界为写入 chunk embedding、按 class_id 和 query vector 查询、回表前保留 chunk_id。
