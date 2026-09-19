# FB 迁移调用清单

## 盘点结论

当前项目尚未完成 FB 与 SaaS 的物理边界隔离，存在两条调用链：

1. 推荐链路：`api/*` → `services/meta/*` → Meta Graph API / Facebook SDK。
2. 兼容旧链路：`services/ads_manager.py` → `services/fb_client.py` 全局单例 → Meta Graph API / Facebook SDK。

因此后续不能只迁移 `services/meta`，必须同时处理 `services/fb_client.py` 和投放任务。

## 调用分类

| 业务 | 当前入口 | 当前 FB 边界 | 迁移目标 | 优先级 |
|---|---|---|---|---|
| OAuth 授权 | `api/meta_auth.py` | `services/meta/oauth_service.py` | 海外 Connector | P0 |
| 凭据管理/轮换 | `api/credentials.py` | `services/credential_service.py`、`services/meta` | Token 只留海外 | P0 |
| BM 管理 | `api/meta_accounts.py` | `BusinessService`、`MetaClient` | 海外 Connector | P0 |
| BM 归属校验 | `api/accounts.py` | `MetaAdsService`、`MetaClient` | 海外 Connector | P0 |
| 广告账户同步 | `services/meta/sync_service.py`、`tasks/meta_sync_tasks.py` | `MetaClient` | 海外 Worker | P1 |
| Facebook Page 同步 | `api/meta_pages.py`、`services/meta/page_service.py` | `MetaClient` | 海外 Connector | P1 |
| 图片/视频上传 | `api/media.py`、`tasks/media_tasks.py` | `MetaAdsService`、`MetaClient` | 海外 Worker | P1 |
| Campaign/AdSet/Ad 投放 | `services/ads_manager.py`、`tasks/campaign_tasks.py` | `services/fb_client.py` 和 `services/meta` | 海外 Worker | P1 |
| Insights 报表 | `services/meta/service.py`、报告任务 | `MetaClient` / Graph API | 海外 Worker | P1 |
| 任务调度 | `celery_app.py`、`tasks/*` | 国内 API/Worker 共用 | 国内编排，海外执行 | P1 |

## 配置盘点

### 必须只存在于海外 Connector

```text
FB_APP_ID
FB_APP_SECRET
FB_LOGIN_CONFIG_ID
FB_ACCESS_TOKEN（兼容旧配置，最终废弃）
FB_ACCOUNT_ID（兼容旧配置，最终废弃）
FB_API_VERSION
FB_OAUTH_REDIRECT_URI
FB_OAUTH_SCOPES
FB_API_TIMEOUT
FB_VIDEO_UPLOAD_TIMEOUT
FB_API_RETRY_COUNT
```

### 国内 SaaS 需要新增

```text
APP_ROLE=saas
FB_CONNECTOR_BASE_URL
FB_CONNECTOR_TIMEOUT
FB_CONNECTOR_SIGNING_KEY
CONNECTOR_SERVICE_TOKEN
SAAS_CALLBACK_BASE_URL
FB_ACCESS_MODE=direct|dual|connector
```

### 海外 Connector 需要新增

```text
APP_ROLE=fb_connector
SAAS_CALLBACK_BASE_URL
SAAS_INTERNAL_SIGNING_KEY
CONNECTOR_SERVICE_TOKEN
```

## 部署耦合

- `deploy/docker-compose.yml` 当前让 `api`、`celery-worker`、`celery-beat` 共用项目镜像和 `.env`。
- `api`、Worker、Beat 需要拆为国内 SaaS 组和海外 Connector 组。
- 两边不共享数据库；国内保存业务和同步结果，海外保存凭据及 Meta 执行状态。
- 当前 `deploy/.env.example` 同时包含 SaaS 和 FB Secret，T02 必须拆开。

## 风险清单

1. `services/fb_client.py` 使用 `FacebookAdsApi.init()` 全局初始化，迁移前不能继续放在国内 Worker。
2. OAuth Callback 地址必须从国内地址改为海外 Connector 地址，并同步修改 Meta Developer 后台。
3. 素材上传属于长耗时任务，必须异步化，不能通过国内 API 同步代理大文件。
4. 投放写操作必须设计幂等键，避免 Connector 重试产生重复 Campaign 或广告。
5. 国内报表不能依赖实时访问 Meta，应查询 Connector 回传后的本地数据。

