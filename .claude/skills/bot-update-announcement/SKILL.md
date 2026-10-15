---
name: bot-update-announcement
description: 部署 Discord 机器人（Fairy，Fly.io）前撰写并校验更新公告 bot/announcements/NNNN.md。每次部署带代码变更都必须先跑这个流程；部署后服务启动会把最新公告向 /订阅更新公告 的频道各推送一次。
---

# Bot Update Announcement

为每次部署写一份更新公告，保证只写本次真实生效的变化、与上一份首尾相接、每次部署只推送一次、严格按模板。

规则真源：仓库根目录 `AGENTS.md`；本 skill 只补充公告流程，冲突时以 `AGENTS.md` 为准。

## 运行机制（写之前先理解）

- 公告文件：`bot/announcements/0001.md`、`0002.md` …，编号连续，一次部署最多新增一份。
- 服务启动（`main.py --serve` / `--serve-only`）且 `DISCORD_UPDATE_ANNOUNCE_ENABLED=true` 时，`src/services/bot_update_announcement_service.py` 把**最新一份**渲染成 embed，发到每个订阅频道。
- 每个（公告, 频道）先在 `bot_update_deliveries` 表登记再发送：重启、改 secrets、重复部署同一版本都不会重发；新订阅的频道从下一份公告开始收。
- 失败不重试（at-most-once），看日志 `[更新公告]`。

## 流程

1. 代码改动先提交（公告不能和被公告的代码在同一个 commit 里，否则 head 无法指向自己）。
2. 运行：

   ```bash
   python scripts/check_update_announcement.py prepare
   ```

   得到下一份的 `id`、`base`（= 上一份的 head，首份为部署前基线）和 **base..HEAD 的净 diff**（只含会打进镜像的路径）。
3. 按下方「取材规则」逐条核对净 diff，按「模板」写 `bot/announcements/NNNN.md`，`head` 填被公告的最后一个代码 commit 的完整 sha。
4. 校验并提交公告：

   ```bash
   python scripts/check_update_announcement.py check --require-current
   ```

   必须输出 `OK`，并检查打印出的渲染效果。
5. 推送到 fork 的 `main`，经用户确认后部署（`fly deploy -a fairy-stock-bot-yonezawa`）。部署后看 `fly logs` 中的 `[更新公告] #N 发送完成`。

## 取材规则（硬性）

1. **只写净变化**：以 `prepare` 输出的 `base..HEAD` 净 diff 为唯一依据，不按 commit 列表逐条翻译。中途加了又删、改了又改回的东西在净 diff 里不存在，就不写。
2. **只写真实生效的**：每一条都要能在代码里找到用户可触达的入口——已注册的斜杠命令、运行时会读取的配置、会被调用的代码路径、用户看得到的报告/消息变化。以下不写：
   - 测试、文档、CI、重构、日志措辞等用户感知不到的改动；
   - 没被任何入口调用的代码、默认关闭且 Fly 上没开的开关；
   - 上游同步里与本 bot 无关的部分（A 股 / Web UI / 桌面端等本服务不用的功能）。
3. **不注水**：禁止“优化性能”“提升稳定性”“修复若干问题”这类无法核对的条目。宁可少写；净 diff 确实没有用户可见变化时，只写一条 `## 注意事项` 的 `- **内部维护**：本次没有用户可见变化`。
4. **数据要准**：命令名、参数、数字、默认值都从当前代码读取后再写，不凭记忆；写 `/xxx` 前确认它在 `scripts/register_discord_commands.py` 和 `bot/commands/` 里都存在。
5. **连续性**：已发布的公告（编号小于新公告的文件）一律不改；前一份写错了，在新公告的 `## 修复` 或 `## 注意事项` 里更正并注明“更正 #N”。
6. **配置类变化**：只在 Fly 上改 secrets（如 `STOCK_LIST`、模型）不会触发公告；若用户可感知，写进下一份公告的 `## 配置变更`。

## 模板

```markdown
---
id: 2
date: 2026-10-16
base: <上一份公告 head 的完整 sha>
head: <本次公告覆盖的最后一个代码 commit 的完整 sha>
---
## 新增
- **主题**：一句话讲清能做什么，命令写成 `/analyze 代码`
## 改进
- **主题**：改了什么、对用户意味着什么
## 修复
- **主题**：之前什么问题，现在怎样
## 配置变更
- **主题**：哪个设置变了、从什么变成什么
## 注意事项
- **主题**：需要用户知道或配合的事
```

格式约束（`check` 会强制）：

- 章节只能是 `新增 / 改进 / 修复 / 配置变更 / 注意事项`，按此顺序，没有内容的章节整段删除。
- 每条必须是 `- **主题**：说明`，主题 ≤ 16 字，用全角冒号；不允许 TODO、待补充等占位符，不允许重复条目。
- 渲染后的正文 ≤ 4096 字符；建议总条目 ≤ 10，一条一句话。

渲染效果（Discord embed）：

```text
📈 Fairy 更新日志 · 2026-10-16
公告 #2（接续 #1）。更新内容如下——

✨ 新增
- 主题：……

共 N 项改动 · 不想收了：/取消订阅更新公告 · abc1234..def5678
```
