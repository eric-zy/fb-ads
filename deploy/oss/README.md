# 阿里云 OSS 第一阶段资源与权限准备

## 资源约定

- Bucket：私有读写，生产环境使用独立业务 Bucket。
- Region/Endpoint：必须与 Bucket 实际地域一致。
- Object 前缀：`ossuser/oversea/{tenantId}/{userId}/{platform}/{yyyy}/{MM}/{dd}/{assetId}/...`，`platform` 默认 `meta`。
- 对象文件名：`{userId}_{yyyyMMddHHmmss}_{digest}.{ext}`；优先使用上传文件 MD5，未提供 MD5 时使用真实文件 SHA-256 前 32 位，不再使用 assetId 作为内容指纹。
- 去重规则：同租户、同素材类型、同文件大小且 SHA-256 相同的素材复用已有记录；MD5 作为兼容指纹并在 Worker 下载 OSS 后与 SHA-256 一起做服务端校验。
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
- 当前 IP 访问时至少加入 `http://49.232.238.163:8094`；切换域名和 HTTPS 后同步替换为正式 Origin，不建议长期使用 `*`。
- 生命周期：清理未完成 Multipart Upload；正式上线后再配置版本保留策略。
- 日志：启用 OSS 访问日志或审计能力，避免记录临时凭证。

## 本阶段完成标准

- Bucket、RAM 角色和最小权限策略已由云管理员创建。
- 服务端可以使用 STS 获取临时凭证。
- 临时凭证只能访问指定 Bucket/前缀。
- 上传、下载、删除权限边界通过云端验证。

## 素材统计回归

部署完成并登录后，可执行只读统计验收：

```bash
MEDIA_STATS_TOKEN='登录令牌' ./scripts/check_media_stats_regression.sh \
  http://127.0.0.1:8094
```

如果要验证指定广告账户维度，再追加内部账户 UUID：

```bash
MEDIA_STATS_ACCOUNT_ID='广告账户内部 UUID' \
MEDIA_STATS_TOKEN='登录令牌' \
./scripts/check_media_stats_regression.sh http://127.0.0.1:8094
```

脚本只读取总览、日期区间总览和首个素材统计，不会上传、修改或删除素材。

## 素材共享与用户隔离回归

素材在同一租户内共享，但账户绑定和修改权限仍按用户权限控制；分组移动也属于素材元数据修改，仅上传人或管理员可执行。准备一个由用户 A 上传的 `ASSET_ID`，并使用同租户用户 B 的令牌执行：

```bash
MEDIA_OWNER_TOKEN='用户 A 令牌' \
MEDIA_READER_TOKEN='用户 B 令牌' \
./scripts/check_media_access_regression.sh \
  http://127.0.0.1:8094 ASSET_ID
```

可选地验证 B 无权访问的账户绑定，以及另一租户无法读取该素材：

```bash
MEDIA_OWNER_TOKEN='用户 A 令牌' \
MEDIA_READER_TOKEN='用户 B 令牌' \
MEDIA_FORBIDDEN_ACCOUNT_ID='B 无权限的账户 UUID' \
MEDIA_OTHER_TENANT_TOKEN='其他租户令牌' \
./scripts/check_media_access_regression.sh \
  http://127.0.0.1:8094 ASSET_ID
```

该脚本为只读检查，不会上传素材、创建绑定、重试任务、刷新元数据或删除素材。

## 共享素材发布顺序

当前迁移链的唯一 head 是 `0043_shared_creative_assets`。生产发布只需执行部署脚本，脚本会自动等待 PostgreSQL，就绪后执行迁移，再重启 API、Worker、Beat 和前端：

```bash
git pull --rebase origin main
PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ ./deploy/deploy.sh
```

如需排障查看版本，可在项目目录手工执行 `python -m alembic current`；正常发布不需要再单独执行 `current` 或 `upgrade head`。迁移成功后再执行上面的双用户共享验收脚本。

注意：仓库早期的 `0003_unify_index_names` 迁移依赖在线 PostgreSQL 索引探测，因此 `alembic upgrade head --sql` 不能作为本项目完整迁移验收方式；生产必须使用实际数据库连接执行在线迁移。`0043` 会将历史素材的 `visibility` 统一为 `TENANT` 并设置后续默认值。

真实云资源创建需要阿里云账号权限；本仓库只提交配置契约和策略模板，不保存任何真实密钥。