## T01 验收记录

- [x] 已搜索 `api`、`services`、`tasks`、`config`、`deploy` 中的 FB 调用。
- [x] 已识别 `services/meta` 与 `services/fb_client.py` 两套边界。
- [x] 已识别 OAuth、凭据、同步、素材、投放、Insights 六类迁移对象。
- [x] 已记录生产配置和 Docker Compose 的耦合点。
- [ ] T02 配置分层完成后补充实际环境变量检查结果。

## T03 执行记录

- [x] 已新增 `services/request_signer.py`。
- [x] 签名覆盖 HTTP 方法、路径、时间戳、请求体摘要和幂等键。
- [x] 已新增签名往返、请求体篡改、时间戳过期测试。
- [x] 已通过模块语法检查和签名往返验证。
- [ ] 尚未接入 Connector HTTP 中间件，待 T04 Connector 外壳建立后接入。

## T04 执行记录

- [x] 已新增 `fb_connector/main.py` 独立 FastAPI 入口。
- [x] 已新增 `/internal/health` 和 `/internal/ready`。
- [x] 除健康检查外的 `/internal/*` 路由已接入 SaaS HMAC 签名校验。
- [x] 已新增 `fb_connector/Dockerfile` 和 `deploy/docker-compose.connector.yml`。
- [x] 健康检查不会返回 App Secret、Access Token 或签名密钥。
- [ ] 尚未迁移具体 Meta API 路由，留待 T06-T10。

## T05 执行记录

- [x] 已新增 `services/fb_connector_client.py`。
- [x] 已统一处理服务签名、Request ID、幂等键、JSON 请求和错误映射。
- [x] 已提供 OAuth、BM、账户、Page、素材、投放和 Insights 客户端方法。
- [x] 已新增 Client 的 Mock 请求测试。
- [x] 已通过 Python 语法检查。
- [ ] 待 T04 Connector 增加对应业务路由后进行联调。

## T06 执行记录

- [x] 已新增海外 OAuth 路由模块 `fb_connector/api/oauth.py`。
- [x] 已实现授权地址生成，`state` 由 SaaS 生成并透传。
- [x] 已定义 `CredentialVault` 接口，约束海外只返回 opaque `credential_id`。
- [x] 在凭据仓储未接入前，OAuth Token 交换接口明确返回 503，不会把 Token 返回给国内或浏览器。
- [x] 已新增海外 `connector_credentials` 模型和数据库 Session 工厂。
- [x] 已使用由 `SECRET_KEY` 派生的 Fernet 密钥加密保存 Token。
- [x] OAuth `/exchange` 在海外完成 Token 交换，仅返回 opaque `credential_id`。
- [ ] 待补充 SaaS 回调、凭据状态同步和生产数据库迁移脚本。
- [x] 已新增 `0017_connector_credentials` 数据库迁移脚本。
- [x] 已新增 SaaS `/api/v1/internal/fb-connector/credential-status` 签名回调入口。
- [x] 回调仅接收 credential_id、状态、scope 和过期时间，不接收 Token。
- [ ] 待 T07 将回调状态映射到国内资产记录，并补充幂等持久化。

## T07 执行记录

- [x] 已新增海外 BM 校验接口 `/internal/meta/business/verify`。
- [x] 已新增广告账户同步接口 `/internal/meta/accounts/sync`。
- [x] 已新增 Page 同步接口 `/internal/meta/pages/sync`。
- [x] 三类接口均只接收 `credential_id`，Token 只在海外 Connector 内解密。
- [ ] 待国内 `api/meta_accounts.py`、`api/accounts.py`、`api/meta_pages.py` 逐个切换到 `FBConnectorClient`。
- [x] `api/meta_accounts.py` 的广告账户归属校验已支持 `FB_ACCESS_MODE=connector`。
- [ ] `api/accounts.py` 和 Page 异步任务仍待切换。
- [x] `api/accounts.py` 的账户创建前 BM 归属校验已支持 Connector 模式。
- [x] Page 查询字段已排除 Page Access Token，禁止回传到 SaaS。

