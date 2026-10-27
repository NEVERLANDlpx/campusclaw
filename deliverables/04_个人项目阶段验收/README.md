# CampusClaw 个人项目阶段验收

## 项目与仓库

- 项目：CampusClaw 班级知识空间
- 技术栈：Flask、SQLite、Bearer JWT、OpenAI 兼容 Chat API、官方 Python MCP SDK
- Git 仓库：https://github.com/NEVERLANDlpx/campusclaw.git
- 本阶段 OpenSpec：`openspec/changes/add-ai-apps-skills-mcp-tracing/`

## 运行

```powershell
python -m pip install -r requirements-dev.txt
python scripts/configure.py
python scripts/init_db.py
python scripts/start_local.py
```

标准容器启动：

```powershell
python scripts/configure.py
docker compose up --build -d
```

页面：http://localhost:8080/materials；Flask 探活：http://localhost:8080/health；MCP 容器探活：http://mcp-tools:8090/health（容器内部地址）。

教师登记内置工具服务时使用：服务器名 `course-tools`、端点 `http://mcp-tools:8090/mcp`、令牌环境变量名 `MCP_SERVICE_TOKEN`。数据库只保存变量名，不保存令牌原文。

## 本阶段能力

- 每班四个独立 AI 应用，分别保存 Prompt、模型参数与检索配置。
- Prompt 模板库采用复制语义，只替换四个白名单变量。
- 三个内置 Skill、Markdown Skill 上传、应用绑定、启停修改、确定性单 Skill 路由及完整指令注入。
- 官方 MCP SDK Streamable HTTP 独立服务、Bearer 校验、分页发现、工具绑定及受限调用循环。
- LLM 请求/响应、Skill 路由、检索命中、MCP 调用和 SSE 事件追踪。
- 教师仅可管理和查看本班；学生只能使用允许的应用并查看自己的追踪。

## 证据性质

`验收证据/` 中 01-03 使用可控假 LLM，证明宿主实际发送的参数、检索、Skill 注入和日志行为；04 使用真实启动的官方 MCP SDK 服务完成 initialize、tools/list 与 tools/call，但模型 tool_calls 仍由可控假 LLM 产生。这种区分是刻意保留的。

当前环境没有配置并运行真实外部课程 LLM 网关，因此本交付物不把可控假 LLM 结果描述为真实模型响应。Docker 仅验证 `docker compose config` 可解析，未在本次执行中构建或启动容器。

## 复现证据

```powershell
python scripts/capture_stage_acceptance.py
python -m pytest -q tests -p no:cacheprovider --basetemp=tmp/pytest-full-final
npx @fission-ai/openspec@1.13.1 validate add-ai-apps-skills-mcp-tracing --strict
```

