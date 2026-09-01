# Runtime And Config

## 后端测试环境

适用于配置为 `shared-backend-app` 的后端任务工作区。

规则：
- 后端测试优先在当前任务自己的后端仓库根目录运行
- 如果宿主机 Python 依赖已经可用，可以先用 `python3 -m pytest ...`
- 如果宿主机依赖不完整、Python 版本不匹配，或测试涉及运行时依赖，切换到当前任务 Docker app 容器
- 不要用共享主仓 `producer-backend` 容器验证任务 clone，除非已经确认该容器挂载的就是当前任务代码目录
- 任务 app 容器由当前任务仓库的 `docker/.task.env` 和 `docker/docker-compose.task.yml` 定义，测试时应在任务后端仓库根目录执行
- 同一任务绑定多个后端时，每个后端使用“任务 ID + repo key”生成独立 `COMPOSE_PROJECT_NAME`；容器、volume 挂载和停止命令互不复用
- 多个后端应在 `repositories.yaml` 中配置不重叠的 `app_port_start` / `app_port_end`，基础 MySQL、Redis、RabbitMQ、Mongo 和 Docker 网络仍可共享
- 如果 app 容器未启动，先用当前任务 compose 文件启动 app

推荐容器测试命令：

```bash
docker compose --env-file docker/.env --env-file docker/.task.env \
  -f docker/docker-compose.yml -f docker/docker-compose.task.yml \
  exec app sh -lc 'cd /usr/src/pf.senguo.cc && python -m pytest ...'
```

## 前端本地依赖环境

适用于配置为 `patch-node-frontend-environment` 的前端任务工作区。

规则：
- 前端 Vitest、`npm run typecheck`、本地启动前，先使用项目声明的 Node 版本；有 `.nvmrc` 优先 `.nvmrc`，否则使用 `package.json` 的 `volta.node`
- `@rolldown/binding-darwin-*`、`@typescript/typescript-darwin-*`、`@parcel/watcher-*`、`lightningcss-*`、`sass-embedded-*` 这类包属于平台原生 optional dependency；缺失通常是本地设备 / Node 架构漂移，不是业务代码失败
- 如果已有 `node_modules`，且 `package-lock.json` 声明的当前平台 optional native 包缺失，`prepare_task_runtime.py` 会执行本地修复命令，默认 `npm ci --include=optional`
- 如果 `node_modules` 不存在，仍按仓库配置的 `install_commands` 首次安装；不要把新任务创建变成默认安装业务依赖
- 本地修复只允许影响 `node_modules`；如果修复后 `package.json` 或 `package-lock.json` 出现 diff，必须视为异常，不能作为业务改动提交
- 不要用切换到另一种架构的 Node 来掩盖问题；最终验证必须回到项目声明 Node 版本和用户默认前端命令

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
- `native_optional_repair_command`: optional command for repairing current-platform frontend optional native dependencies; default `npm ci --include=optional`
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
- cleanup safety policy
- default document filenames

模板：[workspace.yaml.example](workspace.yaml.example)
