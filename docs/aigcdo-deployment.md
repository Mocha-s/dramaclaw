# AIGCDO 多用户部署

更新：2026-11-16。进度与各块验证记录见
[`aigcdo-user-management-research.md`](aigcdo-user-management-research.md)。

本仓库继续使用 **CE**（没有 EE 源码，不设置控制面 DSN）。
`SUPERTALE_AUTH_PROVIDER=aigcdo` 让每个用户用 AIGCDO 网关账号登录，
所有模型调用花用户自己的网关 Key；它不是把 `ST_EDITION` 改成 EE。

## 现在能用什么

| 功能 | 状态 |
| --- | --- |
| 注册、登录、两步验证、退出 | 可用。注册时同时在网关建账号并自动开通一把应用 Key |
| 余额、用量、充值下单、订单查询 | 可用。网关是唯一账本，创作端不另记一本账 |
| 项目与全部创作接口（画布、文本、图像、视频、音频、剧本/草图/视频流水线） | 可用，按 owner 隔离，花发起人自己的 Key |
| 小说导入 | 新建项目可用，不需要 Embedding。旧的知识图谱项目需要配置下文的 Embedding 端点 |
| 对话助手（Agent） | 仅当本机能隔离每个用户的工作进程时开放，否则返回 503，见“对话助手” |
| 技能导入、Agent 配置（`/freezone/skill-imports`、`/freezone/agent-config`） | 不开放（503）。这两处是整个安装共享的可写状态，还没有按用户拆分 |
| 模型网关配置、任务额度 | 仅管理员可用，其他用户 403；诊断接口对所有人 403 |

网关开启 Cloudflare Turnstile 时，登录和注册表单会显示人机验证组件（用网关公开的站点密钥）。
**创作站点的域名必须加进该 Turnstile 组件的允许主机名**，否则组件报错 `110200`、无法登录；
IP 地址访问不行。腾讯、阿里验证码未接入。

邮箱验证、找回密码、邀请码尚未接入。网关开启其中任何一项（或未接入的验证码）时，
创作端的注册入口会显示“暂不支持”，不会发出半截请求。

## 必需配置

| 变量 | 要求 |
| --- | --- |
| `SUPERTALE_AUTH_PROVIDER` | `aigcdo` |
| `ST_EDITION` | `ce` 或不设置；`ST_CONTROL_PLANE_DSN` 必须为空 |
| `AIGCDO_APP_ORIGIN` | 创作站点的确切 HTTPS origin，例如 `https://studio.example.com`，不带路径。只有本机开发允许 loopback HTTP |
| `AIGCDO_STATE_DIR` | 保存认证数据的绝对目录，不能是 `/` |
| `AIGCDO_ENCRYPTION_KEY` | Fernet 密钥。每次重启必须相同，不得进 Git |
| `AIGCDO_APPLICATION_GROUP_ID` | 用户有权使用的网关分组 ID（联调用的是综合分组 41） |
| `AIGCDO_CREDITS_PER_USD` | 每 1 USD 网关余额显示多少积分 |
| `AIGCDO_CREDIT_DECIMALS` | 积分显示的小数位，0–8 |
| `AIGCDO_CREDIT_POLICY_VERSION` | 积分规则版本号，最长 64 字符；订单会记录下单时的版本 |
| `AIGCDO_MODEL_CATALOG` | 运营维护的模型目录 JSON 的路径，见下文 |

生成密钥：

