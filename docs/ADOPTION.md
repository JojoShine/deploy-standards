# 项目接入

接入目标是让业务仓库拥有自己的应用与发布记录，同时复用固定版本的通用部署流程。先完成[README 中的生成步骤](../README.md#快速接入)，再按以下顺序接入。

## 1. 确定项目参数

在业务仓库记录业务 slug、GitHub owner/repo、环境名、域名、`BASE_PATH`、宿主机端口及外部 PostgreSQL 角色。`BASE_PATH` 为空表示根路径，或如 `/survey`；不得带尾斜杠。业务名同时决定镜像名和服务器目录，确定后不要随意更改。

生成器调用方式：

```sh
python3 tools/init-project.py \
  --business sample-survey \
  --output ../sample-survey \
  --standards-ref "$(git rev-parse HEAD)" \
  --owner JojoShine
```

从已检出并审阅的标准仓库运行。命令会复制 `templates/project` 和共享 `scripts`，替换模板变量并生成固定 SHA 的工作流调用。`--owner` 默认 `JojoShine`；采用其他组织时明确传入。不要将生成器指向已有非空业务目录；可先生成到临时目录，再有选择地合并文件。

## 2. 替换参考应用

模板的 Node 22 应用、SQL 迁移、初始化脚本和测试只演示完整发布接口。接入实际业务时：

1. 按**项目已安装的框架版本**和其官方文档实现构建、启动和健康检查，不把参考应用直接当成业务系统。
2. 保留 Dockerfile 的 `runtime`、`migrate` 目标，以及 `/app/bin/healthcheck`、`/app/bin/migrate`、`/app/bin/bootstrap` 接口。依赖锁文件应进入版本控制。
3. 用真实迁移工具替换示例 SQL。重复迁移、重复初始化必须安全；需要创建管理员时，仅首次创建，重复执行不覆盖账号密码。参考初始化只插入演示设置，不创建管理员。
4. 健康接口位于 `BASE_PATH + /healthz`，验证必要数据库能力；所有业务路由和静态资源也要兼容前缀。
5. 生产 Compose 保持独立、只使用镜像。应用角色和迁移角色分别注入，初始化凭据只给初始化任务。

参考项目可在开发机运行；临时 PostgreSQL 只出现在开发或 CI，不随生产包部署：

```sh
npm test
docker compose -f compose.dev.yaml up -d database
docker compose -f compose.dev.yaml run --build --rm migrate
docker compose -f compose.dev.yaml run --build --rm migrate /app/bin/bootstrap
docker compose -f compose.dev.yaml up --build -d app
curl --fail http://127.0.0.1:31001/healthz
docker compose -f compose.dev.yaml down
```

此命令使用模板的默认空 `BASE_PATH` 和端口 31001；如调整需同步 URL。`down` 保留开发数据卷。首次接入还应实际运行迁移和初始化各两次，并验证数据库权限、HTTP 健康和已有账号不被修改。

## 3. 配置 GitHub

生成的 `.github/workflows/{ci,release,deploy}.yml` 是业务仓库的调用方；标准仓库同名文件提供 `workflow_call` 接口。完整输入见[标准第 6 节](../STANDARD.md#6-工作流接口)。

- 将调用方提交到自己的仓库，启用 Actions。允许 CI 的 `GITHUB_TOKEN` 写入本仓库关联的 GHCR packages；按访问需求设置 package 可见性。服务器拉取私有镜像需预先配置只读凭据。
- PR 做检查与镜像验证，不推送。main 成功后保存 `candidate-<完整提交>` artifact，并输出镜像 digest；默认保留 90 天。将实际 CI 成功作为发布依据。
- Release 调用方在 `vX.Y.Z` 标签触发。先确认同一提交位于 main 且 CI 成功，再创建版本标签。Release 从成功候选提升 digest，不重新构建。
- Deploy 调用方从受信任 main 手动触发，填写已发布版本、环境、端口和公网健康 URL。GitHub secrets 配置 `SSH_HOST`、`SSH_USER`、`SSH_PRIVATE_KEY`、`SSH_KNOWN_HOSTS`，可选 `SSH_PORT`。known_hosts 从可信渠道核对，不能通过关闭检查解决连接失败。
- 标准仓库引用固定完整 SHA。更新标准前查看新版本变更，同时更新工作流引用和项目内共享脚本，经过项目 CI 后再发布。

不要把生产数据库 URL、管理员密码或 `.env.prod` 上传为 artifact。构建缓存只加速构建，不作为经过验证的发布候选。

## 4. 准备服务器

运维人员预先安装[标准要求的工具](../STANDARD.md#4-服务器与配置)，分配端口、创建外部 PostgreSQL 及独立角色，并准备 `/opt/<business>/shared/.env.prod`。模板的 `.env.prod.example` 用于列出键名；空值应由运维填写，不能原样部署。文件权限设为 `0600`，内容不能作为 shell 脚本执行。

检查迁移角色能管理目标 schema、应用角色能读写现有和新建业务对象，且应用没有不必要的 DDL 权限；通过应用实际连接测试。迁移角色创建对象后应由迁移或数据库管理员维护 grants/default privileges。备份客户端版本应兼容服务器，并先演练备份恢复。

按照 `nginx/site.conf.example` 审阅业务片段，放入 `/etc/nginx/business/<domain-id>/<business>.conf`，由该域名的 server block include。域名、TLS、`BASE_PATH` 与 `127.0.0.1:APP_PORT` 由运维配置并执行 Nginx 测试和加载。部署脚本不改 Nginx。

最后按[运行手册](OPERATIONS.md)执行首次部署，再显式运行初始化。将业务健康检查、数据备份和回滚演练加入项目交付检查。
