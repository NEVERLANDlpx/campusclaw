## Why

新增作业要求解释文件下载权限并能在真实系统验证。当前系统只展示解析正文，没有返回原文件的接口。本变更补足按班级授权的原文件下载，同时提供后端接口直接访问和上传类型限制的证据。

## What Changes

- 新增 GET /api/materials/{id}/download，已登录教师和学生可下载本班材料。
- 详情页为本班成员提供“下载原文件”按钮。
- 下载先校验会话和班级，再查询数据库记录并确认文件位于本班上传目录内；未登录401，跨班/不存在/文件缺失404。
- 下载使用附件响应，不暴露文件系统路径，不把uploads映射成公共静态目录。
- 补充三项作业说明、真实HTTP记录、下载字节一致性及权限验收。

## Capabilities

### New Capabilities
- `material-download`: 使用现有身份认证和班级边界下载原始材料。

### Modified Capabilities
无。现有auth-upload的接口行为保持不变。

## Non-goals

不新增PDF、Word、Excel、图片解析，不新增公开分享链接、匿名下载或对象存储签名链接。上传仍只支持UTF-8 txt/md。

## Impact

修改Flask路由、详情模板、README，增加下载验收与作业材料；数据库结构不变。
