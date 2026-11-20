# AIGCDO 用户系统与网关接入研究：第一版

更新日期：2026-11-17。

**状态：第一版方向已由用户选定，已进入分支实现阶段；下表逐项记录进度，不代表整版已经上线。**

### 当前实现进度

实现分支：`feat/aigcdo-gateway-integration`，从此前品牌/调研分支新建，
工作区中已有品牌改动随分支保留。

**记录口径：**“已实现”指源码及列出的本地回归，不等于已部署；各块测试数是当时的
选定套件结果，存在重叠，不能相加作为全仓测试总数。当前改动尚未提交或推送。

**版本口径：**用户已确认没有 EE 源码，继续基于 CE 开发，没有将 `ST_EDITION` 或前端构建切到 EE。
AIGCDO 的多用户认证是独立接入；CE/EE 与是否必须登录是两项配置。
现有 EE 分支需要配套 `ST_CONTROL_PLANE_DSN` 与完整企业端口实现，不能通过改 edition
代替用户系统和隔离改造。生产组合必须明确设置 `auth_required=true`，不得沿用 CE 免登录回退。

**存量项目约定（用户明确要求）：**现有 `local` 用户项目与全部文件必须保留。
全部开发完成后，再迁移给用户指定的账号；当前不自动认领、不删除、不提前迁移。
迁移对象届时以不可变网关用户 ID 确认，保留项目 ID/路径，并先备份、预览迁移清单和验证归属。

#### 前八块完成归档

| 块 | 已交付内容 | 主要文件/目录 | 最近验证范围 |
| --- | --- | --- | --- |
| 1 | 网关认证客户端及安全错误 | `src/novelvideo/aigcdo_gateway.py` | 纳入第八块 245 项后端回归 |
| 2 | 加密会话、稳定用户映射、项目 owner 授权 | `aigcdo_sessions.py`、`ports/aigcdo_project.py` | 纳入第八块 245 项后端回归 |
| 3 | Cookie 登录/注册/2FA/me/logout 可组合路由 | `api/routes/aigcdo_auth.py` | 真实本地 ASGI/Cookie 回归，纳入 245 项 |
| 4 | 每用户应用 Key 自动绑定与恢复 | `aigcdo_application_keys.py` | 并发/撤销/结果不确定覆盖，纳入 245 项 |
| 5 | 用户级文本/图片/视频运行时 | `aigcdo_model_runtime.py` | 专项 414 项；后续核心回归纳入 245 项；另有两项既有 HuiMeng 失败见下文 |
| 6 | 余额/冻结额/用量及 Decimal 积分转换 | `aigcdo_billing.py`、`api/routes/aigcdo_billing.py` | 纳入 245 项后端回归 |
| 7 | 充值/本人订单、持久化防重与加密结果 | `aigcdo_payments.py`、`aigcdo_payment_contract.py` | 纳入 245 项；含并发预检拒绝原子落盘 |
| 8 | 账户/充值/支付回跳页面、四项复核修复 | `frontend/src/components/aigcdo/account-page.tsx` | 47 项账户测试；带既有支付/认证共 105 项；CE build/Ruff/gitleaks 通过 |

表中省略前缀的后端路径均位于 `src/novelvideo/`。品牌替换另见 §11。

| 交付 | 状态 | 说明 |
| --- | --- | --- |
| 网关用户认证客户端 | 已实现，复核问题已修复 | 登录、注册、2FA、JWT 查询、刷新和退出；已纳入显式 AIGCDO app 组合 |
| 持久化会话、用户映射、项目授权端口 | 已实现，复核问题已修复 | 加密令牌、稳定映射及真实 owner 授权；第十块接入 registry |
| Cookie 认证 HTTP 路由 | 已实现，复核问题已修复 | 同源认证与安全错误；第十块接入实际 app 工厂，未部署 |
| 注册/登录/2FA 页面及开通恢复 | 第九块已实现，复核修复完成 | 复用现有 LoginCard，服务端声明 AIGCDO 认证后选择新表单；验证码发送/找回密码尚待核实接入 |
| Agent 授权及任务接线 | 已实现并真实联调（2026-11-17） | 任务与对话助手都按发起人身份执行；对话助手仅在本机能隔离工作进程时开放 |
| 应用专用 Key 自动开通 | 已实现，复核问题已修复 | 用户 JWT 调用已有网关接口，加密永久绑定；登录响应与应用重试端点已接入可组合路由 |
| 用户级文本/图像/视频运行时服务 | 已实现，复核问题已修复 | 每次验证用户 Key，固定平台来源，复用既有模型适配器；业务路由和任务接线待完成 |
| 平台模型目录/统一配置入口 | 已实现（运营 JSON 目录，旧配置读写失效） | Embedding 改为运营自配端点，可不在自有网关上 |
| 余额/消费记录及积分换算只读 API | 已实现，复核问题已修复 | 账户页与第十块 AIGCDO app 均已接；读取本人网关账本，不重复扣费 |
| 充值下单与本人订单 API | 已实现，复核补充已完成 | 用户 JWT 下单/查单，本地持久化防重与加密支付信息；网关唯一入账 |
| 账户/充值与支付回跳页面 | 已实现，复核修复完成 | /account 与 /payment/result，私有 API 契约解析、账户级缓存/下单防重、本地二维码 |
| 应用组合与强制认证 | 第十块已实现，复核修复完成 | 显式 provider 选择、必需配置校验、真实身份端口、受控路由与管理保护 |
| 主导航与完整创作接线 | 已实现，除技能导入与 Agent 配置 | 这两处是整个安装共享的可写状态，尚未按用户拆分，保持 503 |
| 迁移及多用户上线验收 | 测试账号真实联调通过；迁移与云端部署待执行 | 迁移目标用户 ID、HTTPS 域名待用户提供；支付未做真实付款 |

首个实施计划：`docs/superpowers/plans/2026-11-15-aigcdo-gateway-client.md`。

以下第一至九块说明保留各块交付当时的验证与限制；其中“尚未接生产工厂”等历史描述
以顶部进度表和第十块记录为最新状态。实际部署、任务执行与工作进程隔离仍未完成。

首块代码：`src/novelvideo/aigcdo_gateway.py`。
回归测试：`tests/test_aigcdo_gateway.py`，连同既有认证端口测试共 52 项通过。
客户端固定 HTTPS 来源、不跟随重定向、不自动重试认证写操作，
凭据使用隐藏明文的类型，网络/业务错误使用本地安全消息。
网关退出失败会明确返回错误，不能将此前实测的 502 当成成功撤销。
独立复核发现的异常令牌编码/异常 repr 泄露风险已修复：
12 项新增回归测试先复现失败，再验证修复；请求前及响应解析时均校验令牌格式。
`pre-commit` 的 gitleaks 钩子和包含未跟踪文件的直接内容扫描均通过。

第二块代码：`src/novelvideo/aigcdo_sessions.py`、
`src/novelvideo/ports/aigcdo_project.py`。计划：
`docs/superpowers/plans/2026-11-15-aigcdo-sessions.md`。

- 身份按不可变网关用户 ID 关联；本地生成稳定用户名用于路径，邮箱变化不改变项目归属。
- Cookie 使用随机值，仅保存 SHA-256 哈希；网关 access/refresh token 使用 Fernet 加密，
  加密载荷绑定 Cookie 哈希、用户和有效期，防止复制记录混用身份。
- 加密密钥由调用者提供，未写入数据库或文档；部署注入和密钥备份属于后续接线。
  `cryptography` 已在原锁文件中，本次只声明为直接依赖，没有升级锁文件中的包版本。
- `verify_session` 查询网关最新身份，校验用户 ID/状态；网关不可用时不使用旧身份放行。
- 同一会话的 refresh 通过数据库比较并更新排他认领；其他并发验证暂时失败，
  不重复消费 refresh token。刷新结果不明或认领超时需重新登录。
- 退出先撤销本地 Cookie，再请求网关退出；网关返回 502 仍会向调用者报告，
  但已撤销的本地会话不能恢复。退出与刷新竞争时还会尝试撤销新轮转的令牌。
- 共享项目注册表改为真实保存/查询 `owner_user_id`；AIGCDO 授权端口仅允许实际 owner，
  未自动认领旧 local 项目。同名跨用户项目互不混用，拒绝伪造目录身份和存储路径覆盖。

当前相关认证、项目及媒体权限测试共 111 项通过（8 条既有依赖弃用警告），
`uv lock --check` 通过。测试使用临时数据库和 HTTP 模拟响应，没有访问线上用户或支付。
这些结果证明服务/端口行为，不表示 HTTP 入口、Agent 工作进程和整个多用户产品已经完成隔离。

第二块复核已修复并新增回归覆盖：

- 退出在短事务内读取最新会话并删除，然后再解密/撤销网关令牌；
  加密密钥不一致也不能保留已退出的本地 Cookie。
- 原子读取/删除消除“先读旧 token、随后 refresh 成功、再删除会话却只撤销旧 token”的竞争。
- 软删除项目保留 owner 的恢复/彻底删除权限；新任务资格单独要求 active。

第三块代码：`src/novelvideo/api/routes/aigcdo_auth.py`，提供
`create_aigcdo_auth_router(auth, app_origin)`，由应用组合方挂到 `/api/v1`。
对应计划：`docs/superpowers/plans/2026-11-15-aigcdo-auth-http.md`。

- 新增登录、注册、2FA、当前身份和退出 HTTP 接口，均使用 `{ok,data/error}` 格式。
- 浏览器写请求校验明确配置的可信 Origin，不能靠伪造 Host 绕过；
  仅接收不超过 16 KiB 的 JSON，输入错误不回显密码。
- 完整认证成功后签发七天 HttpOnly Cookie，响应禁止缓存，不向浏览器返回网关 JWT。
- 2FA 临时凭据使用五分钟加密 HttpOnly Cookie，未完成验证不创建登录会话。
- 新登录替换原 Cookie 时撤销旧本地会话；网关退出失败仍清本地 Cookie，
  返回 `503` 与 `local_session_revoked=true`，不会谎称网关退出成功。
- 身份接口暂不填充虚假积分；网关余额换算接口接通后再补计费响应及前端类型适配。

新增 `tests/test_aigcdo_auth_http.py` 使用真实 ASGI 路由、Cookie 和临时数据库，
网关 HTTP 使用 MockTransport；包含不跳转注册映射、跨浏览器项目权限、2FA、
CSRF、请求体限制与退出异常。当前合并的认证/项目/媒体测试 **132 项通过**，
Ruff 与 `git diff --check` 通过。
生产 `api/app.py`/端口注册尚未切换到新路由，现有线上页面不会因此自动开放注册。

第三块复核补充修复：

- 在任务预留前调用 AIGCDO 项目授权端口重新检查 active 状态和当前 owner；
  软删除保留恢复权限，但不再凭旧 ProjectContext 提交新任务。任务资格计数不作为安全门禁。
- 拒绝 JSON 转义中的非法 Unicode，登录/注册统一返回安全 400，避免 HTTP 编码异常导致 500。

第四块代码：`src/novelvideo/aigcdo_application_keys.py`，计划：
`docs/superpowers/plans/2026-11-15-aigcdo-application-keys.md`。

- 进一步核实网关 `POST /keys` 已支持用户 JWT、自定义强随机 Key 和 `Idempotency-Key`，
  `GET /keys?search=...` 可分页查询；第一版复用这些接口，无需先新增网关 bootstrap 接口。
- 创作端在安全数据库里按本地用户保存唯一应用绑定，先生成并加密保存 32-byte 随机 Key，
  再通过该用户 JWT 将它登记到运营指定分组。用户不输入 Key，也不选择任意 group_id。
