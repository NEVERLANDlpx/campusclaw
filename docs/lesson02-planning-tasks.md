## 1. 骨架与规约
- [ ] 1.1 完成README三行、配置及四件套。verify: 文件存在且范围一致。
- [ ] 1.2 Flask应用和依赖。verify: 可导入应用，缺少密钥拒绝启动。
## 2. 数据
- [ ] 2.1 八张领域/业务表、双班三账号。verify: SQLite查表及bcrypt验证。
- [ ] 2.2 幂等种子。verify: 重复初始化不覆盖或重复材料。
## 3. 登录
- [ ] 3.1 表单、会话、/api/me、退出。verify: 三账号成功、错误密码401、退出后Cookie失效。
- [ ] 3.2 受保护页面与API。verify: 未登录302/401、损坏和过期Cookie拒绝。
## 4. 权限与隔离
- [ ] 4.1 教师写学生读。verify: 学生上传删除403且无副作用。
- [ ] 4.2 列表、详情和删除班级过滤。verify: 跨班404、伪造class_id无效。
## 5. 上传
- [ ] 5.1 合法上传入库。verify: 文件、材料、知识一致且同班学生可见。
- [ ] 5.2 非法文件与数据库失败回滚。verify: 400/413/503且无新增文件/记录。
- [ ] 5.3 删除与CSRF。verify: 教师同班删除成功，无CSRF写入403。
## 6. 部署
- [ ] 6.1 Dockerfile、Compose、.env.example、entrypoint。verify: 配置完整且端口/目录一致。
- [ ] 6.2 GET /health。verify: 无认证200、库不可读503。
- [ ] 6.3 真实Compose构建启动及容器重建持久性。verify: Docker机器执行README验收。
## 7. 收尾
- [ ] 7.1 openspec validate add-auth-rbac-class-knowledge --strict。verify: 官方CLI退出0。
- [ ] 7.2 真实HTTP采集、截图及报告。verify: 登录响应来自运行服务，截图来自浏览器。