## T08 执行记录

- [x] 已新增海外素材上传任务接口 `/internal/meta/media/upload`。
- [x] 上传接口只接收 HTTP(S) `source_url`、素材类型、账户 ID 和幂等键。
- [x] 国内 Client 已要求素材上传必须提供幂等键。
- [x] Connector Worker 已实现下载、Meta 上传、状态持久化和本地文件清理。
- [x] 已新增 Connector Celery Worker，支持流式下载素材并调用 Meta 图片/视频上传。
- [x] 上传任务使用 `credential_id` 获取海外密文凭据，不向 SaaS 返回 Token。
- [x] 国内 Client 上传请求已增加 `credential_id`。
- [ ] 待增加 Connector 任务表、幂等持久化和 SaaS 状态回调。
- [x] 已增加 `connector_media_tasks` 任务表和幂等键唯一约束。
- [x] 已增加上传任务状态查询接口 `/internal/meta/media/upload/{task_id}`。
- [x] Worker 已持久化 QUEUED/UPLOADING/SUCCESS/FAILED 状态。
- [x] 已接入 `/api/v1/internal/fb-connector/media-status` 签名回调；回调直接更新 `MetaAssetBinding`，轮询保留为兜底。
- [x] Connector 回调已写入 `connector_callback_events` outbox，失败按指数退避重试，Beat 每 30 秒恢复投递。

## T09 执行记录

- [x] 已新增海外投放入口 `/internal/meta/campaigns/create`。
- [x] 投放请求要求 `credential_id`、广告账户、业务任务 ID 和幂等键。
- [x] 国内 Client 已强制投放请求提供幂等键。
- [x] Connector Worker 已实现 Campaign/AdSet/Creative/Ad 分步创建和失败留痕。
- [x] 已新增 Connector 投放 Worker，按 Campaign → AdSet → Creative → Ad 顺序执行。
- [x] 投放失败会保留已创建对象 ID 到异常信息，避免无审计的自动误删。
- [x] 已增加 `connector_delivery_tasks` 任务状态表、幂等持久化和状态查询。
- [x] 已增加 `connector_delivery_tasks` 任务状态表和幂等键约束。
- [x] 已增加投放状态查询 `/internal/meta/campaigns/create/{connector_task_id}`。
- [x] Worker 已持久化 CAMPAIGN/ADSET/AD/DONE 执行阶段。
- [x] 已接入 `/api/v1/internal/fb-connector/delivery-status` 签名回调；终态回调触发国内投放子项收敛，轮询保留为兜底。
- [x] Connector 回调事件使用稳定 `event_id` 和原始 body 签名，重复投递不会重复创建 Meta 对象。

## T10 执行记录

- [x] 已新增海外 Insights 接口 `/internal/meta/reports/insights`。
- [x] 支持账户、Campaign、AdSet、Ad 四种层级。
- [x] 支持 1-90 天查询范围。
- [x] Token 只在 Connector 内解密和调用 Meta API。
- [ ] 待增加海外 Insights 定时 Worker、结果回传和国内报表数据落库。
- [x] 已增加海外 Insights Worker。
- [x] Worker 通过 HMAC 回调 `/api/v1/internal/fb-connector/insights`。
- [x] 回调不包含 Access Token。
- [ ] 国内回调目前只确认接收，待接入报表持久化和幂等去重。
- [x] 已增加国内 `connector_insights_snapshots` 幂等快照表。
- [x] Insights 回调按 `request_id` 去重并保存原始 JSON 数据。
- [x] 已配置 Connector Beat 调度入口示例。
- [ ] 生产 Beat 需要由账户配置生成具体任务参数，不能直接使用空参数示例。

## T11 执行记录

- [x] 已新增 `FB拆分灰度与故障演练.md`。
- [x] 已定义 10% → 30% → 100% 灰度顺序。
- [x] 已定义 Connector 宕机、Meta 限流、重复回调、Token 过期演练。
- [x] 已定义 `FB_ACCESS_MODE=direct` 回滚方式。
- [ ] 待测试环境执行真实压测和故障演练。