- 同一绑定只有一次 `prepared → uncertain` 创建认领，重复登录、并发开通和重启不会重复 POST。
  Key 与用户、网关用户 ID、分组及随机应用名称一同加密绑定。
- 创建超时后按该用户的 Key 列表精确查回结果；缺失/不明确时保持 pending，
  不盲目重复创建。若请求从未真正到达网关，这类 pending 目前需要运营核对，
  不自动清除状态或换 Key；这是本阶段明确限制。
- 已绑定 Key 每次开通检查都校验用户归属、分组、名称、密钥值、状态及过期时间。
  删除、停用、换组或异常替换后阻止自动补发；重新授权/分组迁移属于显式运营流程，尚未实现。
- `create_aigcdo_auth_router(..., application_keys=service)` 可在完整登录/注册/2FA 后自动开通，
  浏览器只收到 `application.status=ready/pending/blocked`，不会收到模型 Key。
  新增创作端 `POST /api/v1/auth/application` 仅接受空 JSON，用于已登录用户查询/恢复自身开通状态。
- Key 开通失败不把已经成功的用户注册伪装成失败；Cookie 会话保留并返回 pending/blocked，
  生成入口后续必须要求 ready，不能回退共享默认 Key。

本块复核修复：应用 Key 数据库的文件系统/SQLite 故障转换为安全 pending 状态，
不影响已成功注册/登录的 Cookie 签发；存储恢复后可直接继续开通。
若创建认领后、真正调用网关之前本地会话已撤销，则释放尚未提交的认领，
重新登录可正常开通；一旦调用已开始，仍保留不确定状态，不能盲目重发。
5 项新增回归先复现失败后通过。

本块与认证、项目、任务及媒体权限相关测试共 **190 项通过**，Ruff 与差异检查通过。
没有创建线上 Key；自动开通仅在本地模拟网关/真实数据库及 ASGI 组合中验证。

第五块代码：`src/novelvideo/aigcdo_model_runtime.py`，计划：
`docs/superpowers/plans/2026-11-15-aigcdo-model-runtime.md`。

- `AigcdoModelRuntime` 由运营模型目录与应用 Key 服务构造，提供 text/text_stream/image/video 入口。
  每次调用都通过现有会话和应用绑定校验取得该用户 Key，不在进程环境或模型单例中切换凭据。
- 模型和能力必须匹配运营目录，固定访问 `https://api.aigcdo.top/v1`；
  调用参数不能替换 Key、地址、model 或注入 Authorization。
- 文本复用既有 PydanticAI OpenAI 兼容适配器，支持流式输出；
  每次独立客户端完成后按已有生命周期释放。图片复用现有生成/编辑构造器。
- 视频生成器新增显式 `gateway_config` 参数，传入时跳过全局渠道/模型配置；
  每次运行时调用生成新实例，保持提交、轮询及认证下载在同一用户凭据下。
  旧调用方式和组织路径保留原行为，已有视频测试覆盖回归。
- 当前目录支持 OpenAI 兼容模型端点；并非所有原生 Anthropic/Gemini 路由都已接入，
  实际平台模型、参数和可用性仍需运营配置及线上低额度验证。

模型运行时、认证/Key、原模型设置、图片、视频归档与文本适配测试共 **414 项通过**，
包括真实本地会话/Key 绑定服务到文本 HTTP 的完整用户凭据链路。
Ruff、差异检查与密钥扫描通过。测试没有实际付费请求；视频测试复用真实生成流程，
在 HTTP/文件交付边界替换外部服务。该运行时尚未连接主业务路由、Agent 或后台任务，
因此不能认为现有线上生成任务已经切换为用户专属 Key。

第五块复核已补 5 项回归：
文本及流式文本在第一次等待前深拷贝 settings，防止校验后修改模型/Authorization 或嵌套参数；
显式网关视频实例拒绝生成时传入或环境作用域中的 egress 身份覆盖；
图片 background 参数尚无有效传输实现，现改为拒绝而非静默忽略。

扩展执行 `tests/test_p0g4c_video_egress.py` 后总计 468 passed、2 failed。
失败为 `test_direct_video_backends_preserve_platform_and_deny_organization` 和
`test_direct_backends_deny_organization_bound_only_by_request_scope`：
旧 `huimeng_*` 后端被已有模型解析逻辑送进 NewApiVideoGenerator，传入其不接受的 `client` 参数。
用 Git HEAD 原始 `video_generator.py` 在独立 Python 进程中重跑同两项仍失败，
确认是基线问题，未在本次凭据作用域修复中修改这条旧 provider 路由。
因此扩展视频检查不是全绿；414 项通过仅指上述选定的运行时/网关/媒体套件。

第六块代码：`src/novelvideo/aigcdo_billing.py`、
`src/novelvideo/api/routes/aigcdo_billing.py`，计划：
`docs/superpowers/plans/2026-11-15-aigcdo-billing-reads.md`。

- 进一步核实网关冻结/结算源码：视频和批量图片冻结时，`balance` 已扣除冻结额，
  `frozen_balance` 单独增加；所以 `balance` 直接作为可用余额，不能再减冻结额。
- 网关客户端新增 `/user/profile` 与 `/usage` 用户查询，只用当前用户 JWT。
  查询结果严格校验用户 ID、金额、账单类型、时间和分页；空记录的网关 pages 为 1。
- 可组合路由新增 `GET /api/v1/account/billing/balance` 和 `/usage`，
  使用真实 Cookie 会话和 no-store 响应；不需要模型 Key，更不需要管理 Key。
- `CreditDisplayPolicy` 要求显式提供每单位积分数、精度和规则版本，无生产默认比例。
  金额与积分均使用 Decimal 和字符串传输；ROUND_HALF_UP 只用于展示，不修改网关余额。
- 余额响应分开显示 available/frozen；用量采用网关 `actual_cost`、`refunded_cost`、
  `net_actual_cost`，不重算倍率、不重复扣费。订阅用量保留等值积分，但钱包扣款显示为 0。
- 用户、api_key、上游 account、IP/UA 等嵌套信息不返回浏览器；
  拒绝传入任意 user_id/api_key_id/group_id、重复筛选参数、非法分页或反向日期范围。
- 当前提供 UTC 日期与模型筛选、分页用量；没有本地项目关联前，不声称这些记录属于某个项目，
  也不将当前分页统计伪装成完整 earned/spent/refunded 钱包流水。
- 旧 `/credits/me/summary` 契约尚未替换；它的累计账本字段与本次只读响应不同，
  前端页面需要明确适配后再接入，不能填虚假零值。

本块加认证、Key、运行时及项目授权的选定回归 **208 项通过**，Ruff 和差异检查通过。
独立复核未发现 Critical/Important；极端有限金额的 Decimal 溢出已修复，
5 项 HTTP 回归先复现 500 后验证安全 502 和 no-store，覆盖余额、冻结额及三类消费金额。
未访问真实用户账单、未发起支付、未部署。
余额/积分仍属于只读展示；充值订单、固定兑换比例的运营配置和生产页面下一步接入。

第七块代码：`src/novelvideo/aigcdo_payments.py`、
`aigcdo_payment_contract.py`、`api/routes/aigcdo_payments.py`；
计划：`docs/superpowers/plans/2026-11-15-aigcdo-payments.md`。

- 用户 JWT 复用网关 checkout-info、创建余额充值订单、本人列表/详情和主动查单接口；
  不使用管理 Key，不在本地接支付回调或增加用户余额。
- **源码确认网关创建订单没有通用幂等 helper。** 创作端先持久化
  用户＋幂等操作键＋请求摘要的唯一记录，再发送一次 POST；同键改金额/方式返回 409。
  并发、服务重启或请求重放不会再次创建。超时等结果不确定时返回待核对，
  不按金额猜测订单或自动重发；用户可查本人订单，运营核对后再处理。
- 本地数据库只存下单尝试、加密 checkout 响应和当时的积分展示策略，不存钱包。
  数据库写入失败时不发起订单创建；历史订单的积分预估不随之后展示倍率改变。
- 网关 `amount` 是到账 USD 总额（含 bonus），`pay_amount + currency` 是实际支付；
  用权威订单金额换算 expected_credits，不用当前配置重算已经创建的订单。
  完成标志仅对应 `COMPLETED`，`PAID/RECHARGING` 仍需等待网关履约。
- 创建响应后查询该订单验证用户归属、订单 ID、商户订单号、金额、币种和支付方式；
  详情、列表和主动查单也验证本人归属，查询结束后再次确认 Cookie 未被退出。
- 已保存 checkout 重放时查询最新订单状态，完成、取消、失败、退款或过期后不再给出可支付信息；
  当前关闭新充值不影响恢复已有订单。
- 本阶段只支持 balance 类型的 alipay/wxpay HTTPS 收银台或二维码，
  二维码还支持微信原生 `weixin://wxpay/bizpayurl`。不返回原始 HTML、JSAPI、
  Stripe client_secret、OAuth 或 resume_token；遇到不支持的结果保留待核对状态，不重复下单。
- 回跳 URL 固定为运营配置的创作端 origin＋`/payment/result`，
  Referer 也由服务端固定，符合网关现有回跳 host/path 校验；不接受浏览器自定义回跳地址。
  创作端该回跳页面仍待前端接入；运营生产组合时不能先暴露未完成的支付入口。

新增可组合 `/api/v1/account/payments` 路由：
`GET /checkout`、`GET /orders`、`GET /orders/{id}`、
`POST /orders`（必填 Idempotency-Key）、`POST /orders/{id}/verify`（只允许空 JSON）。
所有写请求校验可信 Origin，余额/订单查询不接受 user_id、状态注入或重复分页参数。

本块合并认证、Key、模型运行时、计费读取和项目授权测试 **240 项通过**，
Ruff 和差异检查通过；独立复核进行中。所有订单和支付渠道均为本地模拟，
未创建线上订单、充值或修改网关配置，也未部署生产路由。

第七块复核未发现 Important/Critical，补充两项：
首次下单遇到网关超时/服务错误即返回 `payment_pending`，持久化操作号保持不变，
避免用户误以为一定没创建；新增 amount=22.55、bonus=2.05、实付=10.25 的回归，
证明比例 100 时预计积分为 2255.0000，不重复叠加赠送。
补充后相关后端套件 **241 项通过**（8 条既有依赖警告）。

第八块前端：

- 新增 `/account` 账户页和 `/payment/result` 回跳页，路由进入前调用真实 `/auth/me`
  获取用户 ID，不能凭浏览器缓存的 role 当授权。页面与二维码模块采用 lazy chunk。
- 新增 `frontend/src/lib/queries/aigcdo-account.ts`，复用现有 Cookie API 客户端，
  Zod 校验余额、用量、订单及 checkout；金额保持字符串，不用浮点重算赠金和兑换。
- 账户页分开展示可用/冻结积分、钱包/订阅用量、充值表单及分页订单；
  网关异常显示不可用，不显示虚假 0。支付状态以服务端查询为准，
  `PAID/RECHARGING` 显示等待入账，`COMPLETED && fulfilled` 才显示已到账。
- 下单前按用户 ID 在 sessionStorage 保存金额/方式/操作号；
  网络失败、pending 或页面重载重试均使用相同操作号，不自动发新单。
  未确认订单时锁定原表单，存储失败或损坏时拒绝下单；已知终态后才能手动开始另一笔。
- 浏览器不持久化支付 URL、JWT、模型 Key 或网关 resume_token。
  React Query keys 包含用户 ID，用户变化时重挂账户内容，离开页面会取消未完成请求。
- 支付链接再校验 HTTPS；二维码使用 `qrcode` 在本地生成，不调用第三方二维码图片接口。
  已完成/过期/取消、查单失败或正在核验时不显示旧支付入口。