```bash
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

缺字段、值非法、同时设置了控制面 DSN 或 `DRAMACLAW_LOCAL_AGENT_TRUST`，
进程都拒绝启动，不会退回单用户的 `local` 身份。

**环境里不能有任何共享模型 Key**（`NEWAPI_API_KEY`、`OPENAI_API_KEY`、
`EMBEDDING_API_KEY` 等，完整名单见 `aigcdo_model_runtime.SHARED_CREDENTIAL_ENV`），
否则拒绝启动：共享 Key 意味着运营替所有用户付费。

### 管理员

| 变量 | 要求 |
| --- | --- |
| `AIGCDO_ADMIN_USER_IDS` | 管理员的网关用户 ID，逗号分隔（在网关后台的用户列表里看）。不设则没有管理员 |

管理员就是被点名的网关账号：照常登录、照常创作，另外在页面右上角多一个“设置”入口，
内容与单机模式相同（模型与渠道、任务与队列、媒体存储），再加积分比例和公告。
网关自身的 admin 角色不算数。其他用户看不到入口，接口返回 403。

- 指向 AIGCDO 网关的分组里填的 Key 只用于拉取上游模型列表和价格，用户生成时用各自的 Key。
- 指向其他地址的分组只允许 Embedding 能力（用管理员填的 Key）；文本和媒体放到外部地址会被忽略。
- 积分比例保存后立即生效：余额、账单、订单和模型价格全部按新比例显示。用户界面只显示积分，不显示美元金额和比例。
- 修改对话助手（Agent）模型后需要重启 API 才会重新检测助手是否可用。分组上的“自动获取上游模型”开关在多用户模式下不生效，需手动点击获取。
- 下面的模型目录文件和积分环境变量只是首次启动的初始值，管理员保存后以保存的为准。

### 模型目录（可选的初始值）

`AIGCDO_MODEL_CATALOG` 指向一份只含模型元数据的 JSON，
示例见 [`aigcdo-model-catalog.example.json`](aigcdo-model-catalog.example.json)：

- `groups[]`：`id`、`name`、`protocol`、`capabilities`、`modelMappings`；
- `capabilityDefaults`：`textGroupId`、`textModel`、`textReasoningEffort`；
- `agentModel`：对话助手用的模型名。留空则不开放对话助手。

目录里出现 `apiKey`、`baseUrl` 或其他字段即拒绝启动。所有调用固定发往
`https://api.aigcdo.top`，Key 取当前用户的应用 Key。
模型的说明和价格取自网关的模型广场，用当前用户的 Key 读取。

### Embedding（可选）

Embedding 是唯一由运营出 Key 的模型调用，可以放在任何 OpenAI 兼容的服务上，
不必是 AIGCDO 网关：

| 变量 | 要求 |
| --- | --- |
| `AIGCDO_EMBEDDING_BASE_URL` | HTTPS 地址，例如 `https://api.siliconflow.cn/v1` |
| `AIGCDO_EMBEDDING_API_KEY` | 运营在该服务上的 Key |
| `AIGCDO_EMBEDDING_MODEL` | 模型名，例如 `BAAI/bge-m3` |
| `AIGCDO_EMBEDDING_DIMENSIONS` | 该模型的原生向量维度，默认 1024 |

前三项要么全设要么全不设，只设一部分拒绝启动。请求不带 `dimensions` 参数，
所以这里填模型的原生维度，不能用它来缩小向量。

只有旧的知识图谱项目（`cognee_legacy`）用得到它。新建项目走结构化导入
（`structured_v1`），不需要 Embedding；不配置时旧项目的图谱构建会失败，其余功能不受影响。
这把 Key 的费用由运营承担，不计入用户账单。

## 对话助手与工作进程隔离

对话助手会启动一个执行模型指令的 Hermes 工作进程。多用户下每个工作进程都放进
bubblewrap 沙箱（`security/sandbox_wrap.py::per_user_argv`）：

- 状态、输出、运行时三个数据根目录和 `AIGCDO_STATE_DIR` 整体不可见，
  只把**当前用户自己的目录**以只读方式挂回来；别的用户的目录在沙箱里根本不存在。
- 运营账号的 home、`/tmp`、`/run` 不可见；仓库目录只有运行所需的 `src`、`integrations`、`.hermes`、`.venv` 可见。
- 全安装共享的 `state/_shared`（含各用户的回放记录）不可见。
- 独立的 PID 命名空间和新的 `/proc`：读不到 API 进程的环境变量（里面有加密密钥）。
- 只有工作进程自己的目录可写。
- 工作进程的环境里没有模型 Key：每一轮对话由 API 进程附上该用户的 Key。
- 工作进程用一个最长 2 小时的短期令牌回调 API。令牌只能从本机回环地址使用，
  只对它绑定的那一个项目有效，退出登录即失效，重新登录后旧工作进程会被替换。

多用户下**没有无沙箱降级**：`SUPERTALE_ALLOW_UNSANDBOXED` 不起作用；
聊天后端固定为 Hermes，`DRAMACLAW_CHAT_BACKEND=codex|claude` 被忽略
（那两个后端的工作进程不在这个沙箱里）。

启动时 API 会真实地在沙箱里跑一次 `hermes --version`。下面任一条不满足，
对话助手自动停用（HTTP 返回 `503 aigcdo_integration_pending`，WebSocket 以 1008 关闭），
其余功能照常，原因写在启动日志 `AIGCDO Agent (chat) is disabled: …` 里：

