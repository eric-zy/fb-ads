# OAuth Connector 真实授权回归

## 自动检查

在国内 SaaS 工作目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check_oauth_connector_regression.ps1 `
  -SaasBase http://49.232.238.163:8094 `
  -ConnectorBase https://iornix.com
```

脚本验证：国内 callback 无内部签名可达且无效 state 安全回跳、海外 callback 可达、海外其他 `/internal/*` 路由无签名返回 401，以及两个受信回跳 origin 仍在白名单内。

## 真实授权验收

1. 打开 `http://49.232.238.163:8094`，使用测试租户管理员登录。
2. 从“添加 Meta 广告账户”发起 OAuth；浏览器应跳转到 Meta，回调地址应为海外 Connector 配置的回调地址。
3. 完成 Meta 授权后，浏览器回到国内 SaaS 的账户页；地址栏只能出现 opaque `credential_id`，不得出现 access token、App Secret 或 Page Token。
4. 读取广告账户列表，选择一个测试账户并提交。确认账户记录的 `connector_credential_id` 非空，国内 `Credential` 不含海外 Token；BM 账户的默认凭据应指向本次授权产生的 Connector 凭据。
5. 确认账户、Page 或授权状态同步任务进入成功/部分成功，并记录任务 ID、账户 ID、BM ID 和同步时间；失败时记录 `last_sync_error` 与 Connector request ID。
6. 重复执行第 3–5 步：相同 Meta 账户和广告账户应复用/更新已有记录，不产生重复账户或继续引用已禁用凭据。
7. 用浏览器开发者工具确认：去掉内部签名不能访问 Connector 受保护 API；保留浏览器 callback 无签名仍可完成 state 校验和回跳。

## 当前阻断项

- 本机对 `https://iornix.com` 的 TLS 握手失败；在海外 Connector 部署机或具备正确证书链的网络环境执行自动检查后，才能勾选海外 callback 可达。
- 真实 Meta 授权必须由具备测试 Meta 账号权限的操作员在浏览器完成，不能用伪造 code 代替。