- 回跳只接受单个合法正整数 order_id，忽略 status/sign 等支付结果提示；
  默认只读轮询当前订单，主动验单由用户点击，验单成功刷新账户余额。
- 四种语言新增 `public/locales/{zh,en,pt,vi}/account.json` 独立命名空间；
  遵循现有设计 tokens 和 Button/Input 原语，没有修改全局 CSS 变量。

独立复核的四项 Important 已修复：

- 共享页面框架使用 `h-dvh overflow-y-auto overflow-x-hidden ui-scrollbar`，
  适配根布局的固定高度，避免小视口下充值/用量区域无法滚动。
- 新操作先按 checkout 公布的全局上下限做精确十进制比较，再保存操作号。
  只有服务端明确返回 `payment_not_submitted` 才释放表单；
  普通 400、网络失败和不确定结果仍保留原操作号。
  服务端在同一 SQLite 原子认领事务内加密持久化“未提交”结果，
  禁止较早开始但较晚完成预检的并发请求继续下单；修改金额后使用新操作号。
- focus/storage/会话变化会清理并取消私有页面状态，重新读取 `/auth/me`；
  下单和验单前再次检查身份，所有账户请求携带 `X-AIGCDO-User-ID`。
  服务端把该预期身份与实际 Cookie 用户比较，不一致在读取/创建订单前返回 409。
  `/me` 仍返回旧身份时停止恢复并提示刷新，避免重复挂载导致无限请求。
- 验单先取消已有订单 GET，暂停轮询/手动刷新，再发布验单结果，
  防止较早的 PENDING 响应覆盖 COMPLETED 并恢复支付链接。

复核中的空分页 Minor 经核对不适用：网关客户端 `usage()` 校验
`pages=max(1, ceil(total/page_size))`，已有新用户空列表 `pages=1` 回归；
因此保持前端正整数分页契约，未放宽为不可从当前后端返回的 `pages=0`。

账户新增测试现为 **47 项**，连同既有支付/认证回归 **105 项通过**；
相关认证/Key/模型/计费/支付/项目后端套件 **245 项通过**（8 条既有依赖警告）。
`pnpm build:ce`（含 TypeScript）通过，存在既有大 chunk 提示；
`design.md lint` 为 0 errors / 15 基线 warnings。
生产 API 工厂尚未启用本系列路由，因此页面源码完成不代表现有线上站点可以充值；
主导航切换和部署需与认证、Agent、权限和运营配置一并完成。
当前没有可用浏览器，未完成真实截图/支付二维码扫码或线上付款验收。

### 第九块：注册/登录界面及开通恢复

计划：`docs/superpowers/plans/2026-11-15-aigcdo-registration-ui.md`。

- 网关客户端新增 `public_auth_settings()`，严格解析认证开关及协议文档，
  可组合认证路由新增 `GET /auth/ui-config`，仅返回前端所需字段和
  `auth_provider=aigcdo`，不透传网关 Logo、其他设置或凭据，响应 no-store。
- 现有 `LoginCard` 按服务端 provider 选择 AIGCDO 表单，复用登录页和弹窗；
  强制认证的 CE 也会读取认证 UI 配置，不再只在 EE 请求这个配置。
- 邮箱密码注册/登录、六位 2FA、ready/pending/blocked 状态和开通恢复均使用原 Cookie API。
  202 只进入验证码步骤，不能写成完整用户身份；旧 auth-store 也增加 202 拒绝保护。
- 注册成功但 Key 尚未开通时保留已登录状态，提供账户链接和“重试开通”，不会重新注册。
  开通恢复先读取真实身份，再用预期用户请求头约束服务端 Cookie，跨标签页换账号会被拒绝。
- 密码/验证码只保留在当前表单内存，完成/转入 2FA 时清除，不写 local/sessionStorage。
  ready 后清理旧 auth-store 并完整跳转创作页，避免复用上一账号的页面内存缓存。
- 登录协议从真实配置读取，以可折叠纯文本展示，勾选绑定当前 revision，不执行 Markdown 内的 HTML。
  配置错误不显示可提交表单；普通错误使用本地文案，不回显网关响应原文。
- 注册超时/5xx 显示“结果未确认，先尝试登录”，不自动重试注册；表单提交防重复点击，
  离开页面取消未完成请求。中英葡越四种语言已补齐文案。

本轮只读复验公开配置：注册开启、邮箱验证/密码找回关闭、登录协议开启、
Turnstile/腾讯/阿里验证码均关闭。远端 SSH 读取未成功，未修改远端文件。
由于未重新取得验证码发送/找回/邀请码/captcha 的完整源代码契约，
本块不编造这些请求：一旦网关开启未接入的注册前置验证，入口明确说明暂不支持。
这部分 N02/M12 仍待完成，不能将当前邮箱注册流程标记为全部认证功能完成。

第九块独立复核修复：

- provider 发现失败保留 `unavailable`，现有 LoginCard 显示配置重试界面，
  不能悄悄切回旧密码表单绕过 AIGCDO 协议/开通状态。
- 认证配置显式启用焦点刷新（覆盖主应用默认关闭焦点刷新的配置）；
  每次提交登录/注册/2FA 前再次读取配置，协议 revision 变化须重新勾选，
  新增未支持验证前置条件或配置失败时不发送认证写请求。
- 原共享 API 客户端的 401 处理会把弹窗中的输错密码/2FA 当作会话失效，
  导致登出、清除挑战 Cookie 并跳转。本次将三类凭据提交端点从自动登出中排除，
  受保护 API 的 401 仍执行原会话失效处理。
  此项复核原标 Minor，按“两步验证码重试被清除”影响升级并修复。

八项复核复现先失败再通过；另补真实 API hooks 的受保护 401 对照与生产 QueryClient
默认配置下的焦点刷新。最终选定前端 **12 文件、151 项通过**，
后端相关套件 **256 项通过**（8 条既有依赖警告）；Ruff、密钥扫描和差异检查通过。
复核修复后的 `pnpm build:ce`（tsc＋Vite）通过，保留既有大 chunk 提示；
四种语言 82 个键及插值一致，包含未跟踪文件的直接内容扫描未发现密钥。
没有将版本切换成 EE；没有真实注册、签发 Key、消费、充值或部署。

### 第十块：实际 app 组合、强制认证与项目权限

计划：`docs/superpowers/plans/2026-11-15-aigcdo-app-composition.md`。
配置说明：[`docs/aigcdo-deployment.md`](aigcdo-deployment.md)。

- `SUPERTALE_AUTH_PROVIDER=aigcdo` 明确选择 AIGCDO 组合，仍为 CE。
  `AigcdoDeployment.from_env()` 要求显式 origin、持久化目录、稳定加密密钥、
  应用分组、积分比例/精度/版本；未猜任何生产默认值。
- registry 注册真实 auth、project_registry/project_access、audit_sink 和生命周期；
  不先注册单用户端口再覆盖一部分，不提供 local AuthSession、任务后台或全局模型凭据。
  已启动进程更换 provider、已污染端口表或缺失/非法配置均拒绝启动。
- 实际 `api/app.py:create_app()` 挂载前九块认证/余额/支付路由和已核查项目/文件路由，
  `/config` 明确返回 `auth_required=true`、`auth_provider=aigcdo`。
- 公共端点按 HTTP 方法和完整路径列出；私有 API/静态文件先查真实 Cookie，
  写请求验证可信 Origin，Bearer/query credential/local trust 不能绕过；
  私有响应禁止缓存，WebSocket 尚不开放。
- 同名跨用户项目分别创建/列出/读取，A 不能读 B 的项目配置与文件。
  网关管理员不自动获得旧 local 项目；项目 ID 和文件路径保持原样。
- 旧模型网关/全局任务额度/诊断接口对普通用户 403、管理员 410。
  未接用户身份的业务入口返回 `503 aigcdo_integration_pending`，
  不能进入旧全局 Key 或单用户任务实现。
- AIGCDO 启动不运行旧目录同步、director 自动任务恢复；生命周期关闭网关 HTTP 客户端。
  冷进程 `registry → app → lifespan → 匿名请求拒绝 → shutdown` 冒烟通过，
  没有请求真实网关。
- 前端整页跳转后的 AIGCDO 登录用 `/auth/me` 恢复 Cookie 身份，
  不信 localStorage 的用户名；CE 配置加载失败同样保持需要登录，
  AIGCDO/配置不可用时 `VITE_AUTH_MODE=local` 不生效。

独立复核修复了 app 构造后、startup 前切换 provider 导致旧路由与新身份端口混用的缺口；
startup 现在先检查 provider 及已捕获的部署实例，任何变化都拒绝启动。
同时为下游未处理异常提供安全 JSON 与 `no-store`，避免外层 500 丢失私有响应缓存限制。
三项回归先复现失败再通过。

最终相关后端 **348 项通过**（112 条依赖/既有 on_event 弃用警告），前端 **13 文件、158 项通过**；
CE build（含 tsc）、Ruff、差异检查、gitleaks 钩子及未跟踪文件直接扫描通过。
尚未部署，生成/Agent/真实工作进程隔离继续下一块，
因此“app 可组合启动”不等同于“全部创作功能可对外上线”。

### 第十一块第一段：任务/Agent 授权与执行凭据

计划：`docs/superpowers/plans/2026-11-15-aigcdo-execution-authority.md`。
核心实现：`src/novelvideo/aigcdo_execution.py`。

- 现有 TaskEnvelope producer/consumer 复用；新增持久化 root_task_id 授权绑定，
  绑定发起用户、原浏览器会话引用、项目、任务类型/载荷摘要及有效期。
  同一 root 不能替换父会话、用户、项目或载荷；只存加密授权，不把 Cookie/JWT/模型 Key 放入任务。
- 用户会话服务增加内部 `load_reference/verify_session_reference`，仍使用原有刷新认领、
  网关实时身份校验和本地撤销逻辑。引用是 Cookie 哈希，不是 HTTP 登录凭据；
  提交引用到 Cookie 接口仍被拒绝。
- `ensure_for_session` 与已有应用 Key 服务共享同一开通/校验逻辑，执行时确认当前分组、
  归属、Key 状态和过期。没有按用户查询“最新登录”来替代旧会话；
  退出后重新登录不会使旧任务恢复执行资格。
- 复用 `AdmissionContext` 的 platform principal，但 ID 为真实用户，
  credential reference 使用 `aigcdo-task:<root>` 独立空间，由 AIGCDO resolver 解析，
  不使用单用户 LocalModelCredentials 或进程共享 Key。
- `AigcdoModelRuntime` 接受经过消费校验的 `VerifiedTaskDelivery`，
  校验授权记录中的项目/载荷摘要后逐次解析用户 Key。
  已用真实文本适配器＋HTTP 模拟完成“签名任务→执行校验→该用户 Key→模型响应”的链路测试。
- 新 auth_session 端口使用短期随机 Agent token，数据库只保存 token 哈希及加密授权。
  创建依赖服务端浏览器上下文，不能凭任意 username 生成令牌；权限限于现有允许 scope，
  项目必须实际归属发起用户。期限最多 24 小时且不超过原 Cookie 会话。
- Agent scope 更新必须来自同一原父会话且有目标项目权限；更新不延长 TTL。
  重启可以恢复验证，过期/退出/网关停用/项目状态变化会拒绝；并发撤销后不会返回旧授权。
  Agent token 不再进入 DTO repr。
- AIGCDO deployment 已注册 auth_session/authz/model_credentials/task_envelope_consumer，
  私有 Cookie 请求绑定执行父上下文。没有注册旧 InlineTaskBackend，
  HTTP Bearer、chat/生成和 WebSocket 仍保持之前的拒绝/未接线状态。

