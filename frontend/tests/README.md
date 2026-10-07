# 前端页面回归

在 `frontend` 目录使用 Node.js 22.13+，执行：

```sh
npm ci
npm run lint
npm run type-check
npm run build
npx playwright install chromium
npm run preview -- --host 127.0.0.1 --port 4178
```

保留预览服务，在另一个终端执行 `npm run test:ui`。CI 会自动启动、清理预览服务。

可通过 `UI_TEST_BASE_URL` 修改本地测试地址。Windows 如果使用已经安装的 Edge，设置 `UI_TEST_BROWSER_PATH` 为 `msedge.exe` 的完整路径，即可跳过 Chromium 下载。

回归覆盖设置保存成功/失败、账户搜索、任务/账户/用户翻页、Dry Run 提交限制、取消确认和提交快照一致性，以及 Instagram 身份选择、同步成功/失败、切换 Page 清除身份和直接投放身份进入预检请求。测试模拟所有 API 并阻断外部网络；不读取真实凭据，不访问业务数据库，不提交真实 Meta 投放。失败截图保存在 `test-results/`。

报表同步专项回归：`node tests/report-sync-smoke.cjs`，覆盖 90 天同步、等待任务结果、业务失败提示、所选日期回补、窗口覆盖和 Meta ID 展示。

删除专项回归：`node tests/campaign-delete-smoke.cjs`，覆盖删除范围确认、取消、结果不确定时只读对账、失败重试与复制重新创建。
