## 1. 仓库与文档（T1）
- [x] 1.1 确认仓根 README 含价值/场景/不做三行说明。verify: 打开 `README.md` 可见三行且与 proposal Non-goals 一致。
- [x] 1.2 添加 `requirements.txt`、应用入口和 `app/` 包骨架。verify: `python -c "import app"` 无报错，缺少密钥时创建应用失败。

## 2. 数据模型与种子（T2）
- [x] 2.1 实现 `scripts/init_db.py`：创建班级、用户、讲义、作业、助手、技能、材料、知识库表。verify: 执行脚本后 SQLite 表含上述结构。
- [x] 2.2 种子：班级 A/B、教师 A、学生 A1/B1、A/B 班可区分材料、用户 `password_hash`。verify: 自动测试查询用户、材料和 bcrypt 哈希。
- [x] 2.3 实现 `app/db.py` 连接、参数化查询、按 `class_id` 列表材料及搜索。verify: A 班列表和搜索不含 B 班标题。

## 3. 登录、会话与密码（T3）
- [x] 3.1 实现 `/login` 页面与 POST 登录逻辑；session 写入 `role`、`class_id`；`SECRET_KEY` 仅来自环境变量。verify: 三账号登录后 `/api/me` 身份正确，缺密钥启动失败。
- [x] 3.2 实现登出与 `login_required`：未登录访问 `/materials` 重定向登录页。verify: 清 Cookie 后页面 302，API 401。
- [x] 3.3 密码 verify 走哈希；错误密码登录失败。verify: 错误口令 401，库中密码字段非明文。

## 4. 班级隔离（T4）
- [x] 4.1 材料列表 API/页面仅查询 session `class_id`。verify: 学生 A1 列表仅含 A 班标题，不出现 B 班样本标题。
- [x] 4.2 按 material id 访问时校验 `class_id`。verify: 教师 A 请求 B 班材料 id 返回 404 且响应无 B 班正文/标题。
- [x] 4.3 确认路由不接受客户端传入的 `class_id` 覆盖会话。verify: 篡改 query/body 中的 `class_id` 仍只能看到本班或越权被拒。

## 5. 角色权限与上传入库（T5）
- [x] 5.1 学生 POST 上传返回 403；DB 与 uploads 无新增。verify: 学生 A1 上传后 `materials` / `knowledge_entries` 行数与上传前相同。
- [x] 5.2 教师上传：落盘 → 解析 txt/md → 同事务写入 `materials` + `knowledge_entries`，`class_id` 来自 session。verify: 教师 A 上传后两表各增 1 行且 class 为 A。
- [x] 5.3 上传成功后本班列表可见；学生 A1 刷新列表可见新条但仍无法上传。verify: 教师上传后 A1 列表含新标题；A1 POST 上传仍 403。
- [x] 5.4 解析失败或非法扩展名返回 4xx 且无脏数据。verify: 上传 `.exe`、空文件、错误编码、超限文件后无孤立 DB 行或文件。

## 6. Docker Compose 与 GET /health（T6）
- [x] 6.1 添加 `Dockerfile`、`docker-compose.yml`、`.env.example`；挂载 `./data`、`./uploads`。verify: `docker compose config` 在 `.env` 存在时可解析。
- [x] 6.2 实现 `GET /health` 无需登录；compose 配置 healthcheck。verify: 本地 `GET /health` 返回 200 JSON。
- [x] 6.3 容器 entrypoint/启动时自动 `init_db`（若库不存在）。verify: Dockerfile CMD 先运行 `python scripts/init_db.py`。
- [ ] 6.4 `docker compose down` 再 `up`（不删 volume）后预置与上传数据仍在。verify: Docker Engine 可用机器上传一条后 down/up，列表仍含该条。
- [x] 6.5 README 补充 Compose 启动步骤、登录 URL、health URL、`.env` 说明。verify: README 可从零定位命令与地址。

## 7. 规约与收尾（T7）
- [x] 7.1 运行 `openspec validate add-auth-rbac-class-knowledge --strict`。verify: `npx @fission-ai/openspec@1.13.1 validate add-auth-rbac-class-knowledge --strict` exit 0。
- [x] 7.2 手工对照 spec 关键 Scenario：跨班被拒、学生上传 403、上传后列表可查。verify: 自动测试、HTTP 采集与浏览器网络验收均记录真实结果。

## 实际验证记录

2026-09-29：`python -m pytest -q tests --basetemp=tmp\pytest-run -p no:cacheprovider` 为 49 passed, 1 skipped；两个 OpenSpec change strict valid；本地 HTTP 与真实 Chrome 浏览器网络验收通过。6.4 因 Docker Engine 未运行未执行，保持未勾选。
