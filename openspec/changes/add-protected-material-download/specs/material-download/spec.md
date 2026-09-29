## Purpose

本班成员能够下载教学材料原文件，直接调用API也不能绕过认证与班级隔离。

## ADDED Requirements

### Requirement: Authenticated class-scoped download

系统 MUST 仅允许具有有效会话的本班teacher或student下载原文件，并 MUST 使用服务端可信班级过滤材料查询。

#### Scenario: Anonymous download
- **WHEN** 无有效会话请求GET或HEAD下载API
- **THEN** 返回401且不发送原文件字节

#### Scenario: Same-class teacher and student
- **WHEN** 教师A或学生A1下载A班材料
- **THEN** 返回200，Content-Disposition包含attachment，响应字节与原文件完全相同
- **AND** 不要求教师写权限或CSRF令牌

#### Scenario: Cross-class request
- **WHEN** A班用户请求B班材料下载，或在查询参数中指定class_id=2
- **THEN** 对B班材料返回404；对A班材料仍按A班授权
- **AND** 不返回B班文件内容、名称或存储路径

#### Scenario: Unavailable resource
- **WHEN** 材料ID不存在或对应原文件缺失
- **THEN** 返回404，不暴露服务器路径

#### Scenario: Revoked login
- **WHEN** 已退出账号重用旧会话请求下载
- **THEN** 返回401

### Requirement: Private file delivery

系统 MUST 通过受保护下载路由传输文件，MUST NOT 将uploads作为公共静态目录。

#### Scenario: Path outside allowed class directory
- **WHEN** 数据库路径或符号链接解析到本班上传目录以外
- **THEN** 下载返回404，不发送目标文件

#### Scenario: Portable stored path
- **WHEN** 材料由 Windows 本地或 Linux Docker 环境创建
- **THEN** materials.file_path MUST 保存为上传根目录内的相对路径
- **AND** 下载时 MUST 按当前运行环境的上传根目录解析该相对路径
- **AND** 旧的 Windows 或 Linux 绝对路径只有在可安全转换为同班相对路径且文件存在时才可迁移

#### Scenario: Attachment response
- **WHEN** 通过授权并成功下载
- **THEN** Content-Type为application/octet-stream，响应含Cache-Control:no-store及X-Content-Type-Options:nosniff
- **AND** 页面向本班教师和学生显示下载按钮

#### Scenario: Direct static path
- **WHEN** 用户尝试通过/uploads/...或/static/uploads/...访问材料文件
- **THEN** 不能下载原文件
