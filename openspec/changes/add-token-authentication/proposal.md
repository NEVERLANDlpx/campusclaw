## Why

0930 课堂任务要求在现有网页登录之外，提供真实可运行的 Token 登录认证。验收重点是学生登录后由浏览器前端发起 `GET /api/materials`，请求头实际包含 `Authorization: Bearer <token>`，后端据此返回本班材料。

## What Changes

- 新增 `POST /api/auth/token`，使用现有账号与 bcrypt 密码哈希校验，成功返回短期 JWT Access Token。
- API 认证边界从 Session Cookie 调整为 Bearer Token：`GET /api/me`、`GET /api/materials`、详情、上传、下载、删除等 `/api` 材料接口均校验 `Authorization` 请求头。
- JWT 使用 HS256、环境变量密钥、固定 issuer、`exp` 过期时间和数据库中的最新用户状态，不接受 `alg=none` 或客户端传入的班级。
- HTML 页面继续保留原有 Session Cookie 登录态，用于页面访问和服务端渲染；但材料 API 不能只靠旧 Session Cookie 通过。
- 前端登录表单改为调用 Token 登录接口，保存短期 token，并在 Fetch/XHR 材料列表、上传、删除、下载等请求中真实附带 Authorization。
- README 增加 0930 Token 登录认证说明、F12 截图步骤、验证命令和与旧 Session Cookie 的区别。

## Non-goals

不实现 Refresh Token、SSO、多端 token 管理、长期持久登录、OAuth/OIDC、公开分享链接或生产级密钥轮换。Token 不写入源码、测试截图或日志。

## Impact

修改 Flask 认证逻辑、前端 JS、README、requirements 和自动化测试。既有账号、密码哈希、班级隔离、上传下载和 HTML 页面访问能力保持可用。