本段先完成执行身份基础，尚未等同于完整生成队列上线：
下一段需逐类把现有业务 runner 调用改到用户运行时、绑定任务参数/模型目录、
完成队列认领/取消/重试及费用不确定恢复；随后再开放经 scope 校验的 Agent API。
Hermes 进程身份/专属模型配置与操作系统挂载隔离也仍需完成。
任务签名仅证明身份/载荷完整，**不声称已实现付费调用去重**；
不能直接把旧全局模型 runner 挂上这个 consumer 就开放使用。

独立复核补充修复：

- 不能只在网关 Key 查询结束后确认父会话：之后的项目查询期间也可能完成退出。
  现在返回任务/Agent 授权前，以一个 SQLite 查询快照联合检查原会话仍有效、身份 active、
  授权未撤销/未修改且未过期；避免两个数据库分别检查留下交错窗口。
- Key 存储故障、待核对开通等 503 不再错误转换成永久授权拒绝；
  通过 `AuthzServiceUnavailable → TaskAuthorityUnavailable` 保持现有 consumer 的故障分类。
  真正的分组/Key/用户权限问题仍拒绝。
- 原 producer 的禁止凭据载荷校验移到授权持久化前调用；
  带 `api_key` 的内部错误载荷不能占用 root，修正后可重新申请同一任务号。
  此项按“失败预检不应消耗不可变操作号”的恢复影响一并修复。

以上七项复现先失败后通过；最终相关后端 **490 项通过**
（144 条依赖/既有 on_event 弃用警告），Ruff、差异检查和密钥扫描通过。
新增回归覆盖并发两用户、篡改、固定绑定、重启、TTL、加密绑定、父会话刷新/注销、
账号与 Key 停用、项目归属/删除状态、并发撤销及真实文本协议。
未运行真实模型、启动 Agent 进程、迁移 local 项目或部署。

### 第十一块第二段至第十三块：创作接线、用户 Key、配置收敛（2026-11-16）

**方案变更：**原“独立文本队列＋逐类重写 runner”作废并删除
（`aigcdo_text_queue.py`、`api/routes/aigcdo_text.py`、旧 `AigcdoModelRuntime`）。
改为复用现有任务引擎和全部生成器，只替换凭据来源：

- `aigcdo_model_runtime.py`：运营模型目录（`AIGCDO_MODEL_CATALOG`，JSON，只含模型元数据，
  带 Key 或外部地址即拒绝启动）＋当前用户 Key 作用域。`model_gateway_settings` 在 AIGCDO 下
  不再读写 `settings.db`，而是返回“目录＋作用域内用户 Key”；作用域外 Key 为空，调用直接失败。
- 任务：注册现有 `InlineTaskBackend`，producer 为 `AigcdoExecutionAuthority.sign_top_level`
  （绑定发起会话），执行前 `task_run_scope` 重新校验会话/项目/Key 后在工作线程绑定该用户 Key；
  子进程通过 `AIGCDO_SCOPED_API_KEY` 继承。请求内联模型调用由边界中间件绑定调用者 Key。
- 文本模型在 AIGCDO 下每次请求解析 Key（Agent 单例不持有 Key）；Cognee 进程级配置只放占位符。
- 启动时若环境里存在任何共享模型 Key（`NEWAPI_API_KEY` 等，见 `SHARED_CREDENTIAL_ENV`）拒绝启动。
- app 组合挂载完整 `api_router`；边界继续拒绝旧管理接口，并暂不开放
  `/chat`、`/freezone/agent-config`、`/freezone/skill-imports`（503 pending）。
- 前端：AIGCDO 下隐藏模型配置/任务额度/媒体存储设置页与相关轮询，账户菜单新增“余额与充值”，
  隐藏本地头像/改密入口。
- 迁移脚本 `scripts/aigcdo_migrate_local_projects.py`（默认预览，`--apply` 才写，先备份）。
- 示例目录 `docs/aigcdo-model-catalog.example.json` 由当前部署的分组导出（不含 Key；
  SiliconFlow 的 Embedding 分组因是外部地址未纳入）。

验证（均为 MockTransport，无真实网关写入）：AIGCDO＋端口＋环境棘轮 **430 项通过**；
含“两用户各自 Key 经任务引擎完成文本生成”、“150+ 条项目路由跨用户 GET/DELETE 无一成功”、
“退出后任务不可消费”、“媒体凭据随作用域”、迁移预览/应用。后端全量 7994 通过、14 失败，
其中 13 项在未改动 HEAD 上同样失败（视频后端/积分路由基线），第 14 项（环境变量棘轮）已修复。
前端全量 **5184 项通过**，CE build 通过。只读核对网关：分组 41 active、10 个目标分组、
注册开启、邮箱验证/找回关闭、新用户默认余额 0.1、`session_binding_enabled=true`。

**当时仍未完成（其中隔离、Embedding、端到端调用和真实注册已在下一节完成）：**

- 第十二块 OS 级隔离未做。当前靠“不开放 Agent/对话”规避：没有用户可控代码执行入口时，
  进程内 runner 只按已授权项目路径读写。开放 Agent 前必须完成。
- 已知限制（代码内 `shortcut:` 注释）：任务运行期间 Key 只校验一次；文本任务不再有
  “结果不确定永不重发”的专用保护，沿用引擎原有语义。
- Embedding 无网关模型，小说导入/知识图谱（Cognee）在 AIGCDO 下不可用，需运营确认网关 Embedding 模型。
- 图像/视频/音频只验证了凭据解析，未做端到端模型调用；真实注册、Key 签发、扣费、支付、部署均未执行。
- 未做独立代码复核（复核子任务两次被限流中断）。

### 第十二块与真实联调（2026-11-16 至 11-17）

用户指示：Embedding 由管理员自定义配置、不必绑定自有网关；用测试账号做真实联调；
工作进程隔离按推荐方案；后续部署到云服务器。部署说明已重写，见
[`aigcdo-deployment.md`](aigcdo-deployment.md)。

**真实联调（测试账号，网关用户 ID 154，分组 41；凭据只在本机 `/root/aigcdo-e2e/`，未进仓库）：**

| 步骤 | 结果 |
| --- | --- |
| 创作端注册 | 一次请求完成网关注册和应用 Key 开通，`application.status=ready`；管理接口核对该用户在网关上恰好 1 把 Key |
| 余额/用量/支付配置/订单 | 读取正常；新用户余额 0.1 USD，按 100 积分/USD 显示 10.00 |
| 文本（gpt-6.1-sol） | 完成；网关记 0.0005712 USD，余额精确减少同额 |
| 图像（gpt-image-2） | 完成，1088×608 PNG；记 0.028665 USD。本人 Cookie 取图 200，无 Cookie 401 |
| 视频（minimax-h3-f-fast，480p 4 秒） | 完成，864×480 H.264 4.46 秒；记 0.06 USD |
| 余额不足 | 网关返回 403 `insufficient_balance`；任务失败并带 `INSUFFICIENT_CREDITS` |
| 进程重启 | 会话、Key 绑定保持有效 |
| Embedding（SiliconFlow `BAAI/bge-m3`） | 经应用自身路由调用成功，1024 维 |
| 对话助手（部署镜像内） | 沙箱内的 Hermes 工作进程完成一轮对话并通过短期令牌读到项目状态；4 次模型调用都记在该用户账上 |

联调期间用管理接口给测试账号加了 2 USD 余额（带幂等键）。这是本轮唯一的网关写操作。

**联调暴露并已修复的问题（都先写了失败用例）：**

- 真实启动必然失败：Cognee 配置在导入时把占位 Key 写进环境变量，被“禁止共享 Key”检查拦下。
  此前的测试都绕过了 CLI 的导入顺序。
- 余额在调用前只剩 0.0108 USD 时，0.0287 USD 的图像请求仍成功，余额变成负数。
  这是网关侧行为（图像按次计费、事后扣款），创作端无法阻止；文本请求在余额为负时被正确拒绝。
- 余额不足没有映射成专用错误码，前端显示的是原始英文报错。现已映射，并且 AIGCDO 下文案改为
  “请在余额与充值中充值”，不再让用户“联系管理员”。
- 每个私有请求都向网关查一次身份（实测约 0.2 秒）。浏览器请求现在复用 30 秒内的校验结果；
  本地退出和过期仍即时生效，任务与 Agent 授权仍每次查网关。
  代价：网关侧停用账号或重置密码最多 30 秒后才在浏览器请求上生效。
- 模型广场缓存过期后在后台线程刷新，线程拿不到当前用户的 Key，说明和价格会消失。
- `bge-m3` 拒绝 `dimensions` 参数（真实 400）。AIGCDO 下不再发送该参数，运营填模型原生维度。
- 对话每一轮都被拒绝（“执行授权已失效”）：请求路径向授权端口申请组织出网身份，
  而 AIGCDO 的端口只认它自己签发的任务。AIGCDO 没有组织，该路径现在直接返回“无组织身份”。

**Embedding：** `AIGCDO_EMBEDDING_{BASE_URL,API_KEY,MODEL,DIMENSIONS}`，运营自己的 Key，
任意 OpenAI 兼容服务。它不进入用户的配置行，也不会被用户 Key 替代。
核对现有 12 个项目全部是 `structured_v1`，新建项目也是，这条管线不用 Embedding；
所以上一轮“小说导入不可用”的说法不准确——只有旧的知识图谱项目需要它。

**工作进程隔离（#346 P1②，第一项）：** 多用户下每个 Hermes 工作进程由 bubblewrap 包装：
数据根目录和认证数据目录整体隐藏，只挂回当前用户自己的目录（只读）；独立 PID 命名空间；
只有工作进程自己的目录可写；没有无沙箱降级；聊天后端固定为 Hermes。
启动时真实试跑一次，不满足就自动停用对话助手，其余功能不受影响。

- 在部署镜像里跑验收用例：包装后的进程读不到另一用户的三类目录、项目注册表、认证数据，
  也读不到 API 进程环境里的加密密钥；嵌套命名空间也解不开隐藏。去掉挂载隔离后该用例如期失败。
- 对真实运行中的工作进程核对：独立的 PID/挂载命名空间，状态目录下只有该用户一项，
  环境里的模型 Key 是占位符。
- Docker 下需要 `seccomp`、`apparmor`、`systempaths` 三项都放开，逐项实测缺一不可
  （覆盖文件 `deploy/docker-compose.aigcdo.yml`）。代价是 API 容器自身失去这三层默认加固。
- 宿主机没有 `bwrap`，所以该验收用例在本机 `pytest` 里是跳过的，只在镜像里跑过。

**验证：** AIGCDO、沙箱、环境棘轮相关后端 345 项通过、1 项跳过。后端全量 8010 通过、15 失败：
12 项是上一轮已确认的 HEAD 基线；`test_new_projects_are_structured…` 在未改动的 HEAD 上同样失败；
`test_director_auto…` 单独重跑通过；compose 文件清单那一项由本轮引入，已把覆盖文件移到 `deploy/` 修复。
前端全量 5186 项通过，CE 构建通过。`check_backend_i18n` 仍因 `video_generator.py` 的既有问题为红。

**仍未完成：**

- 工作进程出站网络未限制（#346 P1② 第二项）。云上需在安全组挡掉实例元数据地址。
- 技能导入、Agent 配置未按用户拆分，保持 503。
- 邮箱验证、找回密码未接入（网关当前关闭）；注册限流与真实客户端 IP 透传未处理。
- 充值只验证到读取支付配置，未创建真实订单、未付款。
- 存量 `local` 项目未迁移（等目标网关用户 ID）；未部署到云服务器；改动未提交。
- 已知限制不变：任务运行期间 Key 只校验一次；文本任务结果不确定时沿用引擎原有重试语义。

