# 发布与运行手册

适用 Linux、Docker Compose v2、外部 PostgreSQL。部署操作者需要访问项目目录、Docker 及备份工具。修改 Docker 运行环境通常拥有很高权限，应使用专用部署身份。完整约束见 [STANDARD.md](../STANDARD.md)。

## 首次准备

以下以业务 `sample-survey` 为例，真实域名和数据库凭据由操作者手动配置；不从本仓库获取生产秘密。

```sh
sudo install -d -m 750 /opt/sample-survey/shared \
  /opt/sample-survey/releases /opt/sample-survey/backups /opt/sample-survey/logs
```

按服务器部署身份设置目录所有者。将生成项目的 `.env.prod.example` 安全复制为 `/opt/sample-survey/shared/.env.prod`，用编辑器填入实际值，设置 `chmod 600`，文件应归运行脚本的部署身份所有。至少配置：

| 键 | 内容 |
| --- | --- |
| `BUSINESS` | `sample-survey` |
| `ENVIRONMENT` | `production` |
| `COMPOSE_PROJECT_NAME` | `sample-survey-production`，跨版本不变 |
| `APP_PORT` | 登记的回环端口，如 `31001` |
| `DATABASE_URL` | 外部 PostgreSQL 的应用角色 URL |
| `MIGRATION_DATABASE_URL` | 独立迁移角色 URL |
| `BACKUP_DATABASE_URL` | 可选，省略或留空则使用迁移 URL |
| `PUBLIC_HEALTH_URL` | 实际域名加 `BASE_PATH + /healthz` |
| `HEALTH_TIMEOUT` | 可选，秒数，默认 `120` |

URL 中的特殊字符按 URI 规则编码，秘密不放进命令历史。先核对数据库角色权限、Nginx 路由、端口分配、磁盘空间、GHCR 访问及兼容的 `pg_dump`/`pg_restore`。首次部署也要备份，数据库与角色必须已存在。

## 部署指定版本

推荐通过生成的 Deploy 工作流部署；它读取本仓库已发布的版本包，验证 SSH 主机，只上传部署文件，并运行包内脚本。服务器秘密必须预先存在。

人工部署时，从可信 GitHub Release 取得 `deploy-vX.Y.Z.tar.gz`，在新的空版本目录解压。先检查归档只有预期版本目录，拒绝绝对路径、`..` 或链接逃逸，再解压；不要把不受信任归档直接解到受保护目录。以下命令假设已安全解压示例版本 `v1.2.3` 到 `/opt/sample-survey/releases/v1.2.3`：

```sh
cd /opt/sample-survey/releases/v1.2.3
sha256sum --check SHA256SUMS
bash scripts/deploy.sh /opt/sample-survey /opt/sample-survey/releases/v1.2.3
```

同一版本目录不可修改后再次使用；修复必须发布新版本。脚本会复核清单完整性、元数据、配置和 digest，不接受任意 source 环境文件。候选必须位于本项目 `releases/<version>`，目录名与元数据版本一致；脚本不搬移目录。成功后 `current` 指向该目录，不要清理。

执行顺序为：加锁 → 验证发布包与环境 → 拉取准确镜像 → 备份数据库并检查 archive 清单 → 一次性迁移 → 替换 app 并等待容器健康 → 检查公网健康 → 原子更新 `current`、`previous`。迁移或健康检查不能跳过。脚本不会在服务器编译应用、安装依赖或修改 Nginx。

## 显式初始化

首次成功部署后，单独运行：

```sh
bash /opt/sample-survey/current/scripts/bootstrap.sh /opt/sample-survey
```

参考应用只插入演示设置，不需要账号凭据。真实业务如需首次管理员，应在 `shared/.env.bootstrap` 手工配置实现所需的 `BOOTSTRAP_` 开头的大写键（其他键会被拒绝），例如 `BOOTSTRAP_ADMIN_USERNAME`、`BOOTSTRAP_ADMIN_PASSWORD`，权限 `0600`。这些键仅注入本次初始化任务；不要把密码放到命令参数、`.env.prod`、应用服务或发布包。业务初始化实现负责校验所需键。

重复执行必须安全，不重置已有账号。迁移和初始化都不能隐式绑到应用启动。完成后按项目策略保留或安全移除初始化秘密。

## 升级与失败处理

升级前检查迁移采用 expand/contract，旧应用仍能使用迁移后的结构。确认 previous 镜像可获取、备份空间充足，再运行同一部署入口。发布过程有锁，不要绕开锁并行执行手工 Compose 操作。

| 失败阶段 | 结果与处理 |
| --- | --- |
| 校验、拉取或备份失败 | 停止；保留原 current，修复输入或依赖后再发布 |
| 迁移失败 | 停止；不启动候选应用；检查迁移是否部分生效 |
| 应用或公网健康失败 | 尝试恢复旧应用镜像与配置；数据库保持迁移后的状态 |
| 恢复旧应用也失败 | 停止自动操作，保留现场、日志及备份，由操作者诊断 |
| 首次上线失败 | 没有有效旧版本；不创建伪造 current，修复后重试 |

先查看部署输出和 Docker 服务日志，避免打印含秘密的完整环境或 `docker compose config`。定位健康问题时同时检查容器内部、宿主机回环地址、Nginx 和公网 URL。脚本准备项目 `logs/`、`backups/` 目录，备份写入 `backups/`；部署输出由工作流或操作者保存，保存前确认不含秘密。

如果 GHCR 拉取失败，默认停止。应急使用本地缓存前必须能从官方仓库取得预期 digest，并确认本地缓存精确匹配；仅有相同标签或来自第三方镜像站不足以证明一致。不知道官方 digest 就不继续。

## 应用回滚

```sh
bash /opt/sample-survey/current/scripts/rollback.sh /opt/sample-survey
```

回滚恢复 previous 的应用镜像、Compose 与配置，再检查健康；不会反向执行迁移或恢复数据库。没有 previous 则停止。回滚后仍需检查业务核心路径及数据库写入。

若迁移已删除或改写旧应用依赖的数据结构，应用回滚可能无效，应停止自动恢复。数据库恢复必须作为独立事件处理，明确数据丢失窗口、停写安排、目标备份和人工批准，再按数据库运维流程操作；本工具不提供自动 restore/reset。

## 日常维护

- 监控磁盘、应用健康、数据库容量和证书有效期。为应用及部署日志设置保留策略。
- 定期进行离机备份和隔离恢复演练。`pg_restore --list` 只证明 archive 可读，不证明数据完整或业务可恢复。
- 保留 current、previous、回滚窗口所需发布包和镜像。清理前核对真实链接及 digest，避免删除仍需恢复的内容。
- 轮换数据库、GHCR 和 SSH 凭据时，核对用途和最小权限；不要把变更混入历史发布包。
- 单实例更新可能短暂中断；发布窗口和业务通知由项目决定。本流程不承诺零停机。

Compose 操作的完整输出保存于 `logs/compose-*.log`，权限 0600，终端只显示日志路径；日志可能含业务输出，应按生产敏感日志管理。

宿主机 PostgreSQL 可在容器连接中使用 `host.docker.internal`（模板已配置 host-gateway）。宿主机备份客户端通常不能解析该容器专用名称，应单独配置 `BACKUP_DATABASE_URL` 指向 `127.0.0.1` 或宿主机可解析的地址。Prisma 的 `schema` 查询参数在数据库整库备份时会忽略，libpq 连接选项保持校验。
