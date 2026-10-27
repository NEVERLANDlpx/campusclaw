## Context

当前实现是 Flask + SQLite。既有 `assistant_prompts`、`assistant_skill_settings` 与旧接口继续保留；新表和服务以幂等迁移增量加入，旧 solving guidance 开关映射到内置 Skill 的启用状态。

## Decisions

1. `assistant_apps` 以 `(class_id, app_key)` 唯一；四个内置应用逐班幂等插入。Prompt 模板应用时复制 `content`，运行期不引用共享模板。
2. 模板渲染仅替换 `app_name`、`class_name`、`knowledge_policy`、`skill_content` 四个白名单占位符；未知变量拒绝保存或渲染，不使用 `eval`。
3. `skills` 迁移为班级 Skill 实体；旧结构无法直接 ALTER 为全部约束时只增列并建立唯一索引。Markdown 上传只解析文本元数据且不执行任何代码。
4. Skill 路由只考虑当前应用绑定且启用的 Skill，按关键词命中数、优先级、稳定 ID 排序，每轮最多选一个；路由候选、理由和注入内容 SHA-256 写入 `skill_route_logs`。
5. MCP 工具服务使用官方 Python MCP SDK 的 Streamable HTTP transport，独立进程与容器运行。宿主登记表只保存 `token_env_key`，运行时再从环境变量取令牌。
6. 连接先 initialize，再完整分页 tools/list；校验完成后在一个事务内替换清单。失败只更新错误状态，不覆盖旧清单。断开立即清空清单。
7. 工具引用固定为 `tool_name@server_name`。配置和运行期都校验班级、连接状态和发现清单。OpenAI 函数名由服务器名与工具名的稳定规范化值和短哈希构成。
8. `AssistantOrchestrator` 独立执行检索、Skill 路由、消息组装、LLM 调用、MCP 调用和上限控制。工具结果只作为 `tool` 消息追加；已知提示词注入句式命中时替换为固定安全文本。
9. `ChatClient.complete()` 保持返回文本；新增 `complete_traceable(payload)` 返回原始响应字典。每次实际请求前插入 `llm_call_logs`，完成或失败后更新真实响应和状态。
10. 默认最多 3 个工具轮次、累计 5 次工具调用，均可由环境变量调整。达到上限后移除工具声明，请模型基于已有消息生成降级回答。
11. 追踪查询：教师仅本班，学生仅本人。日志 JSON 经过凭据键名和 Bearer 字符串脱敏，并记录截断标志。
12. 教师配置界面把模板选择定义为编辑区复制动作，而非立即写数据库；应用保存请求以编辑区内容为准。异步按钮监听器在第一个 `await` 前保存 DOM 引用，并统一恢复禁用状态及展示真实 API 错误。
13. Skill 列表使用可聚焦按钮卡片与一个复用的内联详情面板。详情读取数据库返回的完整 Skill 内容；保存复用现有 Skill 更新和应用绑定接口，不复制新的状态源，并保留未变更绑定的优先级。
14. MCP 服务器卡片复用既有 connect/tools/disconnect API，并在 Skill 详情中复用既有工具绑定 API。连接中的禁用状态只属于当前浏览器，不新增重复状态源；服务器持久状态仍为 disconnected、connected 或 error。`MCP_ALLOWED_HOSTS` 使用逗号分隔精确主机名/IP，默认仅允许 `mcp-tools` 与显式 loopback 主机；登记和连接均校验，避免把教师可写端点变成任意 SSRF 入口。

## Data Flow

Bearer 用户 → 本班 enabled app → 可选检索 → 单 Skill 路由 → 渲染 system message → 绑定且可用的发现工具 → LLM → 可选 MCP call → tool message → 后续 LLM → 最终回答、citation 与审计。

## Migration Plan

启动初始化执行 `CREATE TABLE IF NOT EXISTS`、受控 `ALTER TABLE ADD COLUMN`、唯一索引和幂等种子。不得删除现有数据库；迁移可重复运行。旧 Prompt 和 Skill 接口继续服务默认知识库应用与 solving guidance Skill。

## Risks / Trade-offs

SQLite 适合课程验收但不适合高并发审计。工具结果注入检测仅是基本防护，不能视为完备提示词注入防御。真实外部 LLM 是否主动返回 tool_calls 取决于所用模型，自动测试使用可控假客户端验证完整协议链路，真实网关结果单独标注。

