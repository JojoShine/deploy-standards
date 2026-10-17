# 项目部署约定

本文是后续项目统一沿用的部署规范。各项目根据业务实现自己的 Dockerfile、Compose 和 GitHub Actions；无需接入通用部署框架、生成器或共享脚本库。接入已有项目时单独审阅差异，不直接修改现有生产环境。

## 1. 统一原则

- GitHub Actions 负责检查、构建镜像，并推送到 GHCR。
- 生产服务器只下载部署配置、拉取镜像和运行容器，不上传业务源码，不在服务器安装业务依赖或构建镜像。
- 应用运行、数据库迁移、首次初始化分开执行；构建和应用启动时不自动迁移或初始化。
- 生产使用外部 PostgreSQL；数据库地址和凭据由环境配置提供。
- 公网入口统一由宿主机 Nginx 提供，应用端口仅绑定本机。

## 2. 文件与目录

业务仓库统一使用：

```text
Dockerfile
.dockerignore
compose.prod.yaml              # 独立的生产配置，只使用镜像
compose.dev.yaml               # 如需容器开发环境，使用此文件
.env.prod.example              # 仅列键名和示例，不含真实秘密
.github/workflows/ci.yml        # 检查、构建、验证及候选镜像发布
.github/workflows/release.yml   # 版本镜像与部署文件发布
nginx/business.conf.example    # 独立业务片段，供现有 server 加载
```

生产文件统一叫 `compose.prod.yaml`，不使用不同命名，也不依赖与开发配置合并。服务器统一放在 `/opt/<business>`：

```text
/opt/<business>/
  compose.prod.yaml
  .env.prod
  .env.bootstrap               # 需要初始化秘密时单独提供
  backups/
```

环境文件权限为 `600`，仅部署人员可读取。不提交真实环境文件、凭据和数据库备份。配置按数据读取，不通过 `source` 或 `eval` 执行。

## 3. Docker 构建与数据库任务

一个 Dockerfile 固定提供两个最终目标：

| 目标 | 镜像内容 | 执行时机 |
| --- | --- | --- |
| `runtime` | 编译后的应用和必要运行依赖 | 持续运行应用 |
| `migrate` | 对应版本的迁移、初始化文件及执行工具 | 部署时显式运行一次性任务 |

不为初始化再构建第三个镜像。统一入口由项目实现：

- `/app/bin/healthcheck`：检查应用及必要数据库连接；失败返回非零状态。
- `/app/bin/migrate`：执行尚未执行的生产迁移，重复运行安全。
- `/app/bin/bootstrap`：首次初始化，重复运行不覆盖已有账号密码或业务数据。

这些是项目需要实现的接口，不代表框架自带命令。入口可调用项目实际使用的迁移工具。运行镜像使用非 root 用户；基础镜像声明明确版本，依赖使用锁文件。

应用监听 `0.0.0.0:8080`。健康接口统一为 `/healthz`；有路径前缀时为 `<BASE_PATH>/healthz`。例如前缀 `/surveys`，接口为 `/surveys/healthz`。前缀需要贯穿应用路由、静态资源、健康检查和 Nginx；框架需要构建时确定前缀时，必须在 CI 构建时传入。

## 4. 镜像命名与版本

`business` 使用稳定的小写短横线名称，例如 `qingwen`；GHCR owner 使用小写。

| 用途 | 格式 |
| --- | --- |
| 应用镜像 | `ghcr.io/<owner>/<business>-app` |
| 迁移镜像 | `ghcr.io/<owner>/<business>-migrate` |
| 提交标签 | `sha-<完整提交SHA>` |
| 正式版本标签 | `v<主版本>.<次版本>.<修订版本>`，例如 `v1.2.3` |
| 生产实际引用 | `ghcr.io/<owner>/<business>-app@sha256:<digest>` |

同一正式版本的应用、迁移镜像必须来自同一提交。不同构建产物需要区分标签，例如不同路径前缀使用 `v1.2.3-surveys` 与对应的 SHA 变体标签；在项目中明确变体名称和构建参数。

