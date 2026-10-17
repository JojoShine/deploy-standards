# Deploy Standards

一套面向单台 Linux 服务器、Docker Compose 与外部 PostgreSQL 的发布规范、可复用工作流和部署工具。业务代码在 CI 构建与验证；服务器只接收发布包并运行已验证的镜像。

本仓库提供一个可运行的 Node/PostgreSQL **参考应用**，用于演示接口和验证部署链路。它不是完整业务系统。接入已有应用时，应按项目实际安装的框架版本替换应用、迁移及初始化实现，并保留本标准的部署接口。

- [标准正文](STANDARD.md)：必须遵守的接口与约束。
- [接入步骤](docs/ADOPTION.md)：生成项目、替换参考实现、配置 CI 与服务器。
- [运行手册](docs/OPERATIONS.md)：首次上线、初始化、升级、故障与回滚。
- [端口分配](docs/PORTS.md)：容器端口、宿主机端口与登记表。

## 快速接入

先克隆标准仓库，选择并审阅一个提交。下例取得本地当前提交的完整 SHA；运行前应确认该提交对应你要采用的版本，并检查其 CI 结果。

```sh
git clone https://github.com/JojoShine/deploy-standards.git
cd deploy-standards
STANDARDS_REF=$(git rev-parse HEAD)
python3 tools/init-project.py \
  --business sample-survey \
  --output ../sample-survey \
  --standards-ref "$STANDARDS_REF" \
  --owner JojoShine
cd ../sample-survey
npm test
```

输出目录必须不存在或为空。业务标识使用小写短横线 slug；`--standards-ref` 必须是完整 40 位提交 SHA。生成器复制共享服务器脚本，并把模板中的业务名、镜像所有者和可复用工作流引用替换成确定值。标准更新不会静默修改已生成项目；升级时审阅差异并重新固定标准 SHA。

项目提交到自己的 GitHub 仓库后：PR 运行检查；`main` 成功构建发布 `sha-<完整提交>` 镜像及候选元数据；为同一已测试提交创建 `vX.Y.Z` 标签，发布工作流将原镜像提升为版本标签并生成部署包。版本提升不得重新构建。详见[接入步骤](docs/ADOPTION.md)。

## 标准与项目参数

| 标准统一约定 | 每个项目自行确定 |
| --- | --- |
| `runtime`、`migrate` 镜像目标；显式迁移、初始化 | 业务名、框架及其版本、迁移工具 |
| `compose.prod.yaml` 独立且只用镜像 | GitHub owner/repo、域名、`BASE_PATH` |
| 镜像 digest、完整提交与版本发布包绑定 | PostgreSQL 地址、角色、凭据 |
| 容器监听 `0.0.0.0:8080` | 宿主机 `APP_PORT`，默认 `31000–31999` |
| 服务器路径 `/opt/<business>` | 环境名、外部健康检查 URL、备份保留策略 |

生产密钥由运维人员在服务器手动配置到 `/opt/<business>/shared/.env.prod`；不写进 Git、镜像、工作流或发布包。本仓库不包含实际业务服务器地址或凭据。

## 仓库组成

```text
STANDARD.md               规范性约束
docs/                     接入和运维说明
templates/project/        可运行的参考项目与调用方工作流
scripts/                  deploy.sh、bootstrap.sh、rollback.sh、lib.sh
tools/                    项目生成、发布打包、Compose 检查
.github/workflows/        可复用 CI、Release、Deploy 与仓库自检
tests/                    工具和部署流程测试
```

部署包为 `deploy-vX.Y.Z.tar.gz`，解压后只有一个 `vX.Y.Z/` 顶层目录，包含生产 Compose、镜像引用、元数据、共享脚本、Nginx 示例和校验清单。它不包含业务源码或密钥。

v1 的可执行模板支持单 HTTP 应用与外部 PostgreSQL；多服务、Worker 和其他数据库需通过标准扩展接入，不能绕过现有校验。v1 目标平台为 `linux/amd64`，采用单实例替换，可能短暂中断。应用回滚依赖数据库迁移向后兼容；本标准不承诺零停机，也不自动恢复数据库。许可：[MIT](LICENSE)。
