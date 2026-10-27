## 1. 规约与依赖
- [x] 1.1 增加 0930 Token 认证四件套，明确 API Bearer 边界。
- [x] 1.2 增加维护版 JWT 库依赖，并保持密钥仅来自环境变量。

## 2. 后端实现
- [x] 2.1 新增 `POST /api/auth/token`，成功返回 JWT、类型、过期秒数和非敏感用户信息。
- [x] 2.2 实现 Bearer Token 校验，验证 HS256、exp、issuer、用户 ID 和 auth_version。
- [x] 2.3 将 `/api/me` 与材料相关 `/api` 接口统一为 Bearer Token 认证，确保无 Token、无效、篡改、过期和仅 Session Cookie 均返回401。
- [x] 2.4 保持服务端班级隔离和角色授权，客户端 `class_id` 不参与授权。

## 3. 前端实现
- [x] 3.1 登录页调用 Token 登录接口，并保存短期 token。
- [x] 3.2 材料列表、上传、删除、下载等 Fetch/XHR 实际附带 Authorization。
- [x] 3.3 登出和401时清理前端 token；下载改为带 Authorization 的 fetch + Blob。
- [x] 3.4 隔离登录页与受保护页面初始化，确保 Session/Token 不一致时只执行一次恢复并稳定停留在登录页。

## 4. 验收与文档
- [x] 4.1 补充自动化测试覆盖正确/错误登录、无/坏/篡改/过期 token、仅 Session Cookie、班级隔离、教师学生权限、登出清理和上传下载。
- [ ] 4.2 运行 pytest；可用 Docker 环境中执行 build 验证且不删除 volume。
- [x] 4.3 更新 README，加入 0930 Token 登录认证、F12 截图步骤、验证命令和与旧 Session Cookie 的区别。
- [x] 4.4 增加登录页稳定性、混合认证状态、注销 Session 与旧 Token 失效的回归测试。

实际验证：2026-09-30 `python -m pytest -q tests -p no:cacheprovider` 为 59 passed, 1 skipped；三个 OpenSpec change strict valid。`docker compose config` 可解析；`docker compose build` 未通过，因为 Docker Desktop Linux Engine pipe 不存在，当前机器 Docker Engine 未运行，未执行容器构建或启动，也未删除 volume。
