# FB 最终切割检查清单

## 自动检查

在国内 SaaS 部署机执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check_fb_split_cutover.ps1 -EnvFile deploy/.env
```

必须输出：

```text
CUTOVER_CHECK_PASSED
```

## 人工确认

- [ ] 所有租户已切换到 Connector 模式。
- [ ] OAuth 回调已改为海外域名。
- [ ] 海外 Connector API、Worker、Beat 正常。
- [ ] 海外 Connector 数据库已执行 `alembic -c fb_connector/alembic.ini upgrade head`。
- [ ] 海外使用 `deploy/docker-compose.connector-prod.yml` 独立部署，不依赖国内 Compose。
- [ ] 本地验证可使用 `CONNECTOR_ENV_FILE=fb-connector.env.example`；生产必须使用 `fb-connector.env`。
- [ ] 海外服务器可执行 `bash deploy/fb-connector-deploy.sh` 一键部署。
- [ ] 国内服务器没有 `FB_APP_SECRET`、`FB_ACCESS_TOKEN`。
- [ ] Page Token 不通过接口返回国内。
- [ ] 投放任务具备幂等键和状态回调。
- [ ] Insights 回调已落库并按 request_id 去重。
- [ ] 已完成 Connector 宕机和 Meta 限流演练。
- [ ] 已备份数据库和上一个可部署版本。

## 最终切换

满足全部人工确认后才执行：

```env
APP_ROLE=saas
FB_ACCESS_MODE=connector
FB_CONNECTOR_ENABLED=true
```

之后再删除国内 `facebook_business` 依赖和直连代码。当前阶段不自动删除，避免在测试环境未完成时造成不可逆影响。

## T12 当前记录

- [x] 已新增只读切割前检查脚本。
- [x] 已新增最终切割检查清单。
- [ ] 尚未执行生产切割，原因是前置联调和真实故障演练尚未完成。
