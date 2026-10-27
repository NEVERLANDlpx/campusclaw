## Context

当前 CampusClaw 已有 Flask 签名 Session Cookie，用于网页登录、角色识别、班级隔离、上传和下载。0930 作业要求材料 API 展示真实 Bearer Token 请求头，因此需要把 API 认证和页面 Session 认证明确拆开。

## Goals / Non-Goals

目标是短期 JWT 登录、API Bearer 验证、前端真实 Fetch/XHR 携带 Authorization、本班材料隔离和旧功能不回归。非目标见 proposal。

## Decisions

1. 使用 PyJWT 维护版库，签名算法固定为 HS256。解码时显式传入 `algorithms=['HS256']`，并验证 `exp`、`iss`、`sub`、`iat`、`nbf` 等声明；不支持 `alg=none`。
2. Token 签名密钥从环境变量读取：优先 `JWT_SECRET_KEY`，否则使用同样来自环境变量的 `SECRET_KEY`。不提供硬编码默认值。issuer 为 `campusclaw`，Access Token 有效期 3600 秒。
3. Token payload 仅包含必要身份索引：`sub` 为用户 ID，另含 `auth_version`、`role`、`class_id` 作为审计/版本信息。授权时必须重新按用户 ID 查询数据库，使用数据库中的最新角色、班级和 `auth_version`；若版本不一致，返回401。
4. `POST /api/auth/token` 复用现有账号与 bcrypt 校验，错误凭据统一返回401，不泄露账号是否存在。成功响应 `access_token`、`token_type=bearer`、`expires_in` 和非敏感用户信息。为兼容现有 HTML 页面导航，成功后也建立页面 Session；API 访问仍必须带 Bearer。
5. `/api/me`、`/api/materials`、`/api/materials/{id}`、下载、上传和删除统一使用 Bearer Token。没有 Authorization、格式错误、签名错误、篡改、过期、issuer 不匹配或账号版本失效均返回401。仅有旧 Session Cookie 不能访问这些 API。
6. 材料列表、详情、下载、删除和上传继续只使用服务端可信 `g.user.class_id`；客户端 query/form 中的 `class_id` 不参与授权。A 班 token 搭配 `class_id=B` 仍只能得到 A 班数据或404。
7. 前端在登录页调用 `/api/auth/token`，把 token 放入 `sessionStorage` 以支持同一浏览器标签刷新。README 明确记录 XSS 风险和现有 CSP/模板转义约束；登出、401 或 token 缺失时清理 token。
8. 原生 `<a href>` 不会自动附带 Authorization，因此详情页下载改由前端拦截并用带 Bearer 的 `fetch` 获取 Blob，再触发本地下载。
9. `/login` 是混合认证状态的稳定恢复落点。服务端不能根据不可见的浏览器 `sessionStorage` 推断 Bearer Token 是否存在，因此 GET `/login` 始终渲染登录表单；登录页前端按页面元素显式隔离初始化，不发起材料、AI、Skill 或 MCP 受保护请求。
10. Token 缺失或 API 返回401时，前端用单次守卫捕获并清理 token、调用不要求 Bearer 的同源注销端点并替换到 `/login`。若清理前存在 Token，注销请求可携带它供 Session 已失效时识别并废止账号版本；无效或缺失 Token 仍返回成功。注销请求本身不经过统一 Bearer API 包装，避免401递归；重复并发401共享同一恢复状态，不重复导航。

## Risks / Trade-offs

`sessionStorage` 中的 token 会受 XSS 影响，必须继续保持 CSP、Jinja 自动转义、正文以纯文本展示和不硬编码 token。没有 Refresh Token 意味着 token 过期后需要重新登录，符合课堂演示范围。

Session Cookie 与 `sessionStorage` Token 可能因标签页复制、存储清理或 Token 过期而短暂不一致。稳定登录页和有限次数恢复会牺牲“已登录用户访问 `/login` 自动跳回材料页”的便利性，但避免服务端无法观察 Token 时产生重定向循环。

## Migration Plan

数据库结构无需迁移。部署时若需要独立 JWT 密钥，可在 `.env` 添加 `JWT_SECRET_KEY`；未设置时使用已有环境变量 `SECRET_KEY`。
