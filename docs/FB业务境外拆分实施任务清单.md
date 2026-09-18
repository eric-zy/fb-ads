# FB 业务境外拆分实施任务清单

## 0. 执行原则

- 国内 SaaS 服务不再直接访问 `graph.facebook.com`。
- Access Token、App Secret、OAuth 回调处理只存在于海外 FB Connector。
- 每个任务完成后必须通过验收，再进入下一个任务。
- 每个迁移任务保留开关和回滚路径，不一次性删除旧逻辑。
- 不共享两边数据库；通过 API、任务回调或事件同步数据。

## 1. 任务总览

| 编号 | 任务 | 目标 | 依赖 |
|---|---|---|---|
| T01 | 代码与部署盘点 | 固化现状和迁移边界 | 无 |
| T02 | 环境配置分层 | 建立 SaaS/Connector 两套配置 | T01 |
| T03 | 服务间认证 | 建立国内到海外的安全调用链路 | T02 |
| T04 | FB Connector 外壳 | 建立独立海外服务和健康检查 | T02、T03 |
| T05 | 国内 Connector Client | 国内统一通过 Client 调用海外服务 | T03、T04 |
| T06 | OAuth 与凭据迁移 | Token 全部收敛到海外 | T05 |
| T07 | BM/广告账户/Page 同步迁移 | 迁移资产查询和同步 | T06 |
| T08 | 素材上传迁移 | 迁移图片、视频上传 | T06、T07 |
| T09 | 投放任务迁移 | 迁移 Campaign/AdSet/Ad 创建 | T08 |
| T10 | Insights 和定时任务迁移 | 迁移报表和同步任务 | T07、T09 |
| T11 | 灰度、压测与故障演练 | 验证稳定性和可回滚性 | T06-T10 |
| T12 | 关闭国内 FB 直连 | 完成最终切割 | T11 |

## 2. T01：代码与部署盘点

### 修改范围

- `config/settings.py`
- `services/meta/`
- `api/meta_auth.py`
- `api/meta_accounts.py`
- `api/credentials.py`
- `api/meta_pages.py`
- `api/media.py`
- `tasks/`
- `celery_app.py`
- `deploy/docker-compose.yml`

### 执行步骤

1. 使用以下命令导出 FB 依赖清单：

   ```powershell
   rg -n -i "facebook|graph\.facebook|FB_|MetaClient|facebook_business" api services tasks main.py celery_app.py config deploy
   ```

2. 为每个调用标记：`OAuth`、`账户同步`、`素材上传`、`投放`、`报表`。
3. 标记每个调用的输入、输出、异常和数据库影响。
4. 记录当前生产环境、域名、数据库、Redis、队列和回调地址。
5. 将结果补充到 `docs/FB迁移调用清单.md`。

### 验收

- 所有 FB 直连点都有责任人和迁移任务。
- 所有生产配置项都能归类为 SaaS、Connector 或公共配置。

### 回滚

- 本任务只产生文档，无代码回滚要求。

## 3. T02：环境配置分层

### 修改内容

在 `config/settings.py` 增加：

```python
APP_ROLE: str = os.getenv("APP_ROLE", "saas")
FB_CONNECTOR_BASE_URL: str = os.getenv("FB_CONNECTOR_BASE_URL", "")
FB_CONNECTOR_TIMEOUT: int = int(os.getenv("FB_CONNECTOR_TIMEOUT", "30"))
FB_CONNECTOR_SIGNING_KEY: str = os.getenv("FB_CONNECTOR_SIGNING_KEY", "")
CONNECTOR_SERVICE_TOKEN: str = os.getenv("CONNECTOR_SERVICE_TOKEN", "")
SAAS_CALLBACK_BASE_URL: str = os.getenv("SAAS_CALLBACK_BASE_URL", "")
```

### 执行步骤

1. 更新 `.env.example` 为本地开发配置。
2. 更新 `deploy/.env.example` 为生产 SaaS 配置。
3. 新增 `deploy/fb-connector.env.example` 为海外配置。
4. 增加启动校验：
   - `APP_ROLE=saas` 不要求 FB Secret。
   - `APP_ROLE=fb_connector` 必须要求 `FB_APP_ID`、`FB_APP_SECRET`。
   - 生产环境禁止默认密钥。
5. 将生产密钥放入 Secret Manager 或部署平台密钥配置，不提交 Git。

### 验收

```powershell
python -c "from config.settings import settings; print(settings.APP_ROLE)"
```

- SaaS 环境不含 `FB_APP_SECRET`。
- Connector 环境可以正常加载 Meta 配置。