### 独立复核与浏览器走查（2026-11-17）

**独立复核**（另一个上下文只读审查本轮改动）：无 Critical，1 项 Important，已先复现再修：

- 沙箱把 `state/_shared` 挂回给了每个用户的工作进程，那里有所有用户的草图编辑回放记录。已不再挂回。
- 同时收紧：仓库目录只挂回 `src`、`integrations`、`.hermes`、`.venv`，
  不再整体可见（原先 `.git`、日志和源码目录下可能残留的旧数据都能读到）。修后在镜像里复验通过。

复核提出、未改的 Minor（已知限制）：

- 迁移后的旧 `local` 项目目录仍在 `state/local/<项目>` 下，新 owner 的工作进程看不到它，
  这些项目里的对话助手会失败（不泄漏）。迁移时需要一并处理，见剩余清单 15。
- 同一用户开两个浏览器会话时，后登录的会替换工作进程，另一个会话进行中的那一轮对话会中断。
- 工作进程令牌在路径不含 `/projects/{id}` 的接口上不受项目范围限制（仍限于本人和本人的 Key）。
- 回环校验依赖前置代理添加 `X-Forwarded-For`。仓库自带的 nginx 模板满足；
  自建代理若直连 API 且不加该头，泄漏出去的工作进程令牌可以从外网使用。
- 模型广场缓存是进程级的，由先到的用户的 Key 拉取；目前所有用户同一分组，内容相同。

**浏览器走查**（无头 Chromium，预览站点 `https://10.10.1.88:8443`，即镜像＋工作区代码＋CE 构建产物）：

用户反馈“前端看不到实现的界面”。原因是 `:8080` / `:443` 那套站点是 11-13 构建的单用户容器，
没有启用 AIGCDO 模式；界面本身都在。逐页走查结果：

| 页面 | 结果 |
| --- | --- |
| 登录弹窗 | AIGCDO 邮箱登录表单，带网关的四份协议和勾选项 |
| 注册 | 邮箱＋密码＋协议，“创建账号” |
| 登录 → 项目中心 | 正常，只看到本人项目 |
| 账户菜单 | 公告、余额与充值、语言、退出 |
| 账户页 | 可用/冻结积分、充值表单（支付宝/微信）、订单、模型用量（与联调的 9 笔一致） |
| 项目画布 | 正常打开，任务流“已连接”，控制台无报错 |
| 对话助手（画布助手） | 在浏览器里完成一轮回复 |
| 退出 | 回到登录页；未登录访问 `/account` 被带回登录页 |

走查发现并修复：

- 账户菜单显示的是内部用户名 `aigcdo_01m7…`。`/auth/me` 现在带上网关邮箱，菜单显示邮箱。
- 设置弹窗只剩“虾画 Skills”一页且永远“加载中”（后端 503）。AIGCDO 下隐藏设置入口，
  并且不再请求被保留的 agent-config 接口（原先每次进项目都有一条 503 报错）。
- 画布助手的 `config.yaml` 被中途杀掉的进程写坏后，之后每次启动都沿用坏文件，
  工具限制策略不再套用。现在无法解析的配置会按模板重建（既有代码的缺口，与 AIGCDO 无关）。

未确认：画布助手回复“无法读取画布状态”。画布是空的，我没有分清这是空画布的正常回答，
还是画布上下文桥接在沙箱下不通。退出登录时网关 `logout` 仍返回 502（已知的网关侧问题），
创作端本地会话已撤销、界面正常跳转。无头环境下登录页的开场视频是黑的，未检查视觉效果。

**验证：** 相关后端 448 项通过、1 项跳过；前端全量 5186 项通过；CE 构建、Ruff 通过。

### 本机站点切换与存量迁移（2026-11-17）

用户同意把 `:8080` / `:443` 站点切到 AIGCDO 模式，并把 `local` 项目迁给 用户指定的账号
（网关用户 ID 220，管理接口只读查得）。

- 用 `docker-compose.yml` 叠加 `deploy/docker-compose.aigcdo.yml` 重建并启动；
  `AIGCDO_APP_ORIGIN=https://10.10.1.88`，分组 41，积分 100/USD、2 位小数（沿用联调值，用户未另行指定）。
- 迁移脚本新增 `--create-identity`：目标用户尚未在本站登录时预建身份映射，首次登录按网关用户 ID 认领。
  先预览再执行：13 个项目（10 进行中、1 归档、2 回收站）全部改归该用户，项目 ID 和目录不变。
  备份：卷内 `state/local/projects.db.before-aigcdo-1794910233`，以及 `/root/aigcdo-e2e/backup-before-switch/`。
- 工作进程沙箱额外挂回“当前已授权项目”的三个目录，解决迁移后项目目录仍在 `local/` 下、
  新 owner 的对话助手看不到的问题（复核 Minor 第一条）。
- 切换后匿名检查通过：`/config` 报 `auth_provider=aigcdo`，无 Cookie 访问项目返回 401，对话助手启动探测通过。

**阻塞：网关在当天开启了 Turnstile 人机验证。** 上午联调时关闭，切换后实测网关对不带验证令牌的登录返回
400 `TURNSTILE_VERIFICATION_FAILED`。创作端未接入人机验证，按设计把登录和注册都标为不支持，
因此切换后的站点目前无法登录，迁移结果也还没能用目标账号在浏览器里核对。

**Turnstile 已接入（同日）。** 登录/注册表单在网关开启 Turnstile 时渲染 Cloudflare 组件，
用网关公开的站点密钥；令牌随登录/注册请求转给网关校验，每次提交后换新令牌；CSP 放行
`challenges.cloudflare.com`。后端 302 项、登录表单 16 项测试通过，已重建部署。
浏览器实测组件能加载，但 Cloudflare 返回错误 `110200`（当前访问地址不在该站点密钥的允许域名里），
所以用 `https://10.10.1.88` 仍然拿不到令牌、登不上。需在 Cloudflare 把创作站点的域名加进该组件的允许主机名，
并用该域名访问（同时把 `AIGCDO_APP_ORIGIN` 改成它）。

回滚方法（如需要）：停服，用上面的备份覆盖 `state/local/projects.db`，
再 `docker compose up -d api web`（不带 AIGCDO 覆盖文件）。

### 生产部署（2026-11-17）

提交 `6a638b31` 已推送。按用户要求部署到生产服务器，域名 `canvas.aigcdo.top`，本机恢复单机模式。

- 本机：还原迁移前的项目注册表与 `.env`，不带 AIGCDO 覆盖文件重启；13 个项目可见、免登录。
- 生产：服务器只有 4 GB 内存且跑着另一个产品，镜像在本机构建后 `docker save | docker load` 传过去；
  部署目录 `/opt/aigcdo-canvas`（compose、`.env`、模型目录），API 内存上限 1800 MB，web 只监听 `127.0.0.1:8088`。
- nginx 新站点 `canvas-aigcdo`，用服务器上已有的 Cloudflare Origin 证书（`*.aigcdo.top`）；原有站点复测 200。
- 配置随迁：模型目录（本机现有 7 个分组导出）、Embedding、MinIO 媒体中转（改用环境变量）、任务并发额度。
  存量项目文件按用户要求暂不传。
- 公网验证：`/config` 报 AIGCDO 模式；未登录访问项目 401；登录表单显示 Turnstile 组件，
  在该域名下不再报 `110200`。无头浏览器过不了 Cloudflare 的人机检测，真实登录需人工点一次。
- **对话助手在生产上自动停用**：该机 `kernel.apparmor_restrict_unprivileged_userns=1`（Ubuntu 24.04 默认），
  bubblewrap 报 `setting up uid map: Permission denied`。按设计失败即关闭，其余功能不受影响。
  启用需要在宿主机把该 sysctl 设为 0（会放宽整台机器的限制，待用户决定）。
- 2026-11-19 服务器换了公网 IP。厂商的换 IP 脚本（cloud-init 执行）把所有网卡的地址清空，
  docker 网桥的网关地址也没了：容器仍是 healthy，但宿主机访问不到容器、容器也出不了网，整站超时约 2.5 小时。
  把 `docker network inspect` 里的网关地址加回网桥后恢复，没有重启容器。再换 IP 时先看 `ip -4 addr` 里网桥有没有地址。

### 管理员、账单积分化、品牌清洗（2026-11-17 至 11-18，已部署 `2dc984a9`）

执行文档：`docs/superpowers/plans/2026-11-17-aigcdo-admin-brand-ui.md`。

- 管理员 = `AIGCDO_ADMIN_USER_IDS` 点名的网关账号（生产为 220）。照常登录和创作，右上角多“设置”：
  单机模式的模型与渠道/任务与队列/媒体存储，加积分比例、公告。曾做过环境变量密码＋`/admin` 页，按用户要求删除。
- 用户读到的是“管理员设置的用户视图”：网关分组换成用户自己的 Key，外部地址只允许 Embedding。模型目录文件降为首次启动的初始值。
- 账单接口和页面只显示积分，不再返回美元金额与比例。
- 界面只保留中文；产品名改为 造境/藏境/灵感/镜界/片场/导台/范式，画布助手为“智核”；吉祥物与小游戏删除。
- 登录页保留布局，去掉原项目 GitHub 入口，商务二维码为占位图；帮助链接暂指 `https://api.aigcdo.top`。
- 测试：后端全量 8016 通过（13 项失败为 HEAD 基线）；前端全量 5157 通过。人机验证临时关闭期间，用测试账号在预览站点真实登录验证了管理员入口与账户页。
- 未做：独立复核（子任务随会话中断）；充值故障待用户复测；`/download` 页与旧登录舞台组件仍有原项目链接；登录页视频仍走原项目 CDN。

### 画布助手读写画布失败（2026-11-18 至 11-20，已部署 `e713c060`）

现象：生产上“智核”能对话，改节点时回复“画布操作当前报错”。Hermes 会话库里的工具结果是
`ModuleNotFoundError: No module named 'ulid'`，排查时库里的 4 次画布写入调用全部失败。

原因（镜像从首次部署起就是这样，与 11-18 的几次热更新无关：`3bd47756` 镜像实测同样缺包）：

- 画布插件 `.hermes/plugins/freezone` 跑在 Hermes 的解释器里（镜像中是系统 `/usr/local/bin/python`），
  不是 API 的虚拟环境。那里没有 `jsonschema` 和 `portalocker`，插件开头的导入被 `try/except` 吞掉，
  工作流目录和画布桥接都不可用。11-17 走查时没确认的“无法读取画布状态”就是它。
- 写画布时还要导入 `workflow_preflight`，它为了一个常量导入 `novelvideo.api.schemas`，
  连带加载整个 API 包，在 `python-ulid` 处失败。
- 单机模式默认用 Codex，工具由 API 虚拟环境里的 MCP 服务提供，所以本机没有这个问题。

修复：常量挪到 `official_defaults.py`，`workflow_preflight` 不再碰 API 包；`Dockerfile` 和
`scripts/setup-hermes.sh` 按应用锁定的版本把 `jsonschema`、`portalocker` 装进 Hermes 的解释器，
镜像构建时对插件的导入做一次检查。`tests/test_local_runtime_dependency_isolation.py`
模拟 Hermes 解释器里有的包，防止插件的导入闭包再引入别的依赖（只覆盖导入期，函数内的延迟导入不在内）。

同一批还修了两个与多用户无关的问题：助手把命令的 `type` 写成 `command_type` 时整轮被判失败
（单机 Codex 下表现为“画布操作未完成：tool_arguments_invalid”）；视频节点手填的清晰度被改回 720p。

