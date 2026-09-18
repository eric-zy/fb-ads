# FB 拆分灰度与故障演练手册

## 灰度开关

国内 SaaS：

```env
FB_ACCESS_MODE=direct      # 回滚模式
FB_CONNECTOR_ENABLED=false
```

测试租户灰度：

```env
FB_ACCESS_MODE=connector
FB_CONNECTOR_ENABLED=true
```

切换前必须完成：

```powershell
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.connector.yml config
```

## 发布顺序

1. 部署海外 Connector API。
2. 部署海外 Connector Worker。
3. 检查 `/internal/health` 和 `/internal/ready`。
4. 执行 Alembic：

   ```powershell
   alembic upgrade head
   ```

5. 只为测试租户启用 `connector`。
6. 验证 OAuth、BM 校验、账户校验、素材上传、投放、Insights。
7. 观察任务失败率、回调失败率和 Meta 限流错误。
8. 按 10% → 30% → 100% 扩大租户范围。

## 验收矩阵

| 场景 | 检查点 | 通过标准 |
|---|---|---|
| OAuth | 授权、交换、加密落库 | 国内不出现 Token |
| BM | BM 校验 | 返回 Meta BM 信息 |
| 账户 | 归属校验 | 错误账户被拒绝 |
| 素材 | 图片、视频上传 | 返回 Meta 素材 ID |
| 投放 | Campaign/AdSet/Ad | 幂等重试不重复创建 |
| 报表 | Insights 回调 | 重复 request_id 不重复落库 |

## 故障演练

### Connector 宕机

1. 停止 Connector API。
2. 国内请求应返回 503 和 request_id。
3. SaaS 登录、模板编辑、历史报表仍可用。
4. 恢复 Connector 后重试未完成任务。

### Meta API 超时或限流

1. 模拟超时/429。
2. 检查 Worker 重试次数和延迟。
3. 确认投放写操作使用幂等键。
4. 确认失败任务保留已创建对象 ID。

### 回调重复或乱序

1. 重放相同 `request_id`。
2. 确认国内只保存一条快照。
3. 发送旧状态覆盖新状态。
4. 确认状态机拒绝回退或记录告警。

### Token 过期

1. 使用已失效凭据执行查询。
2. 确认 Connector 返回认证错误。
3. 确认国内仅更新状态，不暴露 Token。
4. 重新 OAuth 后确认新 `credential_id` 可用。

## 回滚

```env
FB_ACCESS_MODE=direct
FB_CONNECTOR_ENABLED=false
```

回滚后：

- 不删除 Connector 数据库。
- 不删除已创建的 Meta 对象。
- 保留失败任务和 request_id。
- 只允许未执行任务重新投递。
- 生产回滚完成后检查国内服务仍未泄漏 FB Secret。

## T11 验收记录

- [x] 已建立发布顺序和验收矩阵。
- [x] 已建立 Connector 宕机、Meta 超时、重复回调、Token 过期演练。
- [x] 已明确 `direct` 模式回滚方式。
- [ ] 待部署测试环境执行真实演练并填写结果。
