## Why

CampusClaw 已有按班级隔离的材料、知识切片、检索和基础 SSE 问答，但 AI 配置仍以班级为单位，Skill 只有单一开关，模型调用只保留最终文本，也没有标准 MCP 服务及宿主工具循环，无法回答阶段验收要求的五项追踪问题。

## What Changes

- 为每个班级幂等初始化四个独立 AI 应用及可复用 Prompt 模板，应用保存自己的 Prompt 副本与检索参数。
- 将 Skill 扩展为受控指令实体，支持 Markdown 上传、应用绑定、确定性单 Skill 路由和完整指令注入。
- 增加独立、Bearer 认证的 MCP Streamable HTTP 工具服务，并实现服务器登记、握手发现、工具绑定与宿主调用循环。
- 增加 LLM 请求/响应、Skill 路由、检索证据和 MCP 调用审计；所有查询按服务端用户、班级和角色授权。
- 扩展材料页的应用选择、教师配置、Skill/MCP 管理及追踪查看，同时保留已有接口兼容性。

## Capabilities

### New Capabilities

- `assistant-app-management`: 应用级 Prompt、模型参数、检索配置和模板复制。
- `controlled-skills`: Skill 定义、上传、绑定、确定性路由及安全指令注入。
- `mcp-tool-orchestration`: 标准 MCP 发现、授权工具候选集、受限调用循环与审计。
- `ai-call-tracing`: 对实际 LLM 请求/响应、检索、Skill 和工具调用进行可授权追踪。

### Modified Capabilities

- `ai-tutor-streaming-chat`: ask 接口接受 app_id，按可信应用配置执行，并增加 tool_call SSE 事件。

## Non-goals

不执行上传 Skill 中的代码；不提供写入或外发型 MCP 工具；不在日志、前端或交付物中保存 API Key、Bearer Token 或 MCP 令牌；不声称未运行的外部网关或 Docker 验收已经通过。

