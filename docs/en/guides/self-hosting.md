<!-- lang-switch -->
**English** · [简体中文](../../zh/guides/self-hosting.md)

# Self-Hosting Handbook (Docker)

DramaClaw CE runs as two Compose services: `api` and `web`. It needs no PostgreSQL,
Redis, or Celery; tasks run inline. Models use the official RelayClaw gateway by default,
or a reachable external OpenAI-compatible or Gemini-compatible gateway configured in the
app.

## 1. Prerequisites and setup

- Docker with Compose >= 2.24.
- At least 2 vCPU / 4 GB recommended.
- A DC key, or an external OpenAI-compatible/Gemini-compatible gateway and its API key.

```bash
git clone https://github.com/dramaclaw/dramaclaw.git
cd dramaclaw
cp .env.example .env
docker compose up -d --build
```

For published images, use `docker compose -f docker-compose.release.yml up -d`.
Both Compose files contain only `api` and `web`; source Compose builds those two images.

## 2. Configure a model gateway

Open `http://localhost:8080` → Settings → Model Configuration.

- **Official:** paste the DC key and save. No model mapping is required.
- **Custom:** add one or more reachable external gateway groups. Select OpenAI-compatible
  or Gemini-compatible protocol, enter that group's base URL and API key, choose its
  capabilities, and map DramaClaw logical models to upstream model IDs.
- **Hybrid:** configure the official key and at least one external group. Matching models
  use the selected group; other requests use the official gateway.

Gateway groups and secrets are stored in the CE settings database, not in Compose.
Never point a third-party group at the official endpoint or reuse the official key for it.

## 3. Start, stop, and data

```bash
docker compose ps
docker compose logs -f api
docker compose down                 # stops services; keeps ce-data
```

Project databases, settings, and generated media are in the named `ce-data` volume at
`/data`. Back it up before moving hosts or upgrading:

```bash
docker run --rm -v dramaclaw-ce_ce-data:/data -v "$PWD":/backup alpine \
  tar czf /backup/ce-data-backup.tar.gz -C /data .
```

An existing `newapi-data` Docker volume is **not** declared or mounted by current CE
Compose. Compose changes do not delete or prune it. Keep it only for manual rollback or
recovery of legacy data; it is outside the normal two-service deployment path.

## 4. Upgrades

```bash
git pull
docker compose up -d --build
```

For release images, update `DRAMACLAW_VERSION`, then run `pull` and `up` with the release
Compose file. The `ce-data` volume and legacy settings keys remain in place. Existing
NewAPI data is not migrated into a bundled service; configure equivalent external groups
manually when needed. Do not remove or prune `newapi-data` as part of an application
upgrade.

## Troubleshooting

| Symptom | What to check |
|---|---|
| Container will not start | `docker compose logs api` and `docker compose config --quiet` |
| Port 8780 is busy | Change the host-side API port in Compose or use another project name |
| Model call errors | Confirm the selected external base URL, API key, protocol, capabilities, and upstream model mapping |
| External gateway unreachable | Ensure the URL is reachable from the `api` container and is not a loopback-only host address |

See [Quickstart](../getting-started/quickstart.md) and [Configuring Model Providers](../getting-started/configuring-models.md).
