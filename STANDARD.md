# 部署标准 v1.0

本文中的“必须”是接入约束，“应”是默认建议。标准负责发布和运行接口；业务仓库负责应用行为、依赖、数据库设计及真实环境参数。参考模板不替代业务系统实现。

## 1. 构建与运行边界

1. 源码检出、依赖安装、测试、编译和镜像构建必须在开发机或 CI 完成。服务器不得执行源码构建、`npm install` 或以源码挂载方式运行生产应用。
2. `compose.prod.yaml` 必须是可独立运行的生产文件，只引用已构建镜像，不依赖开发 Compose 的合并结果；不得包含 `build`、源码挂载或数据库容器。开发使用独立 `compose.dev.yaml`。
3. Dockerfile 必须提供 `runtime` 和 `migrate` 两个目标。运行镜像只保留运行必需内容；迁移镜像携带匹配本次应用版本的迁移及初始化工具。v1 仅支持 `linux/amd64`。
4. 应用必须监听容器内 `0.0.0.0:8080`，提供 `/app/bin/healthcheck`；该命令探测 `BASE_PATH + /healthz`。健康接口应能反映应用及必需数据库连接是否可用，不返回秘密。
5. 迁移入口为 `/app/bin/migrate`，初始化入口为 `/app/bin/bootstrap`。不得在镜像构建或应用启动入口隐式执行二者。初始化必须幂等，重复执行不得重置已有账号密码。
6. 生产 `app` 使用 `restart: unless-stopped`；`migrate` 使用 `profiles: [ops]`、`restart: "no"`，没有端口，通过一次性任务显式运行。后台 worker 如有需要单独定义服务，不发布无用途端口。

