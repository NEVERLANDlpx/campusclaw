# CampusClaw · 班级知识空间

价值：为教师和学生提供按班级隔离的教学材料与知识正文入口。
场景：教师上传 UTF-8 txt/md 后入库，同班学生刷新列表阅读。
不做：AI 问答、聊天、注册、找回密码、作业提交批改、技能开关及生产高可用。

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

授权必须由后端执行：学生写入403；A班对B班的详情/下载/删除固定404；列表只用可信班级参数。
写请求需要CSRF令牌；页面表单自动携带，API也可用`X-CSRF-Token`。GET /login建立登录前CSRF，GET /api/me返回认证后的新CSRF。

## 接口

| 方法与路径 | 说明 | 成功 | 失败 |
|---|---|---|---|
| GET /login | 登录页及CSRF | 200 | — |
| POST /login | username/password/csrf_token表单 | 302到/materials | 401口令错误、403 CSRF错误 |
| POST /login | 同字段JSON请求 | 200 JSON | 401/403 |
| POST /logout | 退出并撤销旧会话 | 302到/login | 403 CSRF错误 |
| GET /api/me | 当前身份和CSRF | 200 | 401 |
| GET /materials | 本班材料页面 | 200 | 302到/login |
| GET /api/materials | 本班材料列表 | 200 | 401 |
| GET /api/materials/{id} | 本班材料与正文 | 200 | 401/404 |
| GET /api/materials/{id}/download | 本班教师/学生下载原文件 | 200附件 | 401/404 |
| POST /api/materials/upload | multipart: file/title/csrf_token | 201 | 400/401/403/413/503 |
| POST /api/materials/{id}/delete | 教师删除本班材料 | 200 | 401/403/404/503 |
| GET /health | 无登录探活 | 200 | 503数据库故障 |

上传单文件上限2MiB，总请求上限3MiB；仅UTF-8 txt/md。文件名替换为服务器UUID。
上传时文件落盘与数据库事务之间提供失败清理；不承诺进程断电下跨文件系统/数据库的完整原子性。
材料内容以转义纯文本展示，Markdown不执行HTML，避免注入。
时间使用UTC，界面有UTC标记。

## 验收与复现

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q tests
npx @fission-ai/openspec@1.13.1 validate add-auth-rbac-class-knowledge --strict
npx @fission-ai/openspec@1.13.1 validate add-protected-material-download --strict
```

当前后端50项通过；首版浏览器7项通过，本次新增浏览器6项通过。两个OpenSpec变更均通过严格校验；完整证据见随包验收说明。
使用自己启动的服务重新采集HTTP：

```bash
python scripts/capture_http.py --output ./http-evidence
python scripts/capture_extra_http.py --output ./extra-http-evidence
```

脚本会登录教师A并在结束时退出，撤销采集Cookie；若教师A在其他窗口登录，该会话也将退出。
页面截图可登录后直接截屏；提供`scripts/browser_capture.cjs`和`scripts/browser_extra_capture.cjs`用于安装Playwright后的自动复现（npm install playwright，npx playwright install chromium）。

Docker实际启动/重建验收在本次环境未执行（没有Docker程序）。请在Docker机器运行：上传一份材料 → `docker compose down` → `docker compose up -d` → 重新登录检查资料及正文仍在。
该项不得仅因配置存在就认定通过。

## 目录

- `openspec/changes/add-auth-rbac-class-knowledge/`：proposal、design、spec、tasks。
- `app/`：路由、数据库、模板和样式。
- `scripts/`：密钥生成、初始化、本地启动、HTTP采集与浏览器验证。
- `tests/test_acceptance.py`：身份/隔离/写入/失败路径自动验收。
- `Dockerfile`、`docker-compose.yml`：标准部署配置。

字体：Noto Sans CJK SC，SIL Open Font License，详见app/static/fonts/LICENSE.txt。

## 新增作业实现

`openspec/changes/add-protected-material-download/`记录原文件下载的四件套。
材料详情中的下载按钮对本班教师/学生都可用；GET下载API复用会话认证、查询层班级过滤及真实文件路径限制，附件返回原始字节。uploads没有公共静态映射。
上传仍只接受UTF-8 txt/md；PDF/Word/图片等未实现解析。
直接浏览器访问API：先登录，再在同一域名下打开/api/me或/api/materials。地址栏是GET，上传须使用页面表单或带CSRF的POST。

## 第四课规约变更

`openspec/changes/add-traceable-vector-retrieval/` 是第四课待实施规约：设计按班级隔离的知识切片、Qdrant 向量索引、keyword/vector/hybrid 检索和可追溯问答。本项目当前仍是 Flask + SQLite；该 change 尚未实现完整 RAG 服务，也未部署 Qdrant 或调用生成模型。