## T12 执行记录

- [x] 已新增 `scripts/check_fb_split_cutover.ps1` 只读切割检查脚本。
- [x] 已新增 `FB最终切割检查清单.md`。
- [x] 检查国内配置必须使用 `APP_ROLE=saas` 和 `FB_ACCESS_MODE=connector`。
- [x] 检查国内配置不得包含 FB Secret、Access Token 和 OAuth 回调配置。
- [ ] 尚未执行最终切割；真实测试环境联调和故障演练通过后再关闭国内直连代码。

## 审查修复记录

- [x] 已修复 Connector Alembic 版本冲突，迁移改为 `0021-0023`，接在 `0020_ad_account_asset_type` 后。
- [ ] 仍需将 Connector 专用表迁移拆到独立海外迁移目录，避免与 SaaS 数据库共用迁移链。
- [x] 已删除误放在 SaaS 迁移目录中的 Connector 迁移；Connector 仅使用 `fb_connector/migrations/versions/0001_connector_initial.py`。
- [x] 已新增 `fb_connector/alembic.ini` 和独立迁移环境。
- [x] 已新增 Connector 初始迁移 `0001_connector_initial`。
- [ ] 部署时需使用 Connector 专用 Alembic，不再执行国内 `migrations/versions/0021-0023`。
- [x] 已新增 `deploy/docker-compose.connector-prod.yml`，包含独立 DB、Redis、API、通用 Worker、Media Worker、Beat。
- [x] 已新增 `deploy/fb-connector-deploy.sh`，支持配置检查、迁移、启动和安全清理碎片缓存。
- [x] 已补齐海外 `/internal/meta/oauth/callback`，回调只跳转 opaque credential_id。
- [x] Insights 回调已改用原始请求体验签，再进行 JSON 解析。
- [x] 已统一 OAuth Client 使用 SaaS 生成的 `state` 参数。
- [x] 已启用 `FB_CONNECTOR_ENABLED` 配置开关。
- [x] Connector 数据库改为复用模块级连接池。
- [x] 素材 URL 已增加协议、DNS 和内网地址校验。
- [x] 已修复 Connector 所有 `connector_session_factory()()` 的重复调用问题。
- [x] Connector 环境模板已明确设置 `FB_CONNECTOR_ENABLED=true`。
- [x] 已补齐根目录和国内部署模板的 Connector 参数。
- [x] 已修正海外 OAuth 回调地址为 `/internal/meta/oauth/callback`。
- [x] 国内 `api/meta_auth.py` 授权入口已支持 Connector 模式，前端无需更换调用地址。
- [x] 国内 `sdk-config` 已支持从海外 Connector 获取 Meta App 配置。
- [x] 海外 Connector 已新增 `sdk-config` 和 `sdk-login`，Token 在海外交换和加密保存。
- [ ] 国内 `sdk-login` 及后续 businesses/accounts 接口仍需完成 Connector 凭据映射。
- [x] 国内 `/businesses` 和 `/ad-accounts` 已支持 Connector 凭据查询。
- [x] 海外已新增 OAuth-first BM 和广告账户查询接口。
- [ ] `complete-accounts` 仍需改为 Connector 结果落库。
- [x] `complete-accounts` 已支持 Connector 模式，国内仅保存 `connector_credential_id` 引用。
- [x] 已新增 `services/credential_resolver.py`，统一返回 direct/connector 凭据引用。
- [x] Connector 凭据引用不会在国内解密或携带 Token。
- [x] Connector 已对内部接口启用 HMAC + Bearer Service Token 双重校验。
- [x] Connector 模式 Page 同步只保存 Page 元数据和 `connector_credential_id`，不保存或回传 Page Token。
- [x] `meta_pages.page_access_token_encrypted` 已允许为空，并新增 Connector 引用迁移。
- [ ] 待投放、素材和报表任务全面改用 `CredentialResolver`。
- [x] 已为 `meta_accounts`、`ad_accounts` 增加 `connector_credential_id` 引用字段。
- [x] 已新增国内迁移 `0033_connector_credential_refs`。
- [x] 国内授权入口保留 `direct` 模式回滚路径。
