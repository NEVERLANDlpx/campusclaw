# 02 后端 API 暴露与访问说明

结论：当前项目是单 Flask + Compose 架构，没有 Nginx。页面 `/login`、`/materials` 与 API `/api/...` 同源，由 app 服务监听 8080。`docker-compose.yml` 将宿主机 `127.0.0.1:8080` 映射到容器 `8080`，默认只允许本机访问，不代表公网开放。

实际配置路径：

- `docker-compose.yml`
- `Dockerfile`
- `app/__init__.py`

可访问地址：

- 登录页：`http://127.0.0.1:8080/login`
- 材料页：`http://127.0.0.1:8080/materials`
- 健康检查：`http://127.0.0.1:8080/health`
- 受保护 API：`http://127.0.0.1:8080/api/materials`

实测结果：

- 匿名 `/health` 返回 200 JSON。
- 匿名 `/api/me`、`/api/materials` 返回 401。
- 登录教师后，浏览器真实发出 `GET /api/materials`，Request Headers 携带 `campusclaw_session` Cookie，Response 只含 A 班材料。
- Docker CLI 存在，但 Docker Engine 未运行，`docker compose up` 未实测通过。

证据：`deliverables/03_截图与证据/browser-evidence/browser-network-validation.json`、`deliverables/03_截图与证据/http-evidence/`。

