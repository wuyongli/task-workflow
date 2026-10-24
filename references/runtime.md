# Runtime And Config

## 后端测试环境

适用于配置为 `shared-backend-app` 的后端任务工作区。

规则：
- 后端任务测试统一在当前任务专属 Docker app 容器中执行；即使宿主机 Python 依赖可用，也不先尝试宿主机 pytest
- 任务 app 容器由当前任务仓库的 `docker/.task.env` 和 `docker/docker-compose.task.yml` 定义；测试前核对 Compose 项目和代码挂载属于当前任务，不使用共享主仓或其它任务容器验证任务 clone
- 测试命令从任务后端仓库根目录发起，容器内也切到仓库根目录（`/usr/src/pf.senguo.cc`）运行 `python -m pytest`，不要从 `pfsource/` 运行
- 任务 app 未运行时，在既有授权内按任务启动配置启动 app，复用已就绪且归属匹配的共享服务；容器内缺 pytest 时按 `ensure_pytest` 配置补齐
- Docker 不可用、任务容器启动失败或容器内缺依赖时，先诊断对应容器 / 镜像环境，记录具体错误和未完成的测试；不退回宿主机补包或执行 pytest，也不修改业务代码来掩盖 `XdbSearchIP` 等依赖缺失
- 同一任务绑定多个后端时，每个后端使用“任务 ID + repo key”生成独立 `COMPOSE_PROJECT_NAME`；容器、volume 挂载和停止命令互不复用
- 多个后端应在 `repositories.yaml` 中配置不重叠的 `app_port_start` / `app_port_end`，基础 MySQL、Redis、RabbitMQ、Mongo 和 Docker 网络仍可共享
- 进入真实页面流程联调前，先读取仓库 README、AGENTS、package.json、`.codex/environments/environment.toml` 启动动作及 `repositories.yaml` 中的 `auto_start_steps` / `start_commands`，在各动作指定的工作目录按既有指令启动前端服务和后端 Docker 服务，不能只启动 app。纯接口/数据库验证启动实际依赖；独立单测不因此强制启动前端或全套服务
- 后端 Docker 启动范围以仓库既有配置为准，通常包括共享 MySQL、Redis、RabbitMQ、Mongo、Nginx 和当前任务专属 app。先核对共享容器归属、挂载和网络；健康且匹配的可直接复用，归属、挂载或路由不匹配时先诊断，不直接重建或切换共享资源。缺失或已停止的服务确认无冲突后按原动作启动
- 就绪检查覆盖容器状态、网络、挂载、端口和近期日志；配置 healthcheck 时须通过，没有 healthcheck 时用服务自身的只读探测或依赖连通验证，不能只凭 running 或命令退出码判定就绪。记录实际命令及 cwd、检查结果和未就绪项到运行附件，progress 只保留结果摘要及附件链接
- 如果某个非关键动作在仓库配置中标记 `allow_failure: true`，仍需记录失败原因并确认它不影响本次被测页面或接口；不能把配置中的容错标记理解成跳过后端服务
- 只有所有本次流程实际依赖的后端 Docker 服务和前端进程就绪、代理指向当前任务后端后，才能进入浏览器真实测试；服务未就绪时先诊断并记录阻塞

以下命令均在任务后端仓库根目录执行。任务 app 未运行时，按既有授权启动：

```bash
docker compose --env-file docker/.env --env-file docker/.task.env \
  -f docker/docker-compose.yml -f docker/docker-compose.task.yml \
  up -d app
```

容器测试命令：

```bash
docker compose --env-file docker/.env --env-file docker/.task.env \
  -f docker/docker-compose.yml -f docker/docker-compose.task.yml \
  exec -T app sh -lc 'cd /usr/src/pf.senguo.cc && python -m pytest ...'
```

## 前端本地依赖环境

适用于配置为 `patch-node-frontend-environment` 的前端任务工作区。

规则：
- 前端 Vitest、`npm run typecheck`、本地启动前，先使用项目声明的 Node 版本；有 `.nvmrc` 优先 `.nvmrc`，否则使用 `package.json` 的 `volta.node`
- 用项目 Node 执行 `node -p 'process.arch'` 记录实际架构，随后直接运行最快的目标验证，不先做多轮依赖探测
- 只有 `node_modules` 不存在，或目标命令实际报当前平台 native binding 缺失时，才执行相应的 prepare；其它业务测试失败直接按测试失败处理
- `sg publish local` 前只做当前平台原生 optional 依赖准备，不做完整 runtime prepare，避免发布前置动作改写本地端口、代理或 `environment.toml`
- `@rolldown/binding-darwin-*`、`@typescript/typescript-darwin-*`、`@parcel/watcher-*`、`lightningcss-*`、`sass-embedded-*` 这类包属于平台原生 optional dependency；缺失通常是本地设备 / Node 架构漂移，不是业务代码失败
- 如果已有 `node_modules`，且 `package-lock.json` 声明的当前平台 optional native 包缺失，`prepare_task_runtime.py` 会先从 lockfile 解析缺失包版本，并定向执行 `npm install --no-save --package-lock=false --no-audit --no-fund <name@version...>`
- 只有无法从 lockfile 解析缺失包版本、定向修复失败，或定向修复后仍缺包时，才回退执行完整依赖修复命令
- 如果 `node_modules` 不存在，仍按仓库配置的 `install_commands` 首次安装；不要把新任务创建变成默认安装业务依赖
- 本地修复只允许影响 `node_modules`；如果本次修复导致 `package.json` 或 `package-lock.json` 产生新变更，必须视为异常，不能作为业务改动提交
- 不要用切换到另一种架构的 Node 来掩盖问题；最终验证必须回到项目声明 Node 版本和用户默认前端命令
- `publish_task_workspace.py` 会在配置为 `patch-node-frontend-environment` 的前端发布前自动执行当前平台原生 optional 依赖准备；不需要用户手动先跑修复命令