提交标签和正式版本标签不得覆盖。正式发布复用已经通过 CI 的镜像摘要，增加版本标签，不重新构建。生产配置固定 digest，不使用 `latest` 等浮动引用。镜像记录来源仓库、提交、版本和许可证信息。

## 5. GitHub CI 与发布

固定流程：

1. PR：安装锁定依赖，执行项目必要的检查、测试、构建，验证两个镜像；不发布生产镜像。
2. main：完成相同验证，使用隔离数据库实际验证迁移、重复初始化、应用启动和健康检查，再将验收的镜像推送 GHCR，记录提交与 digest。
3. `vX.Y.Z` 标签：确认该提交在 main 且 CI 成功，将对应镜像提升为版本标签，发布匹配的部署文件和镜像 digest。
4. 服务器：获取该版本的配置，填入环境参数，拉取准确镜像并部署。

GitHub Release 附带该版本的 `compose.prod.yaml`、环境配置示例、Nginx 示例及包含提交和镜像 digest 的版本说明；不得混用 main 的配置与旧版本镜像。

使用最小必要的 GitHub Actions 权限：检查只读，推送镜像才授予 `packages: write`，创建 Release 才授予 `contents: write`。第三方 Action 固定完整提交 SHA。构建过程不使用生产数据库或生产凭据。

GHCR 公开镜像允许服务器匿名拉取；私有镜像使用只读凭据。部署前确认包的实际可见性。服务器自动部署为可选项；采用时使用受保护环境、预先核对的 SSH 主机指纹和专用部署密钥。

## 6. Compose 与端口

生产 Compose 固定 `app` 和一次性 `migrate` 服务。下面是结构示例，项目按实际需要补充应用环境变量：

```yaml
services:
  app:
    image: ${APP_IMAGE:?APP_IMAGE is required}
    restart: unless-stopped
    init: true
    environment:
      PORT: "8080"
      BASE_PATH: ${BASE_PATH:-}
      DATABASE_URL: ${DATABASE_URL:?DATABASE_URL is required}
    ports:
      - "127.0.0.1:${APP_PORT:?APP_PORT is required}:8080"
    healthcheck:
      test: [CMD, /app/bin/healthcheck]
      interval: 10s
      timeout: 5s
      start_period: 15s
      retries: 12
  migrate:
    image: ${MIGRATE_IMAGE:?MIGRATE_IMAGE is required}
    profiles: [ops]
    restart: "no"
    environment:
      DATABASE_URL: ${MIGRATION_DATABASE_URL:?MIGRATION_DATABASE_URL is required}
    command: [/app/bin/migrate]
```

- Web 应用容器端口固定 `8080`；宿主机端口从 `31000–31999` 分配，在各项目文档登记，避免冲突。已有项目的端口另行迁移，不直接替换。
- 应用端口必须明确绑定 `127.0.0.1`，不能省略绑定地址。
- 迁移、初始化和无 HTTP 入口的 Worker 不发布宿主机端口；后续增加服务时按这个原则处理。
- 生产 Compose 不含 `build`、源码挂载或数据库服务；不设置跨项目冲突的固定 `container_name`。
- Compose 项目名固定为 `<business>-<environment>`，升级时保持不变，例如 `qingwen-production`。

环境配置至少包含 `COMPOSE_PROJECT_NAME`、`APP_IMAGE`、`MIGRATE_IMAGE`、`APP_PORT`、`BASE_PATH`、`DATABASE_URL` 和 `MIGRATION_DATABASE_URL`。应用只接收运行角色凭据，迁移接收具有必要 DDL 权限的迁移角色凭据；初始化秘密仅传给初始化任务。

容器访问宿主机数据库时不能使用容器自身的 `127.0.0.1`。如采用 `host.docker.internal`，在相关服务配置 `extra_hosts: ["host.docker.internal:host-gateway"]`，并按实际 Docker 子网配置 PostgreSQL 监听和访问权限。

