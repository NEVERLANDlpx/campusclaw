## Why

CampusClaw 已有 Bearer JWT Token API 认证、教师上传 UTF-8 txt/md 材料、材料正文入库和班级隔离。第4课仅留下了可追溯向量检索规约，当前代码尚未真正实现 RAG 检索链路。第5课需要在真实 Flask/SQLite 基线上补齐知识切片、embedding、keyword/vector/hybrid 检索，再接入教师 Prompt、AI 技能和 SSE 流式问答。

## What Changes

- 增加 SQLite 知识切片表与向量表，上传成功后从 `knowledge_entries.body_text` 生成 chunk、调用课程 embedding 网关并保存向量。
- 增加独立 SQLite vector store 模块，支持 keyword、vector、hybrid 检索；hybrid 使用 RRF k=60。
- 增加安全重建历史知识索引脚本，不删除材料文件或知识正文。
- 增加教师 Prompt 与 solving guidance 技能配置；学生可使用效果但不能修改。
- 增加基于知识库证据的问答 API，默认 hybrid 检索；无命中不调用 chat gateway。
- 增加 SSE `text/event-stream` 回答，返回 meta/delta/citations/done/error 事件。
- 增加会话与消息保存，历史读取校验 user_id 与 class_id。
- 更新前端材料页，加入“AI 学习助手/知识问答”入口和教师设置入口。

## Current Baseline

当前项目实际是 Python/Flask + SQLite，不是 Go/MySQL。当前实现不部署 Qdrant；小规模课程验收用 SQLite 保存 JSON 向量，并由 Python 做 cosine similarity。代码通过独立 vector store 模块隔离该实现，后续可替换为 Qdrant，但本文档不会声称已经使用 Qdrant。

## Capabilities

### New Capabilities

- `ai-tutor-streaming-chat`: 班级隔离知识检索、教师 Prompt、AI 技能、基于证据的 AI 问答、SSE 流式会话与可追溯 citation。

### Modified Capabilities

- `auth-upload`: 教师上传材料成功后触发知识切片与 embedding 索引；索引失败记录状态，不破坏原材料。
- `knowledge-retrieval`: 第4课规约中未实现的检索能力在本变更中以 SQLite 向量存储落地。

## Non-goals

不迁移 MySQL，不部署 Qdrant，不把 API Key 暴露给浏览器，不让客户端决定 class_id、system prompt、skill enabled 或 citations，不 commit/push，不把真实课程网关密钥写入仓库或文档。

## Impact

影响数据库 schema、上传流程、API、前端材料页、README、测试和运行脚本。外部 embedding/chat API 单元测试必须 mock；真实课程 gateway 仅建议少量手工集成验证。