### 回滚

- 保留原有 `FB_*` 默认读取逻辑，配置校验通过后再切换角色。

## 4. T03：服务间认证

### 新增模块

```text
core/service_auth.py
services/request_signer.py
```

### 执行步骤

1. 定义请求头：

   ```text
   X-Service-Name
   X-Request-Id
   X-Timestamp
   X-Signature
   X-Idempotency-Key
   ```

2. 使用 HMAC-SHA256 对 HTTP 方法、路径、时间戳、请求体摘要签名。
3. 海外 Connector 校验签名、时间窗口和来源服务名。
4. 国内回调接口使用同样的签名校验。
5. 禁止将签名密钥写入日志。

### 验收

- 正确签名请求返回 2xx。
- 错误签名、过期时间戳、重复幂等键均被拒绝或复用原结果。
- 单元测试覆盖签名生成和校验。

### 回滚

- 通过 `SERVICE_AUTH_ENABLED=false` 暂时回到开发环境无签名模式；生产不得关闭。

## 5. T04：建立海外 FB Connector

### 目录建议

```text
fb_connector/
├─ main.py
├─ api/
├─ services/meta/
├─ tasks/
└─ config/settings.py
```

### 执行步骤

1. 复制并整理当前 `services/meta/` 到 Connector 服务。
2. 将 OAuth、Meta API、Token、Meta Celery 任务迁入 Connector。
3. 增加：

   ```text
   GET /internal/health
   GET /internal/ready
   ```

4. 增加 Dockerfile 和独立 Compose 服务。
5. Connector 只监听内网或 HTTPS，不直接暴露管理接口。
6. 增加统一错误格式和 `request_id`。

### 验收

- Connector 可以独立启动。
- Connector 可以初始化 Meta SDK。
- 无 FB 配置时 SaaS 仍可启动。
- 健康检查能区分应用正常、数据库异常和 Meta 配置缺失。

### 回滚

- Connector 不接管线上流量，旧 SaaS 直连逻辑继续保留。

## 6. T05：国内 Connector Client

### 新增模块

```text
services/fb_connector_client.py
```

### 执行步骤

1. 实现统一方法：

   ```python
   authorize()
   verify_business()
   sync_accounts()
   sync_pages()
   upload_media()
   create_campaign()
   get_insights()
   ```

2. 所有方法自动加入签名、超时、重试和 `request_id`。
3. 将 Connector 错误转换为 SaaS 业务错误。
4. 增加 `FB_ACCESS_MODE=direct|connector|dual` 配置。
5. `dual` 模式下记录两边结果差异，但不重复执行写入型 Meta 请求。

### 验收

- 使用 Mock Connector 完成 Client 单元测试。
- Connector 不可用时返回明确的“FB 服务暂不可用”。
- 超时和 5xx 错误按策略重试。

### 回滚

- `FB_ACCESS_MODE=direct` 恢复旧调用路径。

## 7. T06：OAuth 与凭据迁移

### 执行步骤

1. 将 `api/meta_auth.py` 和 OAuth Service 放到 Connector。
2. Connector 生成授权地址，国内只转发授权地址。
3. OAuth Callback 只在 Connector 域名注册。
4. Connector 加密保存 Access Token。
5. Connector 回调 SaaS：`credential_id`、scope、过期时间、Meta 用户 ID 和状态。
6. 国内禁止保存明文 Token。
7. 旧凭据逐个验证，验证失败标记为 `EXPIRED` 或 `DISABLED`。

### 验收

- 浏览器全程不接触 App Secret。
- 国内数据库和日志搜索不到明文 Token。
- 新授权、Token 轮换、失效检测均正常。

### 回滚

- 保留旧凭据数据和旧 OAuth 路由，但关闭新入口流量即可回退。

## 8. T07：BM、广告账户、Page 同步迁移

### 执行步骤

1. Connector 提供 BM 校验、账户列表、Page 列表接口。
2. 修改 `api/meta_accounts.py`、`api/accounts.py`、`api/meta_pages.py`，改用 `FBConnectorClient`。
3. 统一返回脱敏后的资产数据。
4. 同步结果写入国内业务数据库。
5. 增加同步版本号和最后同步时间。
6. 同步失败只更新同步状态，不覆盖上一次有效数据。

### 验收

- 新增 BM、验证 BM、账户同步和 Page 同步正常。
- Connector 断开时，历史账户数据仍可查看。

### 回滚

- 按租户切换回 `direct` 模式。

## 9. T08：素材上传迁移

### 执行步骤

