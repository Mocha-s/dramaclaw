<!-- lang-switch -->
**English** · [简体中文](../../zh/getting-started/configuring-models.md)

# Configuring Models

DramaClaw CE routes text, vision, embedding, image, video, and audio through the official gateway or user-configured third-party groups. Custom groups support OpenAI-compatible and Gemini-compatible protocols. Model settings are stored in local CE `settings.db`; secrets are returned only as masked previews.

After startup, open `http://localhost:8080` and go to **Settings → Models & Channels**. The “Active” badge at the top shows the actual runtime mode, not merely the tab currently being viewed.

## Choose a gateway mode

| Mode | Use case | What you configure |
|---|---|---|
| Official | Use the models provided by RelayClaw | DC Key only |
| Custom | Route models through configured third-party groups | Protocol, Base URL, group API key, capabilities, and logical-model mappings |
| Hybrid | Keep official models while routing matching models through third-party groups | Official DC Key plus one or more configured third-party groups |
| Sub2API | Route capabilities through separately configured OpenAI/Gemini-compatible account groups | Base URL, capability, model mapping, and API Key per group |

Enable the intended mode after configuring it. New jobs read the latest mode, key, and mappings. Jobs already running do not switch gateways midway.

### Sub2API image and video request formats

Sub2API model mappings expose per-model protocol selectors. Image edits default to
the verified `images: [{"image_url": "..."}]` JSON shape; choose `input_reference`
or multipart `image` only when that upstream model's documentation requires it.
NewAPI/custom/official routes keep DramaClaw's existing `image: [url]` JSON
format unless the deployment explicitly overrides it.

Video models default to the modern `POST /videos`, `GET /videos/{id}`, and
`GET /videos/{id}/content` lifecycle. Select the legacy
`/video/generations` endpoint for gateways that require it. Modern requests send
an `Idempotency-Key`; if the completed task has no direct result URL, DramaClaw
downloads the authenticated content endpoint. The server does not retry a
generation with another format after an upstream error, avoiding duplicate
billable jobs.

For a Sub2API group whose protocol is **Gemini**, image models use Gemini's
native `POST /v1beta/models/{model}:generateContent` contract instead of the
OpenAI-compatible image endpoint. Prompts and references are sent in
`contents[].parts[]`; local reference images become `inlineData`, and
`generationConfig.imageConfig` carries `imageSize` and `aspectRatio`. Gemini
video models are not switched to this image contract.

Model capabilities are enforced by the catalog. For example,
`sd17-seedance-2.5-2` is limited to 30 reference images, 10–30 seconds, and 720p.

## Agent model

The Xia Director Agent can either follow the active gateway mode or use an independent third-party endpoint. Under **Agent model**, select **Third party** and provide an OpenAI-compatible Base URL, API Key, and model name. The endpoint must support the OpenAI Responses API and tool calls. This setting affects the Agent only; image, video, audio, embedding, and other feature-model routes continue to use the selected gateway mode.

Secrets remain in the local CE settings database and are returned to the browser only as a masked preview. Changing the third-party endpoint requires entering the API Key again, which prevents a saved credential from being sent to a different host accidentally. Select **Follow current channel** to restore the existing Official, Custom, or Hybrid routing behavior.

## Official mode

Official mode is the shortest setup path:

1. Open **Official**.
2. Enter your RelayClaw DC Key.
3. Click **Save & Enable**.

DramaClaw manages the official gateway URL. RelayClaw already provides the `DC-*-LLM`, `DC-cognee-embedding`, and official media model mappings, so CE-side upstream mappings are unnecessary.

The official image/video list and its resolutions, aspect ratios, durations, and reference-media capabilities come from the bundled `src/novelvideo/official_media_models.json`.

### Update the official media model catalog

Official and Local + Official Hybrid modes show the current catalog version, model count, and source:

- Click **Check for Updates** to fetch the latest catalog from DramaClaw's official publishing URL and apply it immediately.
- **Automatically update the official model catalog** is off by default. When enabled, the backend checks every five minutes by default and also checks immediately when the corresponding settings panel opens.
- Downloaded catalogs are stored locally at `state/local/official_media_models.json` and remain active after restart.
- DramaClaw rejects a remote catalog older than the active version. After an application upgrade, a newer bundled catalog takes precedence over an older local cache.
- After a successful update, an open XiaHua browser observes the catalog status every minute while automatic updates are enabled and refreshes its image and video model lists when the content SHA256 changes.
- The status API reports the active content SHA256, publishing Git revision, publication time, remote URL, and latest update error so each instance can be audited.

Official catalog updates do not change provider channels, model mappings, or capabilities maintained in Custom mode.

The official catalog defaults to the `dramaclaw-dl` bucket in Chengdu: `https://dramaclaw-dl.oss-cn-chengdu.aliyuncs.com/official-media-catalog/manifest.json`. The manifest points to a SHA256-addressed catalog snapshot that is never overwritten. The backend validates the manifest, catalog version, and content SHA256, and uses ETag revalidation. Override the default with `OFFICIAL_MEDIA_CATALOG_MANIFEST_URL`; `OFFICIAL_MEDIA_CATALOG_URL` remains as a legacy direct-JSON source. Set `OFFICIAL_MEDIA_CATALOG_POLL_SECONDS` to change the polling interval; the minimum is 60 seconds.

The repository's `publish-official-media-catalog` workflow uploads `catalogs/<sha256>.json` with a long-lived immutable cache policy, then publishes `manifest.json` with a 60-second cache policy. Configure the following as repository secrets or in the GitHub `official-media-catalog` environment:

- Variables are optional: the defaults are `oss-cn-chengdu.aliyuncs.com`, `dramaclaw-dl`, and `official-media-catalog`; override them with `OFFICIAL_CATALOG_OSS_ENDPOINT`, `OFFICIAL_CATALOG_OSS_BUCKET`, and `OFFICIAL_CATALOG_OSS_PREFIX`.
- Secrets: `OFFICIAL_CATALOG_OSS_ACCESS_KEY_ID` and `OFFICIAL_CATALOG_OSS_ACCESS_KEY_SECRET` take precedence; otherwise the workflow reuses organization-level `OSS_RELAY_AK` and `OSS_RELAY_SK`.

Keep `dramaclaw-dl` private and grant anonymous `GetObject` only for the `official-media-catalog/*` prefix. The CI identity only needs write access to that prefix. Git pull requests remain the source of truth; enabling OSS versioning is recommended for infrastructure recovery.

To obtain a DC Key, visit <https://api.aigcdo.top>.

## Custom mode

Custom mode uses one or more user-configured third-party gateway groups. Start the CE stack with `docker compose up -d`; it starts only `api` and `web`.

### Configure a third-party group

In **Custom**, add a group with a reachable Base URL, its own API key, and an explicit protocol: **OpenAI-compatible** or **Gemini-compatible**. Select capabilities such as text, vision, embedding, image, video, or audio, then map each DramaClaw logical model ID to the upstream model ID. Saved keys remain masked in the browser and are stored in the CE settings database.

OpenAI-compatible groups may use `/v1/models` for discovery when the endpoint supports it. Gemini-compatible image requests use Gemini's native `generateContent` contract. Manual model entry remains available when discovery is unavailable. The app owns the logical-model mapping; the external gateway owns its own upstream accounts and provider configuration.

NewAPI-specific admin CRUD, provider-channel catalogs, channel-type synchronization, and root-account initialization are not portable and are not performed by CE. Recreate those upstream accounts directly in the external gateway you selected. Existing legacy settings and any old `newapi-data` volume are retained for migration or rollback, not used as a bundled service.

### Feature and media models

Keep stable logical names such as `DC-character-builder-LLM`, `DC-scene-builder-LLM`, and `DC-freezone-vision-LLM`, and map them to suitable upstream models. Text features need text models; vision features need multimodal models; embeddings need a compatible embedding model and dimension; media models need the corresponding image, video, or audio capability. Save mappings after editing. A provider error is not retried with another credential.

ComfyUI remains useful as an independent external provider. Configure its reachable service URL and workflows in the selected third-party gateway, then add the matching video group and model mapping in DramaClaw. A container cannot reach a host service through its own `127.0.0.1`; use a host or LAN address reachable from `api`.

