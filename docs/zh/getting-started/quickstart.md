<!-- lang-switch -->
[English](../../en/getting-started/quickstart.md) · **简体中文**

# 快速开始

> 本地跑起 DramaClaw,产出第一个结果。

DramaClaw 是社区版(CE),单机运行、无需 PostgreSQL / Redis。`docker compose` 启动 `api` 和 `web`;模型默认走 **DramaClaw 官方网关(RelayClaw)**,填一个 DC key 即用。自定义网关在设置页配置外部服务。

## 前置

- Docker(Desktop 或 Engine),支持 `docker compose`。
- 一个 **DC key** —— 到 <https://api.aigcdo.top> 注册 / 购买；也可以在设置中配置外部兼容网关。

## 步骤

```bash
# 1. 取得代码
git clone https://github.com/dramaclaw/dramaclaw.git
cd dramaclaw

# 2. 准备配置
cp .env.example .env
#    打开 .env,至少把 PROMPT_EXPORT_PASSWORD 改成非默认值。
#    模型渠道和 key 在下一步通过网页配置，不写入 .env。

# 3. 启动 —— 起 api / web
docker compose up -d --build   # 从源码构建并启动 api、web
# 已发布镜像：docker compose -f docker-compose.release.yml up -d

# 4. 确认已起
docker compose ps   # api、web 均应 running
```

## 填入 DC key(必做一次)

1. 浏览器打开 **`http://localhost:8080`** —— 这就是 DramaClaw 的界面。
2. 进入设置 → **模型配置 → 官方渠道**。网关地址已预填 `https://api.aigcdo.top/v1`。
3. **粘贴你的 DC key**,点「保存并启用」。立即可用,**无需映射任何模型**(RelayClaw 后台已配齐)。

> CE 默认免登录、单本地用户(`ST_EDITION=ce`,compose 已强制)。REST API 在 `http://localhost:8780`(浏览器只与 `web` 通信,它再反代到 `api`)。

## 想使用自己的模型渠道？

在「设置 → 模型配置 → 自定义」中添加可从 `api` 容器访问的 OpenAI 兼容或 Gemini 兼容网关组，填写协议、基础 URL、API key、能力和上游模型映射。详见[配置模型供应商](configuring-models.md)。

## 下一步

- 完整部署/升级/备份:[自托管手册](../guides/self-hosting.md)
- 接入自己的模型:[配置模型供应商](configuring-models.md)