1. 目录里填了 `agentModel`；
2. 装了 Hermes CLI（镜像自带；源码运行要自己装）；
3. 能创建沙箱：需要 `bwrap`、内核允许非特权 user namespace，并且能挂载新的 `/proc`。
   Ubuntu 24.04 宿主机还要 `sysctl kernel.apparmor_restrict_unprivileged_userns=0`，
   否则 bwrap 报 `setting up uid map: Permission denied`。
   在 Docker 里这要求 `security_opt` 同时有 `seccomp:unconfined`、`apparmor:unconfined` 和 `systempaths=unconfined`（2026-11-17 逐项实测，缺一不可）。

画布插件（`.hermes/plugins/freezone`）运行在 Hermes 自己的 Python 环境里，不是 API 的虚拟环境，
它额外需要 `jsonschema` 和 `portalocker`。镜像构建和 `scripts/setup-hermes.sh` 都会装上；
自行安装 Hermes 时要补装，否则助手能对话，但所有画布读写工具都会失败，而且上面的启动探测查不出来。

**还没做的**：工作进程的出站网络没有限制（#346 P1② 的第二项）。
它需要访问本机 API 和网关，目前也能访问宿主机能到达的其他地址。
部署到云服务器时，请在安全组或防火墙上挡掉实例元数据地址 `169.254.169.254`
（或不给这台机器挂实例角色），并且不要在同一台机器的回环地址上跑不带认证的服务。

## 部署到云服务器

用源码构建并叠加 AIGCDO 覆盖文件（已发布的官方镜像不含这部分代码）：

```bash
cp docs/aigcdo-model-catalog.example.json aigcdo-model-catalog.json   # 按需增删模型、填 agentModel
# 在 .env 里写上文的 AIGCDO_* 变量，并设 ST_API_PORT=127.0.0.1:8780
docker compose -f docker-compose.yml -f deploy/docker-compose.aigcdo.yml up -d --build
```

`deploy/docker-compose.aigcdo.yml` 做了四件事：设置 `SUPERTALE_AUTH_PROVIDER=aigcdo`、
把认证数据放到数据卷的 `/data/aigcdo`、挂载模型目录、
加上沙箱需要的 `security_opt` 并关掉无沙箱降级。

其余要求：

- 在 `web`（默认 8080）前放一层 TLS 反向代理，`AIGCDO_APP_ORIGIN` 填它的 HTTPS 地址。
  代理必须原样转发 `Origin` 和 `Cookie`，并支持 WebSocket 升级。
  所有写请求和 WebSocket 都校验 `Origin` 等于 `AIGCDO_APP_ORIGIN`，不一致返回 403。
- API 端口（8780）不要对公网开放，浏览器只访问 `web`。
- 不要让别的代理绕过 `web` 直连 API。API 只在请求来自回环地址且不带 `X-Forwarded-For`
  时才接受工作进程令牌；仓库自带的 nginx 模板会加这个头，自建代理必须也加。
- 前端用默认的 CE 构建即可。
- 当前 SQLite 存储只适合**单台主机**。不要起多个互不共享磁盘的 API 副本。

## 持久化与备份

`AIGCDO_STATE_DIR`（目录 0700，文件 0600）保存：

- `sessions.db`：用户身份映射和加密的网关会话；
- `application-keys.db`：每个用户应用 Key 的加密绑定；
- `payments.db`：下单尝试和加密的支付信息；
- `execution.db`：任务与短期 Agent 令牌的加密授权。

备份这些数据库时必须同时安全备份 `AIGCDO_ENCRYPTION_KEY`。
换了密钥，旧会话、Key 绑定和订单恢复数据都无法解密；目前没有密钥轮换流程。

项目注册表和文件沿用原位置：`STATE_DIR/local/projects.db` 与
`{STATE,OUTPUT,RUNTIME}_DIR/<用户目录>/<项目名>`。

## 存量项目迁移

旧的 `local` 项目和文件原样保留，不会自动归给任何新账号。
全部开发完成后，停服、让目标用户先登录一次，再执行（默认只预览）：

```bash
uv run python scripts/aigcdo_migrate_local_projects.py --gateway-user-id <网关用户 ID> [--apply]
```

`--apply` 才写入，并且先备份；项目 ID 和目录不变。

## 上线前自查

- `GET /api/v1/config` 返回 `edition=ce`、`auth_provider=aigcdo`、`auth_required=true`。
- 不带 Cookie 请求 `/api/v1/projects` 返回 401。
- 启动日志里没有 `AIGCDO Agent (chat) is disabled`（除非有意不开对话助手）。
- 用一个测试账号注册，确认返回 `application.status=ready`，再跑一次文本生成，
  在“余额与充值”里能看到对应的一笔用量。
- `/healthz` 只表示进程存活，不代表网关、模型或支付可用。