验证：在部署镜像里以 AIGCDO 模式、按用户沙箱启动 Hermes 的解释器，真实执行
`freezone_update_node_data` 的处理函数，API 侧取到待执行命令并回写回执，工具返回 `applied`；
同一探针在现行镜像上复现 `No module named 'ulid'`。后端全量 8038 通过，14 项失败中 13 项是 HEAD 基线，
1 项（`test_director_auto`）是定时偶发、单跑通过；前端全量 5155 通过，另 3 项是 11-18 加 480p 档位时
漏改的断言，已修。

生产已部署 `e713c060`（叠层镜像，回滚把 `CANVAS_VERSION` 改回 `a6b2ca47`），同一探针在生产沙箱里通过。

未做：没有用真实账号在浏览器里跑一轮助手改节点（测试账号的会话已过期，重新登录要过人机验证）。

### 剩余实施清单（接续顺序）

| 下一块 | 对应研究编号 | 必须完成的接线与验收 | 所需外部输入 |
| --- | --- | --- | --- |
| 10. 应用组合与强制认证 | M01–M03、M11 | 已实现且复核修复完成；配置化 app 挂载、真实身份端口、项目/媒体隔离、旧管理接口保护 | 部署时仍需注入 HTTPS origin、持久化目录、稳定加密密钥和运营参数 |
| 11. 任务与 Agent 用户凭据 | N04、M06–M07 | 第一段授权/签名/短期 Agent 端口已实现；下一段接实际业务 runner/队列/取消重试/Agent API 和媒体路径校验 | 实际允许模型/协议/默认模型，音频和 Embedding 支持范围 |
| 12. 工作进程隔离 | M13、N09 | Linux 每用户可见挂载、撤销单租户信任回退、API/网关受控出站；真实进程无法读取其他用户文件，同时能完成必要请求 | 部署方式、容器/宿主机 namespace 与挂载权限 |
| 13. 目录/配置/导航收敛 | N07–N08、M04–M05、M08–M10 | 平台目录/参数、唯一配置入口、旧配置写 API 失效、账户与主导航贯通；旧配置不得继续影响模型调用 | 综合分组、模型目录、积分比例/精度/版本、支付渠道 |
| 14. 邮箱验证与恢复 | N02、M12 | 核实并接入发送验证码/找回/重置，按网关开关展示；注册限流与代理 IP/UA 链路 | 可用的源码读取方式、邮件服务及验证策略 |
| 15. 迁移和上线验收 | M14、N09 | 保留存量项目 ID/文件并明确归属；低额度模型/支付对账；重启/撤销/跨用户/扫码及浏览器检查 | 初始管理员的不可变网关用户 ID、低额度联调账号/额度与支付验收安排 |

以上各块可先做配置化代码与本地回归，但对外开放须同时满足 §9 的多用户隔离门槛。
不能因为第 10 块装配成功，就把仍用单租户工作进程的版本开放给外部注册用户。

## 1. 第一版确定采用的方式

**一个 AIGCDO 用户入口 + 网关统一账号 + 每用户专属 Key + 网关唯一账本 + 固定比例积分展示。**

| 项目 | 第一版约定 |
| --- | --- |
| 使用对象 | 外部注册用户 |
| 模型网关 | 固定为 `https://api.aigcdo.top`，模型调用按协议使用 `/v1` 等实际路径 |
| 注册与登录 | 用户在创作端完成，创作后端调用网关认证接口并建立本地身份映射 |
| 密码与验证 | 复用网关认证服务；创作端不保存第二份密码哈希 |
| 模型 Key | 后台自动开通、绑定并保管每用户专属 Key；普通用户不用复制或配置 |
| 模型选择 | 平台提供允许使用的模型，用户在允许范围内选择 |
| 充值与账单 | 在 AIGCDO 创作端展示和操作，由网关创建订单、处理支付回调、入账和记账 |
| 积分 | 网关余额及消费金额按固定规则转换展示，不建设第二套可独立扣减的钱包 |
| 配置入口 | 只保留 AIGCDO 统一管理入口，去掉用户侧官方／第三方／混合模式及本地网关配置 |
| 用户体验 | 注册、模型配置和充值不要求跳转到网关控制台；支付渠道正常的扫码或收银台流程除外 |
| 数据归属 | 创作端管理项目、素材、任务、文件权限及存储额度 |

建议复用现有 AIGCDO 网关管理后台作为唯一运营配置入口，统一维护分组、模型路由、
价格和应用接入策略。创作端不再提供第二套渠道编辑界面。具体管理入口位置仍可调整，
但不能让两处独立修改同一份配置。

第一版不采用“所有用户共用默认 Key，再由创作端另建积分钱包”的方案。
运营服务凭据、用户登录令牌和用户模型 Key 是三种不同凭据，不能混用。

## 2. 调研依据与当前基线

- 创作端仓库：`/root/dramaclaw`，当前实现分支为 `feat/aigcdo-gateway-integration`；
  之前的品牌/调研分支为 `feat/aigcdo-brand-user-management`。
- 网关仓库：`10.10.1.99:/root/sub2api`，审查版本为 `0b4a46e9a`。
  本轮只读查看，检查前后远端工作区均无改动。
- 公开设置：`https://api.aigcdo.top/api/v1/settings/public`。
  检查时注册开启，邮箱验证和找回密码关闭，GitHub 登录开启。
- 创作端 CE 当前是单用户：浏览器会话固定解析为 local owner，项目权限默认放行。
- CE 的使用计量是 `NoOpUsageMeter`，报价是返回 0 的 `LocalCreditQuote`。
  有积分界面不等于已经有可运行的收费后端。

下文“已有”表示调研基线中的实现；“新增／修改”是第一版改造清单，
其中已经落地的子项以顶部实现进度为准。
生产配置、支付行为及实际模型兼容性还需联调验证。
网关路径均以 `/root/sub2api` 为根目录，创作端路径以本仓库为根目录。

## 3. 已有的能力：可以复用

### 3.1 网关已有

| 编号 | 已有能力 | 源码位置 | 第一版怎么用 |
| --- | --- | --- | --- |
| G01 | 邮箱密码注册、登录、刷新、登出 | `backend/internal/server/routes/auth.go`、`internal/handler/auth_handler.go` | 创作后端调用已有认证接口，不重建密码系统 |
| G02 | 邮箱验证码、找回及重置密码 | 同上、`internal/service/auth_service.go` | 复用实现，配置邮件服务并启用所需功能 |
| G03 | 用户管理、账号状态、角色、默认余额/并发/订阅/平台额度 | `internal/server/routes/admin.go`、`internal/service/auth_service.go` | 由网关管理账号及默认权益 |
| G04 | 用户 Key 创建、查询、更新、删除 | `internal/server/routes/user.go`、`internal/handler/api_key_handler.go` | 自动开通时调用现有 Key 服务，Key 归属真实用户 |
| G05 | 分组访问与订阅权限校验 | `internal/service/api_key_service.go` | 只为用户开通有权使用的分组 |
| G06 | 综合分组按模型/端点路由 | `internal/service/composite_route_resolver.go`、`internal/server/routes/gateway.go` | 优先用一个创作专用综合分组覆盖文本、图片、视频 |
| G07 | 文本、图像生成/编辑、视频创建/状态/内容接口 | `internal/server/routes/gateway.go` | 复用现有模型入口，逐模型验证请求与响应 |
| G08 | 用户余额、冻结余额、用量和订阅查询 | `internal/handler/dto/types.go`、`internal/server/routes/user.go` | 作为创作端余额、消费记录的权威数据源 |
| G09 | 支付配置、下单、订单查询、验证、支付渠道回调 | `internal/server/routes/payment.go` | 创作端展示支付流程，网关负责订单状态和入账 |
| G10 | JWT 用户状态、TokenVersion 与可选 IP/UA 会话绑定校验 | `internal/server/middleware/jwt_auth.go`、`session_binding.go` | 复用认证有效性判断，接通创作端会话撤销 |
| G11 | Key 创建的幂等执行机制 | `internal/handler/idempotency_helper.go`、`internal/service/idempotency.go` | 复用请求重试保护；默认 24 小时 TTL 不能替代永久应用绑定 |

注意：已有注册链路**没有自动创建模型 Key**。一个 Key 绑定一个网关 `group_id`；
综合分组具备多能力路由基础，但实际目标分组权限与模型可用性尚未验证。

### 3.2 创作端已有

| 编号 | 已有能力 | 源码位置 | 第一版怎么用 |
| --- | --- | --- | --- |
| C01 | 登录表单、身份状态、Cookie 请求、路由保护框架 | `frontend/src/components/login/login-card.tsx`、`frontend/src/stores/auth-store.ts`、`frontend/src/routes/_app.tsx` | 保留页面和状态管理，接入真实网关身份 |
| C02 | `/auth/me`、`/auth/logout` 与 HttpOnly Cookie 工具 | `src/novelvideo/api/routes/auth.py`、`api/auth.py` | 扩展为真实用户会话 |
| C03 | 项目 owner 字段、项目注册表、授权端口和按用户划分的目录结构 | `ports/local/project.py`、`shared/project_dirs.py` | 保留项目 ID 和数据结构，补实际授权 |
| C04 | 统一模型出口、能力/模型映射、协议适配 | `model_gateway_settings.py`、`model_gateway_protocols.py`、`config.py` | 归并为平台内部模型路由 |
| C05 | 图片生成/编辑与视频创建/轮询/下载调用链 | `generators/nanobanana_grid.py`、`generators/video_generator.py` | 接入当前用户凭据，保留已有请求构造能力 |
| C06 | 请求上下文与模型凭据端口 | `model_gateway_runtime.py`、`ports/model_credentials.py` | 扩展到实际用户身份，不另造平行调用链 |
| C07 | 积分余额、消费流水、充值/订单和支付结果组件 | `frontend/src/components/credits/`、`frontend/src/lib/queries/credits.ts`、`payments.ts` | 复用布局、交互和查询框架，调整数据契约 |
| C08 | 报价、预留、结算、退款、用量记录端口及部分调用点 | `ports/credit_quote.py`、`ports/usage.py`、`api/routes/model_credits.py` | 用于接网关报价/状态展示；不在本地再扣一笔用户余额 |
| C09 | 认证、项目媒体权限、模型路由、账单页面相关测试 | `tests/ports/`、`tests/test_project_static_auth.py`、`frontend/src/__tests__/` | 扩展测试，不把现有单用户测试通过当作多用户已安全 |

本表 `ports/`、`generators/` 等 Python 路径均位于 `src/novelvideo/`。

## 4. 需要新增的部分

| 编号 | 新增内容 | 所在端 | 最小职责与复用关系 |
| --- | --- | --- | --- |
| N01 | 用户身份映射及持久化会话存储 | 创作后端 | 网关不可变用户 ID 关联本地用户/项目；保存会话与加密网关授权，不保存网关密码 |
| N02 | 注册、验证码、找回/重置密码的创作端页面及后端适配接口 | 创作前后端 | 注册/登录/2FA 页面和可组合后端已实现；验证码发送及密码恢复仍待核实接入 |
| N03 | 自动应用开通与稳定 Key 绑定 | 创作后端，调用网关已有接口 | 已实现绑定服务及可组合登录后开通；复用 G04/G05/G11，生产接线仍待完成 |
| N04 | 用户级网关凭据实现及授权生命周期 | 创作后端 | 根据可信请求/任务身份选择用户 Key，处理加密保存、撤销和重新授权 |
| N05 | 网关余额/用量到创作端积分响应的适配 | 创作后端 | 只读服务、账户页面及 AIGCDO app 挂载已实现；运营参数与上线验收待完成 |
| N06 | 创作端支付订单适配层 | 创作后端 | 下单/查单、防重、账户与回跳 UI 及 app 挂载已实现；真实支付验收待完成 |
| N07 | 固定积分换算规则 | 统一管理端＋创作后端 | Decimal 展示策略已实现；比例/精度/版本需显式注入，充值币种及运营配置仍待确定 |
| N08 | 应用模型目录与报价契约中缺失的字段 | 网关／平台服务 | 补足能力、默认模型、参考图/分辨率/时长参数和价格版本；只有现有接口无法提供时才新增只读接口 |
| N09 | 跨用户隔离、账号撤销、充值与扣费对账的联调覆盖 | 两端测试及部署 | 覆盖实际请求与异步任务，不仅测试页面或 mock 响应 |

