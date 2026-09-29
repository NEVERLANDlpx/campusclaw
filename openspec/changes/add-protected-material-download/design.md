## Context

既有auth-upload提供Signed Cookie、数据库实时角色/班级查询以及get_material(id,class_id)。本次复用这些边界，不建立平行认证逻辑。

## Goals / Non-Goals

提供权限可验证、原始字节一致的下载。非目标见proposal。

## Decisions

1. GET /api/materials/<int:mid>/download复用login_required。GET/HEAD都必须认证，认证失败返回401 JSON。
2. get_material使用WHERE m.id=? AND m.class_id=?，参数取g.user.class_id，不接收客户端class_id作为授权依据。本班教师/学生均可下载，写权限仍仅教师拥有。
3. 原文件路径仅取数据库记录。新记录的 `materials.file_path` 只保存相对于上传根目录的路径，如 `1/example.md`。运行时按当前 `UPLOAD_ROOT` 解析目标真实路径，必须在 `UPLOAD_ROOT/{可信class_id}` 的真实目录内；必须为普通文件。旧数据若仍含 Windows 或 Linux 绝对路径，只允许通过包含 `uploads/<class_id>/...` 且班级一致的安全迁移或兼容解析转换为相对路径。路径越界、缺失或不可读统一404，不回传本地路径。
4. Flask send_file以attachment返回原始文件，Content-Type为application/octet-stream；下载文件名使用已净化的原始文件名。响应继承Cache-Control:no-store及X-Content-Type-Options:nosniff。不支持公开uploads目录。
5. 下载是只读GET，不要求CSRF；浏览器自动携带会话Cookie。POST上传/删除仍校验角色和CSRF。未登录使用地址栏打开下载API收到401，不自动登录。
6. 不主动执行原文件、不把Markdown转成可执行HTML。原始文件下载保留UTF-8 BOM等原始字节，不能用数据库解析正文代替原文件。

## Risks / Trade-offs

已授权用户下载到本机后的副本无法通过服务器退出或删除追回；班级权限约束在线访问，不是数字版权管理。服务器上传目录应由应用独占写入；不保证恶意本地管理员同时修改文件导致的路径竞态。

## Migration Plan

无需数据库迁移。既有file_path有效且文件存在即可下载；目录迁移需同步修改文件路径或重新导入。

## Open Questions

无。