推荐修复入口：

```bash
python3 /Users/wuyongli/Documents/sg-skill/task-workflow/scripts/prepare_task_runtime.py "YYYY-MM-DD-原始任务名" --repo 手机前端
```

## `repositories.yaml`

用于保存可复用的仓库注册表。

每个仓库项应包含：
- `key`: stable repo key, usually the directory name
- `path`: main repo path under `/Users/wuyongli/Documents/sg-project`
- `remote`: clone URL when needed
- `notes`: optional brief remarks
- `runtime`: optional runtime bootstrap rules for task clones

`runtime` 支持：
- `mode`: optional runtime preset such as `shared-backend-app`
- `copy_missing_from_main`: copy listed relative paths from the main repo only when the task clone is missing them
  - useful for local-only startup files such as `.codex/environments/environment.toml`
- `copy_missing_from_template`: create missing files inside the task clone from repo-local templates such as `settings_local.py -> settings.py`
- `environment_toml`: optional task repo startup file path for frontend runtime patching
- `task_env_file` / `task_compose_file`: generated helper files for backend runtime presets
- `task_port_key`: optional env key name stored in the task runtime env file for frontend port pinning
- `task_app_image`: optional local image tag to reuse for backend task app containers before falling back to per-task builds
- `mysql_data_switch`: optional explicit MySQL data-directory switch config for backend repos
  - `compose_dir`: main repo docker directory used as the target MySQL data owner
  - `container_name`: shared MySQL container name, default `pf-mysql-1`
  - `mount_destination`: MySQL data mount destination, default `/var/lib/mysql`
  - `data_dir`: target host data dir, default `<compose_dir>/data/mysql`
- `ensure_pytest`: for `shared-backend-app`, default `true`; after the task app starts, ensure `pytest` is available inside the task container
- `pytest_version`: pytest version installed by the backend task container bootstrap, default `7.4.4`
- `pip_index_url`: pip index used when installing backend task test tools, default Aliyun PyPI mirror
- `auto_start_on_prepare` / `auto_start_steps`: optional startup automation after runtime files are ready
- each auto-start step may optionally use `allow_failure: true` when a non-critical local service should not block later steps
- `install_commands`: commands to install dependencies
- `native_optional_repair_command`: 当前平台原生 optional 依赖的完整修复回退命令，默认 `npm ci --include=optional`；正常缺少少量 native 包时优先走 lockfile 定向安装，不直接执行该命令
- `start_commands`: commands to start the repo locally
- `notes`: short runtime remarks for the agent
- 前端如需自动连同任务后端，优先配置 `local_backend_repo_key` + `backend_task_env_file`，从后端 `TASK_APP_HOST_PORT` 读取端口
- `.env` 类前端使用 `local_backend_env_file`，会修正 `VITE_DEV_PROXY_TARGET` / `VITE_PF_API_URL`
- `dev_config/settings.json` 类前端使用 `local_backend_json_file` + `local_backend_json_fields`，例如批发 PC 端修正 `PROXY_TARGET_ADDRESS`
- `src/setupProxy.js` 类前端使用 `local_backend_proxy_js_file`，并用 `local_backend_proxy_js_http_constants` / `local_backend_proxy_js_ws_constants` 指定要替换的常量
- 产地手机端的 `producer_proxy_config_file` 只处理 `vite.proxy.config.mjs`；不要把它当成通用前端代理规则

MySQL 数据目录切换：
- `/task-workflow mysql <目标后端>` 只切换 `mysql_data_switch` 指向的 MySQL 数据目录
- 指令会检查 `pf-mysql-1` 当前 `/var/lib/mysql` 的 host mount source
- 当前目录已匹配目标时 no-op；不匹配时执行 `docker compose up -d --force-recreate mysql`
- 不切 Redis、Mongo、RabbitMQ、Nginx；不补字段、不导数据、不迁移
- 切换后正在连接 MySQL 的任务 app 可能需要重启

发布约定：
- `shared-backend-app` 默认视为后端仓库，发布命令为 `sg publish jenkins`
- `patch-node-frontend-environment` 默认视为前端仓库，发布命令为 `sg publish local`

模板：[repositories.yaml.example](repositories.yaml.example)

## `workspace.yaml`

用于保存工作区级别规则。

应包含：
- workspace root
- tasks root
- docs root
- config root
- task naming rule
- repo directory naming rule
- branch sanitization rule
- clone source mode
- complete remote-sync safety policy
- default document filenames

模板：[workspace.yaml.example](workspace.yaml.example)