## 7. Nginx 独立业务配置

每个业务一个独立 `.conf` 文件，由对应域名已有的 `server` 块加载。目录约定：

```text
/etc/nginx/business/<domain-id>/<business>.conf
```

例如 `tbtparent.me` 使用目录 `/etc/nginx/business/tbtparent-me`，轻问配置文件为 `/etc/nginx/business/tbtparent-me/qingwen.conf`。在该域名现有 HTTPS `server` 块内添加一次：

```nginx
include /etc/nginx/business/tbtparent-me/*.conf;
```

业务片段只定义该业务的 `location`，不再声明 `server`、`listen`、域名或证书。域名、TLS 证书和 HTTPS 跳转继续在原有站点配置中维护。

以 `/surveys` 为入口、应用端口 `31001` 为例：

```nginx
# /etc/nginx/business/tbtparent-me/qingwen.conf
location = /surveys {
    return 308 /surveys/$is_args$args;
}

location ^~ /surveys/ {
    # 不带尾斜杠，保留 /surveys/ 路径前缀。
    proxy_pass http://127.0.0.1:31001;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    client_max_body_size 10m;
}
```

这里的应用必须支持 `/surveys` 前缀，上传大小按业务需求调整。应用使用转发头时，只信任受控代理。通过其他代理或 CDN 接入时，先核对真实协议与客户端地址的传递规则。

根路径业务使用 `location /`，仍保持独立业务文件。配置前检查既有 `location` 是否冲突；不得覆盖其他业务或重复加载同一片段。

修改后先检查，通过才平滑加载：

```sh
sudo nginx -t && sudo systemctl reload nginx
```

容器升级通常无需改 Nginx。域名、入口或端口发生变化时才修改对应业务片段，保留修改前配置用于恢复。

## 8. 部署顺序与回滚

首次部署前准备 Docker Engine、Compose v2、外部 PostgreSQL、所需数据库客户端、业务目录、环境文件和 Nginx。确认运行角色与迁移角色的实际权限，不仅验证能否连接。

每次发布顺序固定为：**核对版本 → 备份数据库和当前配置 → 拉取镜像 → 执行迁移 → 启动应用 → 检查健康**。数据库备份需检查成功，并定期在隔离环境演练恢复。

在 `/opt/<business>` 中执行，统一使用同一生产文件和环境文件：

```sh
docker compose --env-file .env.prod -f compose.prod.yaml pull
docker compose --env-file .env.prod -f compose.prod.yaml run --rm --no-deps migrate
# 仅在迁移成功后继续。
docker compose --env-file .env.prod -f compose.prod.yaml up -d --no-build --wait app
docker compose --env-file .env.prod -f compose.prod.yaml ps
curl --fail https://<domain>/<base-path>/healthz
```

健康 URL 按实际入口填写；无前缀时为 `https://<domain>/healthz`。上面的命令逐步执行，前一步失败即停止。首次部署成功后，如业务需要，再显式运行初始化：

```sh
docker compose --env-file .env.prod -f compose.prod.yaml run --rm --no-deps migrate /app/bin/bootstrap
```

如初始化需要账号密码，项目必须补充仅供初始化任务使用的环境注入方式，从 `.env.bootstrap` 读取；上面的基础示例没有自动加载该文件。禁止将真实密码直接写在命令行或持续传给应用服务。

迁移失败时保留旧应用；应用健康失败时恢复上一版本的 Compose 和镜像 digest，再检查健康。迁移必须尽量向后兼容，先加结构、再切应用、最后另发版本移除旧结构。应用回滚不自动恢复数据库，破坏性迁移需单独安排恢复方案。

运维需保留当前与上一版本配置、镜像 digest 和数据库备份，并维护日志轮转、磁盘空间、备份保留及证书续期。默认是单实例替换，允许短暂中断；需要零停机时在对应项目单独设计。
