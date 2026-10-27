# CampusClaw · 班级知识空间

价值：为教师和学生提供按班级隔离的教学材料与知识正文入口。
场景：教师上传 UTF-8 txt/md 后入库，同班学生刷新列表阅读。
不做：注册、找回密码、作业提交批改、写入/外发型工具及生产高可用。

## 对照课件

参考：[第2课 · SDD 与 CampusClaw 规约](https://devops.hello1023.com/课件/第2课-课件-SDD与CampusClaw规约/index.html)。
课表案例是解释SDD的方法示例，并非CampusClaw功能；没有把无登录课表混入本项目。
第2课原本仅交规约；本包按登录身份、HTTP记录、运行截图，以及新增API访问、下载权限、上传类型六项作业继续完成实现。
先形成四件套，再实现并逐项验收。项目没有冒充执行过 /opsx-propose；四件套由本次实现流程编写，另通过官方 OpenSpec CLI 严格校验。

## 标准启动：Docker Compose

需要 Python 3（生成密钥）和 Docker Desktop / Docker Engine + Compose 插件。
在本目录执行：

```bash
python scripts/configure.py
docker compose up --build -d
docker compose ps
```

打开 http://localhost:8080/login 。探活：http://localhost:8080/health 。
`configure.py` 创建含随机密钥的 `.env`，不会覆盖已有文件。
也可复制 `.env.example` 为 `.env`，用 `python -c "import secrets; print(secrets.token_hex(32))"` 生成密钥后填入。

数据库：`data/app.db`；上传：`uploads/`。Compose 挂载这两个目录，初始化幂等。
不要删除这两个目录，否则资料会丢失。`.env` 不应提交到版本库。
Compose绑定127.0.0.1，默认仅本机访问；本地HTTP下COOKIE_SECURE=0，HTTPS部署才设为1。

## 无 Docker 本地运行

建议 Python 3.12。Windows PowerShell：

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python scripts/configure.py
.venv\Scripts\python scripts/start_local.py
```

macOS / Linux：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/configure.py
.venv/bin/python scripts/start_local.py
```

浏览器同样访问 http://localhost:8080/login 。停止服务用 Ctrl+C。
本地入口使用Flask开发服务器，关闭debug；本次采集运行证据使用Gunicorn 23.0.0。

## 演示账号

| 账号 | 密码 | 角色 | 班级 |
|---|---|---|---|
| teacher_a | Campus@2026 | 教师 A | A |
| student_a1 | Campus@2026 | 学生 A1 | A |
| student_b1 | Campus@2026 | 学生 B1 | B |

这些是课程演示账号。数据库保存bcrypt哈希；预置明文口令只用于演示说明和初始化脚本，不作为用户表字段。
六类核心结构为classes、users、lectures、assignments、assistants、skills；另有materials与knowledge_entries。
作业/助手/技能仅预留结构，未实现业务入口；B班样本为初始化数据，不代表学生能上传。

## 身份与授权

使用Flask默认的签名Cookie会话，Cookie名`campusclaw_session`。载荷含user_id、role、class_id、auth_version、csrf_token。
Cookie签名不是加密。浏览器存载荷并随请求发送；服务端校验签名、两小时有效期与账号auth_version，再重新读取数据库中的当前角色和班级。
本项目既不是JWT，也不是仅存随机session_id的纯服务端会话。课件中的“服务端会话（signed cookie）”在这里按实际实现准确表述。
退出使账号auth_version加1并删除Cookie，因此同账号的其他旧登录也失效。

### 0930 Token 登录认证

新增作业“0930-课堂任务-token方案实现登录认证”已实现真实 Bearer Token API。`POST /api/auth/token` 使用现有账号、bcrypt 密码哈希和数据库用户记录签发 JWT Access Token；JWT 使用 PyJWT、HS256、`exp`、`iat`、`nbf`、`iss=campusclaw`、`sub=user_id` 和 `auth_version`，有效期默认 3600 秒。签名密钥优先读取环境变量 `JWT_SECRET_KEY`，未单独配置时使用同样来自环境变量的 `SECRET_KEY`，没有硬编码密钥。

网页登录页面仍保留 Session Cookie，用于进入 `/materials` 等 HTML 页面；但 `/api/me`、`/api/materials`、材料详情、上传、删除和下载等 `/api` 接口现在必须携带 `Authorization: Bearer <access_token>`。只有旧 Session Cookie、没有 Bearer Token 时，`GET /api/materials` 返回401。后端验证 Token 后仍按用户ID重新查询数据库中的最新角色、班级和 auth_version，列表、详情、下载和写入都只使用服务端可信 `class_id`，请求参数中的 `class_id` 不参与授权。

前端登录表单会真实请求 `/api/auth/token`，把 access token 临时保存到 `sessionStorage`，随后材料列表、搜索、上传、删除、下载都通过 Fetch/XHR 附带 Authorization。下载不再依赖普通 `<a href>`，而是使用带 Authorization 的 fetch 获取 Blob。`sessionStorage` 会受到 XSS 影响，因此本项目继续使用 CSP、Jinja 自动转义、纯文本正文展示和 no-store 响应；不要把 token 写入 HTML、源码、截图或日志。点击退出或 API 返回401时，前端会清理 token 并要求重新登录。

授权必须由后端执行：学生写入403；A班对B班的详情/下载/删除固定404；列表只用可信班级参数。
写请求需要CSRF令牌；页面表单自动携带，API也可用`X-CSRF-Token`。GET /login建立登录前CSRF，GET /api/me返回认证后的新CSRF。

## 接口

| 方法与路径 | 说明 | 成功 | 失败 |
|---|---|---|---|
| GET /login | 登录页及CSRF | 200 | — |
| POST /login | username/password/csrf_token表单 | 302到/materials | 401口令错误、403 CSRF错误 |
| POST /login | 同字段JSON请求 | 200 JSON | 401/403 |
| POST /api/auth/token | JSON: username/password | 200 JSON，返回Bearer JWT | 401 |
| POST /logout | 退出并撤销旧会话 | 302到/login | 403 CSRF错误 |
| GET /api/me | Bearer Token当前身份和CSRF | 200 | 401 |
| GET /materials | 本班材料页面 | 200 | 302到/login |
| GET /api/materials | Bearer Token本班材料列表 | 200 | 401 |
| GET /api/materials/{id} | Bearer Token本班材料与正文 | 200 | 401/404 |
| GET /api/materials/{id}/download | Bearer Token本班教师/学生下载原文件 | 200附件 | 401/404 |
| POST /api/materials/upload | Bearer Token multipart: file/title/csrf_token | 201 | 400/401/403/413/503 |
| POST /api/materials/{id}/delete | Bearer Token教师删除本班材料 | 200 | 401/403/404/503 |
| GET /health | 无登录探活 | 200 | 503数据库故障 |

上传单文件上限2MiB，总请求上限3MiB；仅UTF-8 txt/md。文件名替换为服务器UUID。
上传时文件落盘与数据库事务之间提供失败清理；不承诺进程断电下跨文件系统/数据库的完整原子性。
材料内容以转义纯文本展示，Markdown不执行HTML，避免注入。
时间使用UTC，界面有UTC标记。

## 验收与复现

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q tests -p no:cacheprovider
npx @fission-ai/openspec@1.13.1 validate add-auth-rbac-class-knowledge --strict
npx @fission-ai/openspec@1.13.1 validate add-protected-material-download --strict
npx @fission-ai/openspec@1.13.1 validate add-token-authentication --strict
```

当前后端59项通过、1项因当前Windows账号不能创建符号链接而跳过；首版浏览器7项通过，本次新增浏览器6项通过。三个OpenSpec变更均可严格校验；完整证据见随包验收说明。
使用自己启动的服务重新采集HTTP：

```bash
python scripts/capture_http.py --output ./http-evidence
python scripts/capture_extra_http.py --output ./extra-http-evidence
```

脚本会登录教师A并在结束时退出，撤销采集Cookie；若教师A在其他窗口登录，该会话也将退出。
页面截图可登录后直接截屏；提供`scripts/browser_capture.cjs`和`scripts/browser_extra_capture.cjs`用于安装Playwright后的自动复现（npm install playwright，npx playwright install chromium）。

Docker实际构建/启动验收在本次环境未完成：`docker compose config` 可解析；`docker compose build` 经提权后仍失败，原因是 Docker Desktop Linux Engine pipe 不存在，当前机器 Docker Engine 未运行。未执行容器构建或启动，也未删除 volume。请在 Docker Engine 已启动的机器运行：上传一份材料 → `docker compose down`（不加 `-v`）→ `docker compose up -d` → 重新登录检查资料及正文仍在。该项不得仅因配置存在就认定通过。

### 0930 F12 截图步骤

1. 运行 `python scripts/configure.py`，再运行 `python scripts/start_local.py`；或运行 `docker compose up --build -d`。打开 `http://localhost:8080/login`。
2. 按 F12 打开 Chrome/Edge 开发者工具，切到 Network，勾选 Preserve log，点 Fetch/XHR 过滤器。
3. 点击“学生 A1”演示账号，确认密码为 `Campus@2026`，点击“登录知识空间”。
4. 页面进入 `/materials` 后，Network 的 Fetch/XHR 列表中选择名称为 `materials`、请求 URL 为 `http://localhost:8080/api/materials` 的那条 GET 请求。
5. 在右侧 Headers 面板截图：General 中应看到 `Request Method: GET` 和 `Status Code: 200 OK`；Request Headers 中应看到 `Authorization: Bearer <token>`。
6. Response 或 Preview 中应只出现 A 班材料；即使请求 `GET /api/materials?class_id=2`，使用学生 A Token 也不能得到 B 班材料。
7. 点击侧边栏“退出登录”后，前端清理 `sessionStorage` 中的 `campusclaw_access_token`；再次进入材料页需要重新登录，不会继续发送旧 token。

Token方案与旧Session Cookie方案的区别：旧方案由浏览器自动随同域请求携带签名 Cookie，适合 HTML 页面；新方案由前端 JS 主动在 API 请求头加入 `Authorization: Bearer ...`，适合 F12 验证和前后端分离 API。两者都不信任客户端传入的班级，真正授权仍由后端查询数据库后执行。

## 目录

- `openspec/changes/add-auth-rbac-class-knowledge/`：proposal、design、spec、tasks。
- `app/`：路由、数据库、模板和样式。
- `scripts/`：密钥生成、初始化、本地启动、HTTP采集与浏览器验证。
- `tests/test_acceptance.py`：身份/隔离/写入/失败路径自动验收。
- `Dockerfile`、`docker-compose.yml`：标准部署配置。

字体：Noto Sans CJK SC，SIL Open Font License，详见app/static/fonts/LICENSE.txt。

## 新增作业实现

`openspec/changes/add-protected-material-download/`记录原文件下载的四件套。
`openspec/changes/add-token-authentication/`记录0930 Token登录认证四件套。
材料详情中的下载按钮对本班教师/学生都可用；GET下载API使用 Bearer Token 认证、查询层班级过滤及真实文件路径限制，附件返回原始字节。uploads没有公共静态映射。
上传仍只接受UTF-8 txt/md；PDF/Word/图片等未实现解析。
直接浏览器地址栏访问 `/api/me` 或 `/api/materials` 不会自动附带 Authorization，因此会返回401；请通过登录后的材料页面 Fetch/XHR 或带 Bearer Token 的 API 客户端访问。上传须使用页面表单或同时带 Bearer Token 与 CSRF 的POST。

## 第四课规约变更

`openspec/changes/add-traceable-vector-retrieval/` 是第四课待实施规约：设计按班级隔离的知识切片、Qdrant 向量索引、keyword/vector/hybrid 检索和可追溯问答。本项目当前仍是 Flask + SQLite；该 change 尚未实现完整 RAG 服务，也未部署 Qdrant 或调用生成模型。

## 0930 基于知识库的 AI 问答 / 第5课

本次实现 `openspec/changes/add-ai-tutor-streaming-chat/`。当前真实架构是 Flask + SQLite：上传文件仍保存在 `uploads/`，正文保存在 `knowledge_entries`，新增 `knowledge_chunks` 保存切片和字符区间，新增 `knowledge_chunk_embeddings` 以 JSON 数组保存向量。小规模课程验收由 Python 在 SQLite 结果上计算 cosine similarity；当前没有部署或使用 Qdrant，也不会声称已经接入 Qdrant。后续迁移 Qdrant 的边界在 `app/knowledge.py` 的 vector store 模块：按 class_id 写入/检索 chunk 向量，再回表校验 chunk。

服务端从 `.env` 读取这些 AI 网关变量，只写变量名，不要写密钥值：

- `EMBEDDING_BASE_URL`
- `EMBEDDING_API_KEY`
- `EMBEDDING_MODEL`
- `EMBEDDING_DIM`
- `CHAT_BASE_URL`
- `CHAT_API_KEY`
- `CHAT_MODEL`

embedding 与 chat 网关可以配置成相同地址和 key，但代码中分别使用 embedding client 和 chat client。配置完整时，服务端启动会用一条短文本检查 `EMBEDDING_DIM` 与真实 embedding 长度是否一致；不一致会报清晰错误。API Key 只在 Flask 服务端使用，不会发送给浏览器。

上传与索引流程：教师上传 UTF-8 `.txt` / `.md` 后，系统先按原逻辑保存材料、正文和讲义关联，再按约 800 字、80 字 overlap 切片，尽量在空行、换行、句号附近截断。每个 chunk 调 embedding，成功标记 `ready`，失败标记 `failed` 并记录受控错误；材料本身仍可阅读。历史材料可运行：

```bash
python scripts/rebuild_knowledge_index.py
```

脚本只处理正常 txt/md 材料，失败会记录到索引状态，不删除数据库材料、知识正文或上传文件。

检索支持三种模式：`keyword` 只查 SQLite ready chunk，不调用 embedding；`vector` 对 query 调课程 embedding，与当前班级 ready chunk 向量计算 cosine similarity，阈值 0.35；`hybrid` 是默认模式，合并 keyword 和 vector 排名并使用 RRF，k=60。所有阶段的 `class_id` 都来自 Bearer Token 对应用户的服务端身份，客户端 query/body/header 中伪造 `class_id` 不参与授权。返回 citation 前还会按当前班级回表校验，A 班检索 B 班独有词对外表现为无结果。

教师 Prompt 与 Skill：教师可通过页面或 API 修改本班 Prompt，保存后下一轮提问生效；学生不能修改。`solving_guidance` 技能由教师开关，开启时服务端给模型额外注入“启发式引导、给思路和关键步骤、引用本班资料、不直接给最终答案”的 Skill instruction。学生请求中伪造 `skill_enabled` 不会改变服务端配置。

AI 问答入口在登录后的 `/materials` 页面，“AI 学习助手”区域会显示“回答基于班级 A 知识库”等班级提示。问答 API 使用 `POST /api/assistant/ask`，返回 `text/event-stream`。事件包含 `meta`、`delta`、`citations`、`done`，错误时包含 `error`。当前实现会先调用 OpenAI 兼容 `/chat/completions` 获取最终文本，再由 Flask 服务端按片段输出 SSE；未虚构上游模型一定支持 `stream=true`。前端使用 fetch streaming 边接收边显示回答，不等完整响应后一次性出现。

无命中行为：如果本班 hybrid 检索没有命中 ready chunk，服务端不会调用 chat gateway，固定返回“资料中未找到相关内容”，并返回空 citations。citation 数据始终由服务端根据真实 chunk 构造，材料标题、chunk id、chunk 序号、字符区间和摘录都来自数据库，不能让模型自行编造。

浏览器验收建议：

1. 配置 `.env` 中的 embedding/chat 变量，运行 `python scripts/start_local.py`。
2. 用教师 A 登录，上传 `docs/ai-qa-proof.md`，或上传同内容的 UTF-8 Markdown 文件 `ai-qa-proof.md`。
3. 若材料是旧数据，运行 `python scripts/rebuild_knowledge_index.py` 补齐索引。
4. 用学生 A1 登录，打开 `/materials` 的 AI 学习助手。
5. 提问：`CampusClaw 的知识检索在没有资料依据时应该怎么处理？`
6. 预期页面逐段显示回答，正文含 `[1]`；引用来源卡显示 `ai-qa-proof.md`、chunk 编号、字符区间、原文摘录和“打开对应材料”；不会引用 B 班材料。
7. 再提一个本班资料没有依据的问题，预期显示“资料中未找到相关内容”，且不显示伪造 citation。

截图建议截取：材料页顶部班级提示、AI 学习助手流式回答区域、`[1]` 标注、引用来源卡、Network 中 `/api/assistant/ask` 的 `text/event-stream` 响应。不要截取 `.env`、Authorization Token、API Key、JWT Secret 或 Session。

## 个人项目阶段验收：多应用、Skill、MCP 与追踪

`openspec/changes/add-ai-apps-skills-mcp-tracing/` 记录本阶段规约。初始化会为每个班级幂等创建“通用 AI 对话、课程知识库问答、学习辅导助手、课程工具助手”四个应用；每个应用保存独立 Prompt 副本、模型参数和检索配置。模板变量只允许 `app_name`、`class_name`、`knowledge_policy`、`skill_content`。

内置 Skill 为 `solving_guidance`、`knowledge_citation`、`course_tool_assistant`。教师可以上传 Markdown Skill；内容只作为受控指令保存和注入，不执行其中的 Python、Shell 或其他代码。每轮只选择一个绑定且启用的 Skill，候选、命中原因和注入内容哈希会写入审计表。

独立 MCP 服务由官方 Python MCP SDK 的 Streamable HTTP transport 实现，提供只读工具 `lookup_course_glossary` 和 `formula_hint`。标准 Compose 启动会同时运行 Flask 宿主和 `mcp-tools` 服务：

```bash
python scripts/configure.py
docker compose up --build -d
```

`MCP_SERVICE_TOKEN` 只存在于服务端环境；数据库仅保存 `token_env_key`。首次使用时，教师在页面或 API 登记 `http://mcp-tools:8090/mcp`、环境变量名 `MCP_SERVICE_TOKEN`，再调用连接接口完成 initialize 与分页 tools/list。宿主只向模型声明当前命中 Skill 已绑定、当前连接且仍在发现清单中的工具。
`MCP_ALLOWED_HOSTS` 使用逗号分隔允许连接的精确主机名或 IP；Compose 默认允许 `mcp-tools` 和显式 loopback 主机。若部署需要连接其他 MCP 主机，必须由运维显式加入允许列表，教师表单本身不能扩大服务端网络访问范围。

问答请求使用 `app_id`，服务端忽略客户端伪造的 `class_id` 或 `skill_enabled`。SSE 事件包含 `meta`、真实发生时的 `tool_call`、`delta`、`citations`、`done` 和 `error`。实际模型请求/响应写入 `llm_call_logs`，MCP 调用写入 `mcp_call_logs`；教师仅能查本班，学生仅能查本人。日志不保存 Authorization、API Key 或 MCP 令牌。

本阶段验证命令：

```bash
python -m pytest -q tests -p no:cacheprovider --basetemp=tmp/pytest-full-stage
npx @fission-ai/openspec@1.13.1 validate add-ai-apps-skills-mcp-tracing --strict
docker compose config --quiet
```

自动测试使用可控假 LLM 验证 tool_calls 编排，同时启动本机真实官方 MCP SDK 服务验证握手、Bearer 拒绝、发现和调用。真实外部课程 LLM 网关仍需在拥有有效网关配置的环境单独运行；未运行时不得把假客户端结果描述为真实模型结果。
