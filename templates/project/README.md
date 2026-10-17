# __BUSINESS__

这是 Node 22 / PostgreSQL 16 的部署起点：包含可运行的 HTTP 参考程序、镜像、数据库操作和固定标准版本的工作流。请用真实业务代码替换参考程序；它不是已经实现的业务系统。标准工具仓库：[JojoShine/deploy-standards](https://github.com/JojoShine/deploy-standards)，固定版本 `__STANDARDS_REF__`，业务仓库所有者 `__OWNER__`。

## 本地开发

不需要安装 npm 依赖。Node 22 下运行：

```sh
npm test
npm run check
npm start
```

程序监听 `0.0.0.0:8080`，提供 `/`、`/healthz` 和 `/version`。`BASE_PATH=/starter npm start` 会将这些路由移至 `/starter/`、`/starter/healthz` 和 `/starter/version`。`BASE_PATH` 为空或由字母、数字、下划线和连字符组成的绝对路径，不带末尾斜线。`APP_VERSION` 用于版本响应，CI 通过同名镜像构建参数写入提交号。启动、构建和健康检查不连接数据库；请根据实际业务补充数据库就绪检查。

可选的完整本地容器环境：

```sh
docker compose -f compose.dev.yaml up -d --wait database
docker compose -f compose.dev.yaml run --build --rm migrate
docker compose -f compose.dev.yaml run --rm migrate /app/bin/bootstrap
docker compose -f compose.dev.yaml up -d --build app
curl --fail http://127.0.0.1:31001/healthz
```

开发环境的数据库和密码仅供本地使用。停止环境运行 `docker compose -f compose.dev.yaml down`，保留数据卷；不要将开发配置复制到生产环境。

## 镜像与数据库

`docker build --target runtime` 生成应用镜像，`docker build --target migrate` 生成数据库工具镜像。应用以非 root 用户监听 8080；工具使用 PostgreSQL 16 的 `psql`，通过镜像内的 Python 标准库将 URL 转换成 libpq 环境变量。两个操作入口分别为 `/app/bin/migrate` 和 `/app/bin/bootstrap`。`DATABASE_URL` 通过环境传入工具，连接凭据不会出现在命令参数中。

迁移创建 `app_schema_migrations` 版本记录和 `starter_settings` 演示表。初始化仅插入缺失的 `welcome` 键，不修改已有值，也不创建或重置账号密码。两者可重复执行并使用同一事务锁串行化；初始化前必须先迁移。开发真实迁移时保留历史，使用与旧版应用兼容的 expand/contract 变更，禁止将破坏性数据库回退当成应用回滚。

## CI、发布和生产

三个调用工作流固定到同一标准 SHA。PR 只验证；main 验证后发布 `<business>-app` / `<business>-migrate` 的提交镜像；`vX.Y.Z` 标签提升已通过 CI 的同一镜像摘要并发布部署包。修改标准版本时，同时更新三个工作流的 `uses` 和 `standard-ref`。子路径或变体发布时，CI 与 Release 的 `base-path` / `variant` 必须一致，服务器脚本从发布元数据读取 `base_path` 并传给应用，无需在 `.env.prod` 重复配置。

生产仅使用 `compose.prod.yaml` 和发布包中的摘要镜像；不在服务器构建源码，不启动数据库容器。先由管理员准备外部 PostgreSQL 和 `/opt/__BUSINESS__/shared/.env.prod`（参考 `.env.prod.example`，权限 600）。应用用 `DATABASE_URL`，迁移用权限更高的独立 `MIGRATION_DATABASE_URL`；备份可用独立 `BACKUP_DATABASE_URL`。必填连接凭据和公网健康地址示例均留空，需要自行填入。

`APP_IMAGE` 和 `MIGRATE_IMAGE` 来自发布包的 `release.env`，必须是 `ghcr.io/...@sha256:...` 完整摘要引用；公共端口仅绑定 `127.0.0.1:${APP_PORT}:8080`，默认分配区间 31000–31999。工具服务只在 `ops` profile 中运行，不开放端口，不自动重启。脚本会验证镜像摘要和 Compose 配置，禁止手动把可变标签作为生产输入。

部署账户需要 Bash、Python 3、Docker Compose v2、flock、curl，以及兼容数据库服务器的 `pg_dump` / `pg_restore`。脚本从生成项目的 `scripts/` 目录提供：

```sh
scripts/deploy.sh /opt/__BUSINESS__ /opt/__BUSINESS__/releases/v1.0.0
scripts/bootstrap.sh /opt/__BUSINESS__
scripts/rollback.sh /opt/__BUSINESS__
```

初始化只在管理员明确调用时执行，应用启动和部署不执行初始化。此参考初始化没有额外凭据；如业务以后需要一次性秘密，放在 `shared/.env.bootstrap`（权限 600），仅注入工具任务。应用回滚恢复上一镜像与配置，可能短暂停机，不恢复数据库。

手动 Deploy 工作流仅允许从 main 运行。配置 `SSH_HOST`、`SSH_USER`、`SSH_PRIVATE_KEY`、`SSH_KNOWN_HOSTS`，以及可选 `SSH_PORT`；服务器秘密文件预先存在，工作流只上传发布部署包。需要的话，在 GitHub 环境上设置人工审批。

`nginx/site.conf.example` 是 location 片段，安装到 `/etc/nginx/business/<domain-id>/__BUSINESS__.conf` 并包含在域名已有 server 块内；不要重复声明域名 server。将 upstream 端口改为实际 `APP_PORT`，子路径部署时将 location 改成相同前缀（如 `/starter/`）。`proxy_pass` 不带末尾斜线，以保留传给应用的路径。TLS、nginx 校验和重载由管理员执行，部署脚本不会修改 nginx。
