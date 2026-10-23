<!-- lang-switch -->
[English](../../en/guides/self-hosting.md) · **简体中文**

# Docker 自托管手册

CE 的 Compose 只启动两个服务：`api` 和 `web`。无需 PostgreSQL、Redis 或 Celery，任务在进程内执行。模型默认使用官方 RelayClaw，也可以在应用中配置可访问的外部 OpenAI 兼容或 Gemini 兼容网关。

## 启动

```bash
git clone https://github.com/dramaclaw/dramaclaw.git
cd dramaclaw
cp .env.example .env
docker compose up -d --build
```

使用已发布镜像：`docker compose -f docker-compose.release.yml up -d`。源码和镜像 Compose 都只有 `api`、`web`。

## 配置网关

打开 `http://localhost:8080` → 设置 → 模型配置：

- **官方**：粘贴 DC key，无需模型映射。
- **自定义**：添加一个或多个外部网关组，选择 OpenAI 兼容或 Gemini 兼容协议，填写从 `api` 容器可访问的基础 URL、该组 API key、能力和上游模型映射。
- **混合**：同时配置官方 key 和至少一个外部网关组；匹配的模型使用对应网关，其余请求使用官方网关。

网关组和密钥保存于 CE 设置数据库，不由 Compose 管理。不要把官方 key 发给第三方地址，也不要把第三方地址设置为 `localhost`（除非网关就在同一容器内）。

## 数据与升级

项目数据库、设置和生成媒体位于 `ce-data:/data`。停止或重建容器不会删除它；只有显式 `docker compose down -v` 才会删除卷。

旧版本留下的 `newapi-data` 卷不会被当前 Compose 声明、挂载、删除或清理。它只保留给人工回滚或恢复，不属于当前两服务部署路径。

```bash
git pull
docker compose up -d --build
```

升级不会删除旧设置键，也不会把旧 NewAPI 管理数据自动迁移到某个内置服务。需要时请在设置中手动创建等价的外部网关组。

## 排查

- 容器启动失败：运行 `docker compose logs api` 和 `docker compose config --quiet`。
- 模型调用失败：检查外部 URL、协议、API key、能力和上游模型映射。
- 外部网关不可达：确认该地址能从 `api` 容器访问，且不是仅绑定宿主机回环地址。
