# Runtime And Config

## 后端测试环境

适用于 `producer-backend` 任务工作区。

规则：
- 后端测试优先在当前任务自己的后端仓库根目录运行
- 如果宿主机 Python 依赖已经可用，可以先用 `python3 -m pytest ...`
- 如果宿主机依赖不完整、Python 版本不匹配，或测试涉及运行时依赖，切换到当前任务 Docker app 容器
- 不要用共享主仓 `producer-backend` 容器验证任务 clone，除非已经确认该容器挂载的就是当前任务代码目录
- 任务 app 容器由当前任务仓库的 `docker/.task.env` 和 `docker/docker-compose.task.yml` 定义，测试时应在任务后端仓库根目录执行
- 如果 app 容器未启动，先用当前任务 compose 文件启动 app

推荐容器测试命令：

```bash
docker compose --env-file docker/.env --env-file docker/.task.env \
  -f docker/docker-compose.yml -f docker/docker-compose.task.yml \
  exec app sh -lc 'cd /usr/src/pf.senguo.cc && python -m pytest ...'
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
- `ensure_pytest`: for `shared-backend-app`, default `true`; after the task app starts, ensure `pytest` is available inside the task container
- `pytest_version`: pytest version installed by the backend task container bootstrap, default `7.4.4`
- `pip_index_url`: pip index used when installing backend task test tools, default Aliyun PyPI mirror
- `auto_start_on_prepare` / `auto_start_steps`: optional startup automation after runtime files are ready
- each auto-start step may optionally use `allow_failure: true` when a non-critical local service should not block later steps
- `install_commands`: commands to install dependencies
- `start_commands`: commands to start the repo locally
- `notes`: short runtime remarks for the agent

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