[Docker 多阶段构建](https://docs.docker.com/build/building/multi-stage/)支持具名目标；[Compose profiles](https://docs.docker.com/compose/how-tos/profiles/)用于按需启用运维任务。显式指定服务仍可运行该任务，因此 profile 不代替权限控制。

## 2. 命名、版本和镜像

| 对象 | 约定 | 示例 |
| --- | --- | --- |
| 业务标识 | 小写短横线 slug | `sample-survey` |
| 环境 | 明确命名，生产默认 `production` | `production`、`staging`、`development` |
| Compose 项目名 | `<business>-<environment>`，跨版本稳定 | `sample-survey-production` |
| 运行镜像 | `ghcr.io/<lowercase-owner>/<business>-app` | `ghcr.io/jojoshine/sample-survey-app` |
| 工具镜像 | `ghcr.io/<lowercase-owner>/<business>-migrate` | `ghcr.io/jojoshine/sample-survey-migrate` |
| 不可覆盖候选标签 | `sha-<完整40位提交>` | 每个提交一个候选 |
| 版本 | `vMAJOR.MINOR.PATCH` | `v1.2.3` |
| 部署引用 | 完整镜像名加 `@sha256:<64位十六进制>` | 发布包内只使用 digest |

构建时需要区分应用变体时，`app` 候选与版本标签可加同一 `-<variant>` 后缀；`migrate` 保持无变体标签。`BASE_PATH` 是空串或无尾斜杠的绝对路径，必须在候选构建、镜像健康检查、发布元数据和 Nginx 配置中保持一致；更改构建参数需要新候选，不能冒充旧产物。

`main` 只发布候选 SHA 标签；PR 不推送镜像。重复处理已发布的 SHA 必须复用可验证的原候选或失败，不得静默覆盖。版本发布只允许提升 `main` 上经过成功 CI 的同一提交、同一 digest，不得重新构建。即使内容相同，重建也不是“已测试的同一个镜像”。提升工具不得意外包裹为新索引导致 digest 改变，提升后必须核对。

镜像应携带 OCI source、revision、version、licenses 标签。GHCR 的认证和访问遵循[官方容器仓库文档](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)。`latest` 等浮动标签不得作为生产发布依据。

## 3. 发布包与标准版本绑定

每个 GitHub Release 提供 `deploy-vX.Y.Z.tar.gz`，只有一个同名版本目录，至少包含：

```text
vX.Y.Z/
  compose.prod.yaml
  release.env
  release.json
  SHA256SUMS
  scripts/{lib,deploy,bootstrap,rollback}.sh
  scripts/lib.py
  nginx/site.conf.example
```

- `release.env` 只含 `APP_IMAGE`、`MIGRATE_IMAGE`，且均为完整 GHCR digest 引用。解析它作为数据，不得通过 shell `source` 执行。
- `release.json` 包含 `standard_version: "1.0"`、`business`、`version`、完整 `commit`、`platform: "linux/amd64"`、`base_path`，以及 `images.app`、`images.migrate` 的 `ref` 与候选 `tag`；镜像引用必须与 `release.env` 完全对应。
- `SHA256SUMS` 覆盖包内除自身以外的全部文件。路径必须相对、无逃逸、无不受信任链接；校验不得只验证清单中一个子集而遗漏新增文件。
- 镜像、Compose、脚本、Nginx 示例和标准引用必须来自同一版本对应的发布输入，不得用新 `main` 文件搭配旧镜像。
- 校验和用于检测包内容变化，不代替来源认证；必须从预期仓库的受信任 Release 获取，再核对版本、提交、候选与 digest。

共享脚本通过项目生成器进入业务仓库，调用方工作流固定完整标准提交 SHA。标准升级须显式审阅；可复用工作流不得引用可移动的 `main` 或版本标签作为固定依据。[GitHub 可复用工作流文档](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows)说明调用接口和提交 SHA 引用方式。

## 4. 服务器与配置

```text
/opt/<business>/
  shared/.env.prod
  shared/.env.bootstrap       # 需要初始化秘密时单独配置
  releases/vX.Y.Z/
  current -> releases/vX.Y.Z
  previous -> releases/vA.B.C
  backups/
  logs/
```

生产密钥由运维人员在服务器手动配置，权限 `0600`，目录仅对部署操作者及必要管理员开放。不得提交 `.env.prod`、初始化凭据、数据库备份或登录令牌。环境文件作为受约束的数据解析，不是 shell 脚本。

`.env.prod` 必须提供 `BUSINESS`、`ENVIRONMENT`、`COMPOSE_PROJECT_NAME`、`APP_PORT`、`DATABASE_URL`、`MIGRATION_DATABASE_URL`、`PUBLIC_HEALTH_URL`；可提供 `BACKUP_DATABASE_URL`（省略或留空时默认迁移 URL）与 `HEALTH_TIMEOUT`（默认 120 秒）。`PUBLIC_HEALTH_URL` 包含实际域名及 `BASE_PATH + /healthz`。非秘密构建参数应留在版本配置，不藏入服务器环境。

PostgreSQL 由外部服务提供。应用角色和迁移角色必须分开：应用只具备业务运行需要的 schema 使用、表读写及序列权限；迁移角色具备迁移所需 DDL 权限。二者均不应是 superuser。迁移创建的对象必须向应用角色授予现有对象及后续对象所需权限。上线前以两个实际连接分别检查角色身份、schema 权限、应用查询和迁移执行；“可以连接”不代表权限正确。备份角色需能读取全部待备份数据，受 RLS 影响时必须单独验证备份完整性。

运行服务只取得 `DATABASE_URL`；迁移和初始化只取得所需迁移凭据。初始化额外秘密使用 `shared/.env.bootstrap`，仅接受 `BOOTSTRAP_` 开头的大写键，仅注入一次性初始化任务，不能持续注入应用或进入发布包。

宿主机必须具备 Bash、Python 3、Docker Engine、Docker Compose v2、`flock`、`curl`、兼容数据库版本的 `pg_dump` 与 `pg_restore`。脚本不安装依赖、不创建数据库、不修改 Nginx。

## 5. 网络与 Nginx

公网 Web 服务使用 `127.0.0.1:${APP_PORT}:8080`，默认分配 `31000–31999`。不得省略绑定地址，也不得改成 `0.0.0.0` 对外暴露。数据库、worker、迁移任务不发布宿主机端口。具体登记方式见[端口约定](docs/PORTS.md)。[Docker 端口发布文档](https://docs.docker.com/engine/network/port-publishing/)说明回环地址绑定行为。

TLS 和域名路由由宿主机 Nginx 管理。通用示例路径为 `/etc/nginx/business/<domain-id>/<business>.conf`，`domain-id` 为稳定的域名配置标识（例如 `example-com`），由对应 server block include 业务片段；实际加载关系以主机配置为准。项目保留 `nginx/site.conf.example`，由人工填写真实域名、端口、路径和证书后审查、测试、加载。共享部署脚本不得直接覆盖现有虚拟主机配置。

## 6. 工作流接口

| 可复用工作流 | 主要输入 | 输出或作用 |
| --- | --- | --- |
| `ci.yml` | `business`、`standard-ref`；可选 `checks`、`build-context`、`dockerfile`、`base-path`、`variant`、`postgres-image` | 测试实际镜像；成功 main 输出 `app-image`、`migrate-image`、`commit` 及候选元数据 |
| `release.yml` | `business`、`standard-ref`；可选 `base-path`、`variant` | 从同一提交成功 CI 的候选提取 digest，提升版本标签，发布部署包 |
| `deploy.yml` | `business`、`version`、`public-health-url`、`app-port`、`standard-ref`；`environment` 默认 `production` | 下载本业务仓库的版本包，仅传输部署文件并调用包内脚本 |

`ci` 默认检查命令 `npm test`、构建上下文 `.`、Dockerfile `Dockerfile`、临时 PostgreSQL `postgres:16-alpine`。候选 artifact 名为 `candidate-<完整提交>`，保留 90 天；发布必须找到该提交成功 CI 的候选，不能接受任意调用者直接提供的 digest。候选过期应按审阅流程恢复可验证的产物证据，不能绕过验证或覆写同一 SHA。

部署密钥为 `SSH_HOST`、`SSH_USER`、`SSH_PRIVATE_KEY`、`SSH_KNOWN_HOSTS`，可选 `SSH_PORT` 默认 22。只能由受信任的 main 调用部署；使用预置 known_hosts 验证主机，不能关闭校验。生产部署应使用 GitHub environment 的访问控制。权限默认 `contents: read`；仅构建和提升授予 `packages: write`，Release 另需 `contents: write`。禁止 `pull_request_target` 执行不受信任代码。main 发布任务不得在半途中被后续运行取消。

## 7. 发布、失败与生命周期

服务器统一接口：

```sh
bash RELEASE_DIR/scripts/deploy.sh PROJECT_ROOT RELEASE_DIR
bash PROJECT_ROOT/current/scripts/bootstrap.sh PROJECT_ROOT
bash PROJECT_ROOT/current/scripts/rollback.sh PROJECT_ROOT
```

`PROJECT_ROOT`、`RELEASE_DIR` 是绝对路径；候选必须安全解压到 `PROJECT_ROOT/releases/<version>`，目录名与元数据版本一致。脚本不会搬移目录；`current`、`previous` 只能指向本项目 releases 内的版本目录。部署必须加锁串行，验证配置和包、拉取准确 digest、使用宿主机 `pg_dump` 创建 custom 格式备份并以 `pg_restore --list` 检查，然后执行一次迁移，再替换应用并检查容器及公网健康。全部通过才原子更新 `current`、`previous`。

迁移失败必须停止，不启动候选应用；应用替换前失败保持原 current。应用或公网健康失败，应重建旧版本应用配置与镜像；不得反向执行迁移或自动恢复数据库。首次部署失败不得伪造 current。失败恢复本身如失败，应停止并明确报告，交由运维处置。

镜像拉取失败时，默认停止。如果采用本地缓存应急路径，必须先从官方仓库取得预期 digest，再核对本地镜像准确匹配；不得通过镜像大小、旧标签或第三方镜像站推断一致。无法确认官方 digest 时停止。

迁移必须采用 expand/contract：先添加兼容结构，完成应用切换和回滚窗口后，再另发版本移除旧结构。数据库不兼容时，应用回滚可能失败，应停止自动操作；备份恢复是独立、人工确认的数据恢复流程。备份清单校验不等于已证明可恢复，应在隔离数据库定期演练。

运维人员负责磁盘监控、日志轮转、备份保留、离机备份、凭据轮换和证书续期。清理镜像或发布目录前，保留 current、previous 及回滚窗口所需内容。单实例替换可能中断；需要零停机、蓝绿或多机部署的项目应另行设计，不能以本标准默认流程承诺。

## 8. 例外与升级

超出默认端口段、增加独立服务或采用其他运行时，应在业务仓库记录差异、原因、验证方式、负责人及回退方式。会破坏共享脚本或元数据契约的改动需要先更新标准版本，不能私自修改后继续宣称兼容 v1。无需为单个项目引入额外审批系统；在版本审阅中清楚记录即可。
