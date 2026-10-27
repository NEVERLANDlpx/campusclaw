## 1. 规约与基线
- [x] 1.1 审查 README、认证/上传 OpenSpec、第4课检索规约，确认当前是 Flask/SQLite。verify: 本 change 的 proposal/design 明确当前基线。
- [x] 1.2 创建第5课 OpenSpec 四件套。verify: `openspec/changes/add-ai-tutor-streaming-chat/` 含 proposal/design/tasks/spec。

## 2. 数据与索引
- [x] 2.1 新增 chunk、embedding、Prompt、Skill、会话和消息表。verify: `app/db.py` schema 创建相应表。
- [x] 2.2 上传后切片并调用 embedding，保存 ready/failed 状态。verify: `tests/test_ai_assistant.py::test_upload_creates_knowledge_index`。
- [x] 2.3 增加历史索引重建脚本。verify: `scripts/rebuild_knowledge_index.py`。

## 3. 检索
- [x] 3.1 实现 keyword/vector/hybrid 和 RRF。verify: `test_keyword_vector_hybrid_and_rrf`。
- [x] 3.2 class_id 仅来自服务端身份。verify: `test_cross_class_unique_content_hidden` 与既有 class isolation 测试。
- [x] 3.3 citation excerpt 来自真实 chunk。verify: `test_hits_call_chat_and_citations_are_real_chunks`。

## 4. Prompt 与 Skill
- [x] 4.1 教师可 GET/PUT Prompt，学生 PUT 返回 403。verify: `test_prompt_and_skill_teacher_only_and_affect_next_round`。
- [x] 4.2 教师可开关 solving guidance，学生不能修改。verify: 同上。

## 5. SSE 问答与会话
- [x] 5.1 实现 `/api/assistant/ask` SSE。verify: `test_sse_events_and_conversation_owner`。
- [x] 5.2 无命中不调用 chat gateway。verify: `test_no_hits_skips_chat_and_returns_fixed_text`。
- [x] 5.3 会话历史按本人和班级校验。verify: `test_sse_events_and_conversation_owner`。

## 6. 前端与文档
- [x] 6.1 材料页增加 AI 学习助手和引用卡。verify: 手工打开 `/materials` 可见入口。
- [x] 6.2 教师页面增加 Prompt/Skill 设置。verify: 教师登录材料页可见设置面板。
- [x] 6.3 README 增加第5课说明和验收步骤。verify: README 含“0930 基于知识库的 AI 问答 / 第5课”。

## 7. 验证
- [x] 7.1 运行 pytest。verify: `python -m pytest -q tests --tb=short --basetemp=tmp\pytest-full-ai -p no:cacheprovider` 为 69 passed, 1 skipped。
- [x] 7.2 运行 OpenSpec strict。verify: `npx @fission-ai/openspec@1.13.1 validate add-ai-tutor-streaming-chat --strict` 为 valid。
- [ ] 7.3 真实课程 gateway 少量手工集成测试。verify: 需配置真实 `.env` 后上传 proof 材料并截图；未配置时不得标记通过。