### N03 的边界

现有 `/api/v1/keys` 可按用户 JWT 创建 Key；进一步核实支持 custom_key 和分页检索后，
第一版改为在创作端维护永久应用绑定，直接复用网关接口。
此前暂拟的网关 `/api/v1/integrations/aigcdo/bootstrap` **不再是第一版必需新增项**。
创作端可组合路由已提供 `/api/v1/auth/application`，生产应用还未挂载。

- 根据已认证用户及受控应用策略选择分组，不能信任浏览器任意提交的用户 ID 或高权限分组。
- 复用网关 Key 服务，记录稳定绑定，返回开通状态、Key 引用和平台模型信息。
- 对初始应用绑定建立唯一约束；重试不能重复创建 Key、账号或重复发放注册权益。
- Key 撤销与开通失败是不同状态，不能将主动撤销当故障自动补发。
- 注册成功但开通失败时保留状态；用户下次登录可查询恢复。
  无法判定创建是否发生时，需要运营核对，不会自动再发创建请求。
- 若跨系统需要专用服务认证，应只授权应用接入操作，同时校验用户授权。
  普通用户 JWT、模型 Key、管理员 `x-api-key` 不能互相替代。

首版优先每用户一把应用专用 Key；如果真实分组/协议限制要求多把，由后台自动管理，
仍不增加用户配置入口。

## 5. 需要修改的部分

| 编号 | 现有部分 | 修改要求 | 主要位置 |
| --- | --- | --- | --- |
| M01 | CE 默认 local owner、项目权限全放行 | 换成真实认证与按 owner/成员授权，补用户映射；新用户不能访问旧 local 项目 | `ports/local/auth.py`、`ports/local/project.py`、`ports/registry.py` |
| M02 | 认证是否开启与 EE 绑定、CE 免登录回退 | AIGCDO 部署强制真实登录，认证/配置不可用时拒绝受保护访问 | `api/routes/config.py`、`frontend/src/lib/runtime-config.ts`、`lib/auth-mode.ts` |
| M03 | 原登录状态及 `/auth/me`、登出处理 | 接 N01/N02，适配网关 JWT 刷新、账号状态和密码变更；保留创作端 HttpOnly Cookie | `api/routes/auth.py`、`api/auth.py`、`frontend/src/stores/auth-store.ts` |
| M04 | 官方／第三方／混合、本地 NewAPI、Agent 独立外部凭据配置 | 删除模式切换、手填地址/Key、本地初始化/渠道管理入口；统一显示平台状态与可选模型 | `frontend/src/components/settings/settings-dialog.tsx`、相关查询、类型和四种语言文案 |
| M05 | 旧配置写接口、模式选择和自动同步任务 | 移除旧第三方/本地配置的可写入口及运行时读取；迁入统一平台配置，不能只隐藏页面 | `api/routes/model_gateway.py`、`model_gateway_settings.py`、模型同步相关调用 |
| M06 | 实例级 `platform_gateway_api_key` 和全局运行时凭据 | 按可信用户/任务身份解析 N04；禁止修改共享全局 Key 来实现切换用户 | `config.py`、`model_gateway_runtime.py`、`ports/model_credentials.py` |
| M07 | 文本、Agent、图片、视频及音频/Embedding 调用 | 接入用户凭据；保留能力路由、端点、参数适配及后台任务身份；避免跨用户模型客户端缓存 | 生成器、`chat/hermes_workspace.py`、`chat/hermes_pool.py`、任务执行入口 |
| M08 | 原官方 BrainClaw 默认值、媒体模型目录和更新源 | 替换成 AIGCDO 实际模型与协议；现有第三方适配归入平台内部实现 | `official_defaults.py`、`official_media_models.json`、`official_media_catalog_remote.py`、`brainclaw_contract.py` 的使用点 |
| M09 | CE 零报价/空计量与积分查询契约 | 通过 N05/N08 展示网关报价、余额和已结算用量；明确每个预留/退款调用点如何与网关状态对应，禁止本地再次扣款 | `ports/local/usage.py`、`ports/local/credit_quote.py`、`api/routes/model_credits.py`、`frontend/src/lib/queries/credits.ts` |
| M10 | 充值、订单、支付返回与恢复页面 | 接 N06；充值选项对应网关实际支持的充值订单，支付后以网关验证/查询结果为准 | `frontend/src/lib/queries/payments.ts`、`components/credits/`、支付路由 |
| M11 | 全局设置的 CE 模式权限判断 | 改为明确的平台管理员授权；普通用户无权改渠道、价格、全局额度或读取凭据 | `api/routes/model_gateway.py`、`api/routes/task_limits.py` |
| M12 | 网关邮件、验证、应用分组及接入代理配置 | 启用需要的邮箱验证/找回流程，配置综合分组与模型权限；适配代理 IP/UA、注册登录限流 | 网关配置及相关 auth/session middleware |
| M13 | 部署与隔离 | 为互不信任用户限制工作进程可见目录；关闭多用户下的单租户全信任回退；移除实际仍在使用的本地模型网关启动依赖 | 部署脚本、Compose、Hermes sandbox/worker 配置 |
| M14 | 存量设置和项目迁移 | 保存项目 ID/路径，将旧 local 项目明确交给一个初始管理员；迁移有效模型映射后停用旧配置 | 项目注册表、平台模型目录和迁移脚本 |

除明确的 `frontend/` 路径外，本表模块路径位于 `src/novelvideo/`；
迁移脚本路径在实施时按仓库惯例确定。

“去掉本地配置”指本地**模型网关**配置，不是删除创作项目、素材、状态数据库或媒体存储能力。
旧组织管理页面有专门的迁移约束测试，不应直接恢复它们；用户管理优先复用网关已有后台。

## 6. 第一版的业务流程

### 6.1 注册与登录

1. 用户在创作端填写注册信息，按网关配置完成验证及服务协议流程。
2. 创作后端调用网关注册/登录；已有账号登录后关联，不能仅凭相同邮箱自动合并。
3. 根据返回的网关用户 ID 建立本地映射，签发创作端 Cookie 会话。
4. 自动完成应用 Key 开通；普通页面仅收到开通状态与可用模型，不收到 Key 或 refresh token。
5. 邮箱验证、找回密码和改密复用网关服务；账号停用、改密、撤销授权时同步限制创作端访问及任务。

本地存储身份映射、会话、项目关系和必要缓存，不存第二套密码或可独立扣减的余额。
文件目录使用稳定的本地身份标识，不直接随网关可修改昵称或邮箱变动。

### 6.2 充值与积分展示

1. 用户在 AIGCDO 选择充值金额，后端按当前用户授权向网关创建订单。
2. 创作端展示支付信息；回调由网关校验并处理入账。
3. 创作端查询网关订单结果，确认成功后刷新余额与积分显示。
4. 回调重复、刷新页面或重复查单均不能重复入账；不以浏览器返回参数判断已经支付。

换算原则：

- 用户余额、冻结额、消费及退款记录均以网关为准。已由冻结/结算 SQL 确认
  `balance` 是可用余额，不能再减一次 `frozen_balance`；实际支付渠道入账仍需联调。
- 若规定每单位网关余额对应 `R` 积分，则展示和报价均由同一服务端规则换算；
  `R` 的具体数值、网关计价单位和支付币种尚待确定。
- 网关 Key quota 的源码注释使用 USD，不能把人民币充值金额直接当作同单位余额。
  充值页面应使用网关实际的金额/入账换算和适用价格。
- 金额按定点数处理，展示精度及舍入规则一致；充值订单记录当时的兑换/价格版本，
  不通过事后改倍率变更已购权益。
- 本地只记录网关订单引用、展示映射或缓存，不执行独立的积分增加/扣减。

### 6.3 模型调用与结算

1. 用户选择平台允许的模型，创作端显示可获得的预计费用；动态用量必须标明估算。
2. 后端/任务进程使用当前用户的应用 Key 调用网关，由网关执行实际权限与计费检查。
3. 记录本地用户、项目、任务及网关 request/task ID，用于查询进度和关联费用。
4. 创作端从网关读取最终结算记录，换算为积分展示，不再在本地扣费。
5. 网关已受理但超时的任务先查询最终状态，不直接重发、退款或宣称免费。
6. 一个创作任务可能包含多次文本/图片/视频调用；展示可按任务汇总，
   但消费仍按网关真实记录，任务部分失败不自动意味着全部费用退还。

**余额查询只用于展示或提前提示，不是并发扣费的授权依据。**
需逐类验证网关已有的额度检查、冻结/结算和退款行为；若某条调用路径缺失关键能力，
在网关侧补齐，不在创作端复制第二本账。

## 7. 原官方方式为什么还需要适配

通过历史提交 `31c0e10b2` 确认：
原地址 `https://relayclaw.cdnfg.com/v1` 已在之前改为 `https://api.aigcdo.top/v1`。
本轮前端品牌修改没有完成后端用户或计费接入。

当前原官方分支仍有以下约束：

| 位置 | 源码事实 | 第一版处理 |
| --- | --- | --- |
| `model_gateway_settings.py:2263` | CE 官方读取实例级 `platform_gateway_api_key` | 改为当前用户的应用凭据 |
| `model_gateway_settings.py:2423`、`config.py:381` | 官方文本使用 `brainclaw`，部分任务携带 `X-BrainClaw-Profile` | 使用真实平台模型及适配；不能仅替换 URL |
| `chat/hermes_workspace.py:375` | Agent 默认继承官方模型，独立第三方模式还影响 Responses 协议 | 归入平台配置，显式保持正确协议与工具调用能力 |
| `generators/nanobanana_grid.py:4115` | 图片生成与编辑端点、参考图格式分开处理 | 保留已具备的适配并验证网关模型 |
| `generators/video_generator.py:1986` | 视频按能力获取凭据，支持 `/videos` 和 `/video/generations` | 使用选定模型的正确 schema 并验证轮询/内容访问 |
| `official_media_catalog_remote.py:25` | 默认目录更新源仍是原 DramaClaw GitHub/OSS | 接管为 AIGCDO 维护的目录源 |

在已读 Sub2API Go 源码中未发现 BrainClaw 专用处理；运行时模型别名仍可能通过配置支持，
尚未核实。推荐吸收现有第三方通用协议适配，不为保留旧模式而重建 BrainClaw 服务。
当前仓库缺少完整 EE 控制面实现，不能推断原官方 SaaS 的逐用户开通机制可直接复制。

## 8. 接口复用与待新增边界

