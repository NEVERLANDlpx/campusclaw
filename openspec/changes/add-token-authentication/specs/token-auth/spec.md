## Purpose

材料 API 必须使用真实 Bearer Token 完成认证，前端浏览器请求可在 F12 Network 中看到 Authorization 请求头，并继续按服务端班级与角色规则授权。

## ADDED Requirements

### Requirement: JWT token login

系统 MUST 提供 JSON Token 登录接口，使用现有账号密码哈希校验签发短期 JWT Access Token。

#### Scenario: Valid credentials
- **WHEN** `teacher_a`、`student_a1` 或 `student_b1` 向 `POST /api/auth/token` 提交正确 `username` 和 `password`
- **THEN** 返回200，响应包含 `access_token`、`token_type=bearer`、`expires_in=3600`
- **AND** 响应用户信息不包含密码哈希或密钥

#### Scenario: Wrong credentials
- **WHEN** 用户名不存在或密码错误
- **THEN** 返回401和统一错误信息
- **AND** 不泄露账号是否存在

#### Scenario: Token claims and signing
- **WHEN** 系统签发 access token
- **THEN** token MUST 使用 HS256 签名并包含 `exp`、`iat`、`nbf`、`iss`、`sub` 和账号版本
- **AND** 签名密钥 MUST 来自环境变量，不得硬编码

### Requirement: Bearer-only API authentication

系统 MUST 对材料 API 和身份 API 使用 `Authorization: Bearer <token>` 认证，不能仅凭 Session Cookie 通过。

#### Scenario: Missing Authorization
- **WHEN** 未携带 Authorization 请求 `GET /api/materials` 或 `GET /api/me`
- **THEN** 返回401

#### Scenario: Invalid token
- **WHEN** token 签名无效、内容被篡改、issuer 不匹配、格式错误或过期
- **THEN** 返回401
- **AND** 不返回材料内容

#### Scenario: Session without Bearer
- **WHEN** 浏览器只有旧 Session Cookie 但请求头没有 Bearer Token
- **THEN** `GET /api/materials` 返回401

#### Scenario: Database-authoritative user
- **WHEN** token 中存在 role 或 class_id
- **THEN** 后端仍 MUST 使用 token `sub` 查询数据库中的最新角色、班级和账号版本
- **AND** token 账号版本与数据库不一致时返回401

### Requirement: Token-scoped class authorization

系统 MUST 对通过 Bearer Token 认证的材料读写继续执行服务端班级隔离和角色授权。

#### Scenario: Same-class materials
- **WHEN** 学生 A 使用有效 token 请求 `GET /api/materials`
- **THEN** 返回200且仅包含 A 班材料

#### Scenario: Manipulated class id
- **WHEN** 学生 A 使用有效 token 请求 `GET /api/materials?class_id=2`
- **THEN** 仍仅返回 A 班材料，不返回 B 班标题或正文

#### Scenario: Teacher and student permissions
- **WHEN** 教师使用 token 上传、删除或下载本班材料
- **THEN** 按既有规则成功
- **AND** 学生使用 token 上传或删除返回403，但读取和下载本班材料成功

### Requirement: Browser token request chain

前端 MUST 使用 Token 登录接口并在真实 Fetch/XHR 请求中附带 Authorization 请求头。

#### Scenario: Materials page request
- **WHEN** 学生 A 从登录页登录并进入材料页面
- **THEN** 浏览器发起 `GET /api/materials`
- **AND** F12 Network 的该请求 Headers 中可见 `Authorization: Bearer <token>`
- **AND** General 中请求方法为GET、状态为200

#### Scenario: Logout and 401 handling
- **WHEN** 用户点击退出或任一 API 返回401
- **THEN** 前端清理已保存 token
- **AND** 后续材料请求不再发送旧 token，并要求重新登录

#### Scenario: Stable login page in mixed authentication state
- **WHEN** 浏览器打开 `/login`，包括存在 Session Cookie 但 `sessionStorage` 中没有有效 Bearer Token 的情况
- **THEN** 服务端返回可交互的登录页面，不得仅凭 Session 无条件重定向到 `/materials`
- **AND** 登录页不得启动材料、AI 应用、Skill 或 MCP 等受保护 API 的页面初始化
- **AND** 缺少或失效 Token 的恢复与注销流程每次页面加载最多启动一次，最终稳定停留在登录页

#### Scenario: API logout without bearer token
- **WHEN** 混合认证状态中的浏览器向 `POST /api/auth/logout` 发起同源请求且未携带 Bearer Token
- **THEN** 注销端点仍清除服务器 Session 并返回成功
- **AND** 该 Session 对应用户的旧 Token 版本失效，后续 HTML 页面与 API 均要求重新登录

#### Scenario: API logout with token but expired session
- **WHEN** Session 已缺失但浏览器仍持有有效 Bearer Token 并调用 `POST /api/auth/logout`
- **THEN** 注销端点使用该 Token 识别用户并废止其账号版本
- **AND** 缺失或无效 Token 不使注销端点返回401或触发递归恢复

#### Scenario: Protected download from browser
- **WHEN** 用户点击下载原文件
- **THEN** 前端 MUST 使用带 Authorization 的 fetch 获取文件 Blob
- **AND** 不能依赖原生地址栏或普通 `<a href>` 自动携带 Authorization