## Hybrid mode

Hybrid keeps RelayClaw for official models while selecting configured third-party groups for matching capabilities or model IDs. Save the official DC key, add at least one valid external group, map the intended logical models, and enable Hybrid. An exact or most-specific unambiguous mapping wins; unmatched requests use the official gateway. Runtime failures do not automatically retry with another credential.

## Reference media storage

Image editing, video first/last frames, reference images, and identity images require upstream services to read local files. Go to **Settings → Media Storage** and configure a publicly reachable temporary media relay.

### Aliyun OSS

Provide a Bucket and an AccessKey with read/write permission for that Bucket. A narrowly scoped RAM sub-account is recommended.

| UI field | Environment variable | Example or notes |
|---|---|---|
| Endpoint | `OSS_RELAY_ENDPOINT` | `oss-cn-chengdu.aliyuncs.com`, without `https://` |
| Bucket | `OSS_RELAY_BUCKET` | Temporary-media Bucket |
| AccessKey ID | `OSS_RELAY_AK` | Bucket-scoped AK |
| AccessKey Secret | `OSS_RELAY_SK` | Matching SK |
| TTL | `MEDIA_RELAY_TTL_SECONDS` | Default: 1800 seconds |

### Self-hosted MinIO

In **Settings → Media Storage**, select MinIO and provide the S3 endpoint reachable
by the API container, bucket and credentials, plus the public HTTPS endpoint
reachable by the upstream model. The internal and public endpoints may use the
same reverse proxy or separate internal/public addresses. Credentials stay
server-side and are never returned to the browser.

The Bucket does not need public-read access. DramaClaw generates temporary signed URLs for upstream access.

### Cloudinary

Enter Cloud name, API Key, API Secret, and an optional folder. Find them under **Product environment settings → API Keys** in Cloudinary. Saved database settings take precedence over environment variables, and full secrets are never returned to the frontend.

## Troubleshooting

| Symptom | What to check |
|---|---|
| No “Saved” badge after saving a key | The value may still be a browser draft. Save/update that channel or reapply the complete profile, and ensure the running image contains the latest code. |
| Adding a media model says its provider key is missing | The provider channel was not persisted to NewAPI. Save/update the channel before saving media models. |
| NewAPI reports `No available channel for model ...` | Check the logical mapping, channel status, upstream model name, and group. |
| Structured steps fail with `Exceeded maximum output retries` behind a Codex-backed relay (Codex2API etc.) | The relay may drop `tool_calls` on `/v1/chat/completions`. Check the selected external gateway's compatibility options and enable its Responses compatibility mode if available. See the [troubleshooting guide](../guides/troubleshooting.md#model--gateway). |
| A new model is absent from XiaHua | Verify it is enabled, has the correct media type, the complete configuration was saved, and the page was refreshed. |
| Controls do not match model capabilities | Check the media model `config`, especially resolutions, ratios, modes, and reference limits. |
| Knowledge-graph embedding fails | Check the key, upstream model, dimensions, and batch size. HTTP 429 means upstream rate limiting. |
| Reference media cannot be read | Verify media storage and that the upstream service can reach the temporary public URL. |
| Hybrid local video fails without official fallback | Expected: Hybrid mode has no automatic failure fallback. |
| ComfyUI cannot connect to `127.0.0.1:8188` | `127.0.0.1` means the environment running the DramaClaw backend. For containers or remote deployments, use a host or LAN address reachable from that backend. |
| A MiniMax H3 workflow reports missing nodes or models | Install the custom nodes and model files referenced by the recommended workflow, then adjust the workflow for local filenames and versions. |

## Related files

- `src/novelvideo/official_media_models.json`: CE official media models and capabilities.
- `.env.example`: environment variable reference.
- `docker-compose.yml` (source build) / `docker-compose.release.yml` (images): two-service CE deployment (`api` + `web`); external gateway groups are configured in Settings.
- [Self-Hosting Handbook](../guides/self-hosting.md)
- [Environment Variable Reference](../reference/environment-variables.md)
