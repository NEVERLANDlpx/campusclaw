## 1. 存储与迁移
- [ ] 1.1 设计并创建 `knowledge_chunks` 表，含 chunk_id、class_id、material_id、ordinal、字符区间、heading_path、body_text、index_status、indexed_at、index_error。verify: schema 可查询且外键/索引覆盖 class_id 与 material_id。
- [ ] 1.2 编写既有 `knowledge_entries` 到 chunk 的迁移或重建脚本。verify: 旧材料可生成 chunk，且不删除材料、正文或上传文件。
- [ ] 1.3 明确 SQLite 继续使用与可选 MySQL 迁移边界。verify: README 或设计文档说明当前 Flask/SQLite 基线和 MySQL 迁移条件。

## 2. 切片
- [ ] 2.1 实现自动窗口切分，默认 800 字、重叠 80 字。verify: 长文本切片字符区间连续且有 80 字重叠。
- [ ] 2.2 实现自定义分隔符切分，超长片段继续窗口拆分。verify: 分隔符样本文本 chunk 边界符合预期。
- [ ] 2.3 实现 Markdown 标题切分并记录 heading_path。verify: 多级标题材料能返回对应标题路径和字符区间。

## 3. 索引
- [ ] 3.1 增加 Qdrant 配置、collection 初始化和健康检查。verify: Qdrant 可用时 collection 存在且向量维度正确。
- [ ] 3.2 上传或重建时为 chunk 生成嵌入并 upsert 到 Qdrant，点 ID 使用 chunk_id。verify: Qdrant payload 含 class_id、material_id、ordinal。
- [ ] 3.3 记录索引状态和失败原因。verify: 模拟 Qdrant 失败时 chunk 为 failed，材料仍可阅读。

## 4. 检索
- [ ] 4.1 实现 keyword 模式，只查关系数据库且不调用嵌入。verify: mock 嵌入客户端调用次数为 0。
- [ ] 4.2 实现 vector 模式，相似度阈值 0.35。verify: 低于 0.35 的候选不返回。
- [ ] 4.3 实现 hybrid 默认模式，RRF k=60。verify: 固定 keyword/vector 排名输入得到可预测融合排序。
- [ ] 4.4 Qdrant 不可用时 keyword 正常，vector 明确失败，hybrid 显式降级。verify: 断开 Qdrant 后三种模式响应符合 spec。

## 5. 权限与班级隔离
- [ ] 5.1 检索 API 只使用 session.class_id，忽略客户端 class_id。verify: A 班伪造 class_id=2 仍只查 A 班。
- [ ] 5.2 Qdrant 查询使用 class_id filter。verify: mock Qdrant 请求包含 A 班 payload filter。
- [ ] 5.3 向量命中后数据库回表再次按 class_id 过滤。verify: Qdrant 返回 B 班 chunk_id 时 A 班响应丢弃该结果。
- [ ] 5.4 跨班独有内容检索为空且不泄漏。verify: A 班检索 B 班独有短语不含 B 班标题、正文、chunk_id、material_id。

## 6. 溯源响应
- [ ] 6.1 检索结果返回材料标题、chunk 序号、字符区间、摘录和材料入口。verify: 响应 source_url 指向本班 `/materials/<id>`。
- [ ] 6.2 excerpt 必须来自真实 chunk body_text。verify: 对照数据库 chunk 正文能找到返回摘录。

## 7. 问答
- [ ] 7.1 实现 `POST /api/ask`，默认 hybrid 检索。verify: 有命中时传入模型的上下文只含本班 chunk。
- [ ] 7.2 无命中时返回“资料中未找到相关内容”且不调用生成模型。verify: mock 生成模型调用次数为 0。
- [ ] 7.3 答案引用校验。verify: `[1]`、`[2]` 均能对应 sources 中真实 chunk；无效引用被拒绝或重试。

## 8. 异常处理与重建
- [ ] 8.1 空查询返回 400 且不调用嵌入、Qdrant 或生成模型。verify: 三类 mock 调用次数均为 0。
- [ ] 8.2 实现单材料和全班重建索引入口或命令。verify: 重建同一材料幂等，不产生重复有效 chunk 或跨班 payload。
- [ ] 8.3 普通用户错误响应不泄漏服务器路径、Qdrant 堆栈或他班 payload。verify: 异常响应只含受控错误信息。

## 9. 测试与文档
- [ ] 9.1 增加单元测试覆盖三种切分策略、RRF、阈值过滤和引用校验。verify: pytest 通过。
- [ ] 9.2 增加集成测试覆盖 keyword/vector/hybrid、Qdrant 故障、跨班伪造 class_id、无命中 ask。verify: pytest 通过。
- [ ] 9.3 更新 README 的第四课变更入口、配置项和验收命令。verify: README 不声称未实现功能已完成。
- [ ] 9.4 运行 `openspec validate add-traceable-vector-retrieval --strict`。verify: 命令 exit 0。