| 用途 | 现有网关接口 | 创作端需要做的事 |
| --- | --- | --- |
| 注册/验证 | `POST /api/v1/auth/register`、`/auth/send-verify-code` | 新增同源页面/后端适配，处理验证和恢复 |
| 登录/会话 | `POST /api/v1/auth/login`、`/auth/refresh`、`/auth/logout`；`GET /api/v1/auth/me` | 适配 Cookie、身份、刷新及退出 |
| 找回/改密 | `POST /api/v1/auth/forgot-password`、`/auth/reset-password`；`PUT /api/v1/user/password` | 接入创作端账户页面，不另建密码库 |
| Key/分组 | `POST /api/v1/keys`、`GET /api/v1/groups/available` | 在 N03 内部复用；不把完整管理 API 开放给前端 |
| 余额/用量 | `GET /api/v1/user/profile`、`/usage`、`/usage/stats` | 映射为创作端积分、消费和任务费用展示 |
| 充值 | `GET /api/v1/payment/config`、`/payment/checkout-info`；`POST /api/v1/payment/orders` | 复用现有充值类型和价格，展示支付信息 |
| 查单 | `GET /api/v1/payment/orders/my`、`/payment/orders/:id`；`POST /api/v1/payment/orders/verify` | 校验用户归属，支付返回和刷新后恢复状态 |
| 应用开通 | 复用 `/api/v1/keys` 的创建、按名称搜索、按 ID 查询 | 创作端持久化绑定服务及 `/api/v1/auth/application` 已实现，生产接线待完成 |
| 平台目录/参数化报价 | 现有模型列表不保证具备全部媒体参数和统一报价字段 | **需核实后补缺**，避免重复实现网关已有定价 |

表内省略前缀的路径均以 `/api/v1` 为前缀。真实请求字段以网关路由和 handler 为准，
部分历史注释中的 `/api-keys` 或 `/users/me` 不是当前实际路由。

具体适配差异：

- 网关 envelope 为 `{code, message, data}`，创作端常用 `{ok, data, error}`，需服务端转换。
- 网关模型 Key 与登录 JWT 分离；`admin x-api-key` 不会自动变成指定用户身份。
- 启用 IP/UA 绑定后，注册、登录、刷新、查身份必须保持一致的可信代理链路；
  不能随意复用浏览器原会话到后端。
- 注册/登录有按 IP 限流，服务端代理不能让所有用户共享错误的客户端 IP。
- 普通用户无法通过改写 user_id、order_id、project_id 或 group_id 越权访问。

## 9. 实施顺序和验收

| 顺序 | 工作 | 完成标准 |
| --- | --- | --- |
| 1 | 确定平台分组/目录、注册方式、积分换算和旧项目归属 | 有明确配置与迁移输入，不猜默认模型/价格 |
| 2 | N01–N04、M01–M03：身份、会话、自动开通、项目权限 | 新老账号在创作端登录；不手填 Key；失败可恢复；跨用户访问被拒绝 |
| 3 | M06–M08：平台模型路由和用户凭据 | 文本、Agent、图片、视频完整调用及用量归属正确 |
| 4 | N05–N08、M09–M10：余额、充值、积分和订单展示 | 支付只在网关入账一次，积分转换一致，用户无需网关控制台 |
| 5 | M04–M05、M11–M14：配置收敛、迁移、部署 | 旧写接口失效，模型与项目可继续使用，多用户工作进程隔离通过 |

以上是建议顺序，不是允许未隔离的版本先对外上线。开放外部用户前必须完成：

- 未登录 API 返回 401，普通用户管理操作返回 403。
- 用户 A 无法访问 B 的项目、任务、媒体、文件、Key、余额和订单。
- 停用/改密/撤销后正确限制会话与任务；后台重试不借用别人的 Key。
- 自动开通重试不重复注册、重复发权益或无限增发 Key。
- 支付回调重复、支付返回参数伪造、服务重启不会造成重复入账。
- 并发模型请求不能仅凭过时余额绕过网关额度检查；超时/取消/部分失败能正确对账。
- 原积分预留/退款调用点不会额外扣一笔或伪造本地退款。
- 旧 local 项目保留 ID 和文件，归属明确；旧模型映射迁移后可打开历史项目。
- 真实 Linux 工作进程不能读取其他用户目录，且必要 API/模型调用可完成。

隔离约束依据：`AGENTS.md` 的 Hermes Sandbox / #346。
CE 当前单租户 unsandboxed 降级不能直接用于互不信任的外部用户部署。

## 10. 尚需确定的参数

架构选择已经确定，不再讨论是否采用共享默认 Key。实施前还需确定：

1. 创作专用综合分组、文本/图像/视频默认模型，以及现有音频/Embedding 功能的模型支持。
2. 首版注册渠道；建议沿用网关已有邮箱密码与验证码，确认邮件服务和找回密码开关。
3. 充值币种、网关入账单位、每单位对应积分数、展示精度、舍入及价格生效规则。
4. 使用的支付渠道及网关已有订单能否直接覆盖创作端充值选项。
5. 新用户默认权益、用户并发与存储限额、旧 local 项目的初始管理员归属。
6. 管理配置入口的最终位置、应用服务认证方式及低额度联调账号。

## 11. 本轮实际完成与验证范围

- 已完成前端 AIGCDO 品牌替换；之前的相关前端测试为 13 个文件、134 项通过，
  CE 生产构建通过，设计规范检查为 0 errors、15 个基线 warnings。
  这些结果仅验证品牌改动，**不能作为用户系统或计费已通过的证据**。
- 已只读检查网关公开配置和 `0b4a46e9a` 源码，并核对创作端原官方/第三方路由及 CE 计费端口。
- 第一至八块已实现认证/Key/模型/计费/支付服务及账户 UI，第九块补注册登录与开通恢复，
  第十块接入显式 AIGCDO app 组合（见顶部记录）；Agent/后台任务/完整 UI 导航/
  配置收敛/迁移部署仍待完成。
- 未创建测试用户、签发 Key、执行充值或实际模型调用；未跑远端测试、修改远端配置或部署服务。
- 没有将服务器密码、管理员令牌、模型 Key 写入本文。

### 管理 API 认证验证

使用用户提供的管理凭据，通过源码规定的 `x-api-key` 请求头向
`https://api.aigcdo.top` 发起只读请求，结果如下（不记录凭据）：

| 请求 | HTTP 状态 | 返回结果 |
| --- | --- | --- |
| `GET /api/v1/settings/public`（公开） | 200 | 站点名称 AIGCDO |
| `GET /api/v1/admin/groups/all`（无凭据，对照） | 401 | `UNAUTHORIZED` |
| `GET /api/v1/admin/groups/all`（管理凭据） | 401 | `INVALID_ADMIN_KEY` |
| `GET /api/v1/admin/users?page=1&page_size=1`（管理凭据） | 401 | `INVALID_ADMIN_KEY` |

首次结论：目标站点可达，但当时提供的 Key 未被线上实例接受。
随后用户提供更新后的凭据，复验结果见下节。两次均未创建用户、签发 Key、充值或执行模型调用。

### 更新管理凭据后的只读复验

更新后的管理凭据通过 `x-api-key` 认证，未将凭据写入文件或展示到验证结果中：

| 请求 | HTTP 状态 | 结果 |
| --- | --- | --- |
| `GET /api/v1/admin/groups/all` | 200 | `code=0`，返回 15 个分组 |
| `GET /api/v1/admin/users?page=1&page_size=1` | 200 | `code=0`，用户列表读取成功；不记录个人资料 |
| `GET /api/v1/admin/groups/41/composite-routes` | 200 | `code=0`，显式路由列表为空 |
| `GET /api/v1/admin/groups/41/composite-targets` | 200 | `code=0`，返回 10 个启用的目标分组 |

综合分组 `41`：

- 名称：`聚合分组【ALL IN ONE】`；平台 `composite`；状态 `active`。
- 标准余额分组（`subscription_type=standard`），非独占，允许图片生成。
- 目标包括 `2`（GPT-PLUS）、`15`（Gemini）、`16`（生图渠道专用）、
  `19`（Video/次）、`24`（Claude-kiro）、`27`（Grok）、
  `28`（Video/秒）、`43`（Deepseek）、`44`（Kimi）、`45`（GLM）。
- 模型白名单开关为关闭；响应中的模型数组不能直接作为“已验证支持模型”或限制名单。
- 当前没有显式模型路由，应结合综合分组的动态目标选择规则验证；
  不能把存在目标渠道等同于任何模型都能正确分派，遇到模型重名/平台歧义时需明确映射。

对第一版的影响：已经有可评估复用的综合分组，**不需要预设一定要新建分组**。
可先以 `41` 验证自动应用 Key 和三类模型调用；是否直接采用该组或另设受限的创作专用分组，
由允许模型、计费和权限边界决定。此次仅确认管理读取与配置状态，
未验证写权限、普通用户实际权益、Key 签发、支付入账或真实模型可用性。

### 普通用户 JWT 链路实测

使用用户提供的既有账号登录，仅进行身份与配置查询及测试会话刷新/退出；
全程未使用管理 Key，不在文档中记录邮箱、密码、令牌、Key 或个人余额。

| 操作 | HTTP 状态 | 实际结果 |
| --- | --- | --- |
| `POST /api/v1/auth/login` | 200 | 返回 access token 和 refresh token；账号角色为普通 `user`，access token 有效期字段为 86400 秒 |
| `GET /api/v1/auth/me` | 200 | 身份 ID 与登录结果一致，账号 active，可读取本人余额和冻结额 |
| `GET /api/v1/user/profile` | 200 | 本人资料及余额读取成功 |
| `GET /api/v1/groups/available` | 200 | 可用分组包含 `41`（综合分组）及其他公开分组 |
| `GET /api/v1/keys?page=1&page_size=1` | 200 | 本人 Key 列表读取成功；验证输出省略密钥值 |
| `POST /api/v1/auth/refresh` | 200 | 成功返回新 access/refresh token |
| 新 access token 调用 `/api/v1/auth/me` | 200 | 身份仍与登录用户一致 |
| `POST /api/v1/auth/logout`（本次测试刷新令牌） | 502 | 未收到成功退出响应，无法确认本次测试会话已撤销 |

结论：**普通用户不需要管理 Key，即可完成登录、JWT 查询本人信息/余额/分组/Key 和刷新。**
不需要为这些操作再开发一种“用户管理 Key”。
应用自动开通及稳定绑定仍需补齐；此次没有创建 Key、注册新用户、发起充值或模型调用。
该既有账号可访问分组 41，不代表新注册用户或受限账号必然有相同权限。

退出接口 502 是待核查项：不能将“已调用 logout”视为会话已撤销，
也尚未验证退出后 access token 的失效语义。上线前需检查网关退出处理及代理错误，
补充登出、改密、停用和撤销的端到端验证。

### 创作端新用户自动映射的验证边界

再次检查当前创作端源码：

- `api/routes/auth.py` 仍只实现 `/auth/me` 和 `/auth/logout`。
- `ports/local/auth.py` 仍返回固定 local owner；
  `ports/local/project.py` 的用户解析和项目权限仍为单用户实现。
- 此项核查时尚无网关注册/登录客户端；目前已新增 `aigcdo_gateway.py`、
  `aigcdo_sessions.py`、项目授权端口及可组合 Cookie 认证路由，
  已通过临时 ASGI 应用的注册/登录/持久化映射及自动 Key 开通测试，但尚未切换生产 app。

因此，目前验证到的是“无需打开网关网页即可通过 API 登录并查询”，
**不是“当前创作端已能注册新用户并自动关联网关”**。
新账号注册需使用用户确认的专用测试邮箱进行真实接口验证，
持久化身份映射、Cookie 路由和自动 Key 开通已经过本地集成测试；
生产应用组合、模型调用端的凭据解析仍需接通 N01–N04 才能完成线上端到端验收。

映射对象是用户身份：一个创作端用户对应一个网关用户，可拥有多个创作项目。
创建新的创作项目不应重复注册网关账号；项目和素材保留在创作端，
调用费用通过该用户的 Key 归属网关账户，并在创作端关联任务/项目。
