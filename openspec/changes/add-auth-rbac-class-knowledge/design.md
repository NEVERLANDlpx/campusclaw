## Context

从空项目实现 CampusClaw 教学实验。需求以同目录 specs/auth-upload/spec.md 为准。

## Goals / Non-Goals

目标是账号登录、服务端授权、跨班拒绝、上传入库与可复现证据；非目标见 proposal.md。

## Decisions

1. 使用 Flask 3 / Jinja SSR、SQLite、bcrypt、Gunicorn，端口 8080。SQLite 位于 data/app.db。
2. 使用 Flask 默认签名 Cookie 会话，不使用 JWT。Cookie 名 campusclaw_session，HttpOnly、SameSite=Lax，生存期两小时。载荷含 user_id、role、class_id、auth_version 与 csrf_token；签名保证完整性，不提供加密。数据在客户端，验证与授权在服务端，这不是仅存随机 SID 的纯服务端会话。
3. SECRET_KEY 必须从环境变量注入，至少32字符；无值启动失败。密码使用 bcrypt。每次受保护请求重新查询 users，使用数据库角色和班级，且比较 auth_version。退出增加该版本，撤销同账号既有 Cookie。
4. 页面未认证重定向 /login；API 未认证返回401。写入操作检查角色与 CSRF，学生写入403。错误密码401，不泄露账号是否存在。
5. 所有材料列表、详情、知识正文查询包含可信 class_id 条件。跨班资源固定404，不透露是否存在。上传表单的 class_id 不参与授权。
6. 教师上传仅支持UTF-8 txt/md、最大2MiB、非空且无二进制控制字符。服务器生成 UUID 文件名，目录按班级分区。数据库只保存相对于上传根目录的路径（如 `1/<uuid>.md`），运行时再按当前 `UPLOAD_ROOT` 解析，避免 Windows 与 Linux 绝对路径漂移。文件保存后在同一 SQLite 事务插入 materials、knowledge_entries、lectures，任一步失败清理文件与回滚。删除使用同目录重命名暂存，再删除数据库记录；失败还原，成功清理。进程突发崩溃的跨文件系统/数据库原子性不属于本实验保证。
7. classes/users/lectures/assignments/assistants/skills 为六类核心结构；materials/knowledge_entries 为本次功能表。材料外键删除级联，知识记录与材料包含相同class_id约束。种子含双班、三账号和可区分资料；初始化幂等，不覆盖已有上传。
8. Compose 挂载 ./data 和 ./uploads；entrypoint先初始化，再启动单worker多线程Gunicorn。/health 无需登录，检查数据库结构，可用200、不可用503。启动后数据库故障仍可返回503，不重置数据。

## Data flow

登录表单 → bcrypt校验 → 写会话 → Set-Cookie → 浏览器请求携Cookie → 后端验证签名/期限/版本 → 读取用户当前角色班级 → 带班级条件查询。

上传表单 → 用户认证 → 教师权限 → CSRF → 文件检查 → 文件落盘 → 事务写材料、正文和讲义关联 → 201 → 本班列表刷新可见。

## Risks / Trade-offs

本地 HTTP 的 Cookie Secure 关闭；HTTPS 部署设置 COOKIE_SECURE=1。演示账号不可直接用于公共生产环境。SQLite适合课程单实例，不实现分布式会话。Docker运行验收须在安装Docker的机器执行。

## Migration Plan

首次运行创建结构和演示数据，重复初始化只补缺失账号与班级，不重建已有内容。已有结构迁移不在本次范围。

## Open Questions

无阻塞问题。未提供学生姓名/学号，不填写虚构个人信息。