1. 国内先保存素材元数据和本地/对象存储地址。
2. 国内向 Connector 提交 `media_id`、文件地址和目标广告账户。
3. Connector 下载或流式读取素材并上传 Meta。
4. Connector 返回 `image_hash`、`video_id` 等结果。
5. 国内保存结果和 Connector 任务 ID。
6. 视频上传使用独立超时和断点/重试策略。

### 验收

- 图片、视频上传成功。
- 大文件超时不会阻塞 API 请求。
- 重试不会生成重复素材记录。

### 回滚

- 暂时恢复国内上传路径；已经上传成功的 Meta 素材不删除。

## 10. T09：投放任务迁移

### 执行步骤

1. 国内创建 SaaS 任务并生成唯一 `idempotency_key`。
2. 国内调用 Connector 创建执行任务。
3. Connector Worker 执行 Campaign、AdSet、Ad 创建。
4. Connector 按步骤回调国内任务状态。
5. 失败时记录 Meta 错误码、错误分类和可重试标记。
6. 补偿删除只允许 Connector 执行。
7. 国内前端只展示任务状态，不直接接触 Meta API。

### 验收

- 单次任务完整创建 Campaign/AdSet/Ad。
- 网络重试不会重复创建对象。
- 部分失败可以定位到具体步骤。
- Connector 重启后任务可以继续或安全重试。

### 回滚

- 按租户关闭 Connector 投放开关，未执行任务回到旧 Worker。

## 11. T10：Insights 和定时任务迁移

### 执行步骤

1. 将 `fetch_account_insights`、`sync_campaigns_task` 等 FB 任务迁入 Connector。
2. 国内 Beat 只创建同步意图或查询任务。
3. Connector Beat 调度 Meta 拉取任务。
4. Connector 回调或批量推送标准化报表数据。
5. 国内报表接口只查询国内数据库。
6. 增加断点、分页游标和最后成功同步时间。

### 验收

- 7/30/90 天报表数据正常。
- Meta 限流后能延迟重试。
- 重复同步不会重复写入统计数据。

### 回滚

- 保留旧定时任务配置，按任务类型切换回旧实现。

## 12. T11：灰度、压测和故障演练

### 执行步骤

1. 选择一个测试租户启用 `connector` 模式。
2. 验证 OAuth、同步、上传、投放、报表全流程。
3. 对 Connector 做并发、超时、限流和大文件测试。
4. 演练：
   - Connector 宕机
   - Meta API 超时
   - Redis 中断
   - 回调重复
   - 回调乱序
   - Token 过期
5. 记录恢复时间和数据一致性结果。
6. 扩大到 10%、30%、100% 租户。

### 验收

- 关键链路成功率、P95 延迟、任务重复率达到预定指标。
- 故障时国内 SaaS 不被拖垮。
- 所有灰度开关可在不发版情况下切换。

### 回滚

- 将租户路由全部切回 `direct` 或暂停 FB 操作，不删除任务数据。

## 13. T12：关闭国内 FB 直连

### 执行步骤

1. 确认所有租户已切换到 Connector。
2. 确认国内服务器环境变量不存在：

   ```text
   FB_APP_SECRET
   FB_ACCESS_TOKEN
   FB_OAUTH_REDIRECT_URI
   ```

3. 删除或隔离国内 `facebook_business` 依赖。
4. 删除国内 FB 直连代码和旧任务入口。
5. 将 Meta OAuth 回调域名只保留海外域名。
6. 更新部署文档、监控、告警和应急手册。
7. 观察至少一个完整业务周期后关闭兼容开关。

### 验收

- 国内服务无法直接访问 Meta，但业务系统正常运行。
- 所有 FB 能力均通过 Connector 完成。
- 生产日志、镜像和环境变量检查通过。

### 回滚

- 保留上一个可部署版本和数据库备份；必要时回滚应用版本并恢复 Connector 路由。

## 14. 每个任务的固定执行模板

每次实施按以下顺序执行：

1. 建立任务分支：`codex/fb-split-Txx`。
2. 修改代码、配置或文档。
3. 执行单元测试和相关接口测试。
4. 更新迁移记录，写明变更文件、配置和风险。
5. 部署到测试环境。
6. 执行本任务验收清单。
7. 保存日志、截图或测试结果。
8. 验收通过后合并；失败则按本任务回滚点恢复。

## 15. 最小上线顺序

如果需要尽快落地，建议先执行：

```text
T01 → T02 → T03 → T04 → T05 → T06 → T07
```

完成这七项后，已经实现“OAuth、Token、BM 和账户同步走海外”。之后再继续 T08-T12，迁移素材、投放、报表和定时任务。
