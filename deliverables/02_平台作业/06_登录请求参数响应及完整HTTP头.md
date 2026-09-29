# 06 登录请求参数、响应结果及完整 HTTP 头

登录 URL：`http://127.0.0.1:8080/login`。

Method：`POST`。

请求类型：普通 HTML 表单提交，Network 中属于 `Doc`，不是 XHR。项目没有为了截图强行改成 JSON 登录；材料列表和上传使用 Fetch/XHR。

Payload 字段：

- `csrf_token=[REDACTED]`
- `username=teacher_a`
- `password=[REDACTED]`

成功响应：

- Status：302
- Location：`/materials`
- Set-Cookie：`campusclaw_session=[REDACTED]; Expires=...; HttpOnly; Path=/; SameSite=Lax`

错误密码响应：401，页面显示统一错误信息，不建立认证会话。

完整脱敏 HTTP 记录：`deliverables/03_截图与证据/http-evidence/02_登录请求与完整HTTP响应.txt`。

