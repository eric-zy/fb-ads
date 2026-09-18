# 阿里云 OSS 第一阶段资源与权限准备

## 资源约定

- Bucket：私有读写，生产环境使用独立业务 Bucket。
- Region/Endpoint：必须与 Bucket 实际地域一致。
- Object 前缀：`ossuser/oversea/{tenantId}/{userId}/{platform}/{yyyy}/{MM}/{dd}/{assetId}/...`，`platform` 默认 `meta`。
- 前端只使用 STS 临时凭证或服务端生成的短期签名 URL。
- 长期 AccessKey 仅存放在服务端密钥系统，不进入前端、日志或 Git。
- 当前部署只提供 `ADS_OSS_ACCESS_KEY_ID`、`ADS_OSS_ACCESS_KEY_SECRET`、`ADS_OSS_BUCKET`、`ADS_OSS_REGION` 时，服务端直接使用 RAM 用户 AccessKey 生成短期签名 URL；应用只将签名 URL 返回给浏览器。
- 如果后续增加 `OSS_STS_ROLE_ARN`，则自动切换为 AssumeRole/STS 模式。

## RAM 权限

1. 创建上传角色，使用 `ram-policy-upload.json`，只允许写入 `ossuser/oversea/*`。
2. 创建服务端角色，使用 `ram-policy-server.json`，用于校验、读取、签名下载和删除。
3. 允许应用身份调用 `sts:AssumeRole`，但不要把 OSS 全量权限交给浏览器。
4. 生产环境将 Bucket 名称、Role ARN、Endpoint 写入部署密钥管理，不写入仓库。

## Bucket 建议

- ACL：Private。
- CORS：仅允许实际前端域名，允许 `PUT`、`POST`、`GET`、`HEAD`，暴露 `ETag`。
- 生命周期：清理未完成 Multipart Upload；正式上线后再配置版本保留策略。
- 日志：启用 OSS 访问日志或审计能力，避免记录临时凭证。

## 本阶段完成标准

- Bucket、RAM 角色和最小权限策略已由云管理员创建。
- 服务端可以使用 STS 获取临时凭证。
- 临时凭证只能访问指定 Bucket/前缀。
- 上传、下载、删除权限边界通过云端验证。

真实云资源创建需要阿里云账号权限；本仓库只提交配置契约和策略模板，不保存任何真实密钥。
