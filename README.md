# tg-group-guardian

一个 Telegram 群管 + 投稿审核机器人：**纯 Python 标准库、单文件、零第三方依赖**，`python3 bot.py` 就能跑。所有设置都在一个 `config.json` 里，源码不写死任何群 ID、管理员 ID 或密钥。

## 功能

**群管理**
- 新人按钮真人验证：进群先禁言，限时内点按钮才解禁，超时自动移出；验证欢迎消息会自动清理
- 链接/广告自动删帖：警告累计（默认 3 次）自动禁言 1 小时
- 违禁词过滤：词表是独立文本文件，一行一个词，随时改
- 刷屏检测：短时间连发自动删帖 + 短禁言（阈值可配）
- 管理员命令（回复目标消息后发送）：`/mute`、`/unmute`、`/kick`、`/ban`、`/unban <id>`、`/id`
- 群里 @ 机器人或提到「投稿 / 群规」关键词时自动回复说明（带 60 秒冷却，不刷屏）

**投稿审核（可整体关闭）**
- 用户私聊发照片/视频投稿，连发自动合并成一条（相册式，上限可配）
- 投稿人补一段文字介绍：可选用模板填写；可开启 AI 自动整理（默认关闭，需自备 API key）把自由文本整理成统一字段，并回发投稿人确认
- 可选匿名 / 带用户名发布；选完才转超级管理员审核，管理员点按钮通过后才发布到频道，图文说明合并在同一条里
- 投稿频率限制，防刷

**进群通道**
- 私聊机器人点「申请进群」：自动生成一人一用的专属邀请链接
- 链接进群申请（chat join request）自动转发超级管理员，按钮批准/拒绝

## 部署三步

1. **建机器人拿 token**：在 Telegram 里找 @BotFather 发 `/newbot`，按提示拿到 token，把 token 单独存成一个文件，例如 `/root/.tg-group-guardian_token`（权限建议 600）。把机器人拉进你的群和频道，并设为管理员（需要删消息、禁言、邀请链接权限）。
2. **填配置**：`cp config.example.json config.json`，按下面说明改成你自己的值；再 `cp banwords.example.txt banwords.txt` 按需改词表。
3. **启动**：先前台试跑确认无误：

   ```bash
   python3 bot.py
   ```

   正式常驻用 systemd（示例 unit，把路径换成你的实际路径）：

   ```ini
   [Unit]
   Description=tg-group-guardian
   After=network-online.target

   [Service]
   WorkingDirectory=/opt/tg-group-guardian
   ExecStart=/usr/bin/python3 /opt/tg-group-guardian/bot.py
   Restart=always
   RestartSec=5

   [Install]
   WantedBy=multi-user.target
   ```

   存为 `/etc/systemd/system/tg-group-guardian.service` 后 `systemctl enable --now tg-group-guardian`。

运行状态（警告次数、待验证名单、投稿队列）保存在同目录的 `state.json`，自动生成，不用管。

## 配置项说明（config.json）

| 键 | 说明 |
| --- | --- |
| `token_file` | 存放 Bot Token 的文件路径。token 不写进 config、更不写进代码。 |
| `channel_id` | 投稿审核通过后发布到的频道 ID（`-100` 开头）。只用群管功能时可随便填一个占位值。注意：私聊「申请进群」发的专属链接也是这个目标的链接，频道和群都适用。 |
| `managed_group_ids` | 机器人要管理的群 ID 列表。留空数组 = 它所在的所有群都管；填了就只管列表里的群。 |
| `super_admin_id` | 超级管理员的 TG 数字 ID：投稿审核、进群申请都发给他；他在任何群里都视为管理员。 |
| `verify_timeout_seconds` | 新人验证时限（秒），默认 300（5 分钟）。 |
| `verify_pass_message_ttl_seconds` | 「验证通过」欢迎消息多少秒后自动删除，默认 300；填 0 不删。 |
| `warnings_before_mute` | 累计警告多少次触发禁言，默认 3。 |
| `mute_seconds` | 警告触发的禁言时长（秒），默认 3600。 |
| `flood.max_messages` / `flood.window_seconds` / `flood.mute_seconds` | 刷屏判定：窗口秒数内超过 N 条即删帖并禁言 M 秒。默认 10 秒 6 条、禁言 600 秒。 |
| `banwords_file` | 违禁词文件路径（相对路径按 bot.py 所在目录解析）。 |
| `submissions.enabled` | 投稿功能总开关。关掉后私聊只剩申请进群。 |
| `submissions.max_media` | 一条投稿最多合并多少个照片/视频，默认 30。 |
| `submissions.rate_limit_count` / `submissions.rate_limit_window_seconds` | 投稿频率限制：窗口内最多投 N 条，默认 3600 秒 5 条。 |
| `submissions.fields` | 投稿字段清单，模板、AI 整理、确认稿都按这个清单生成。默认：标题 / 分类 / 地区 / 说明 / 署名。 |
| `submissions.rules_text` | 投稿规则文案（/start 和投稿入口展示）。留空用内置默认文案。 |
| `submissions.ai_parse.enabled` | AI 自动整理投稿介绍，默认 **false 关闭**。 |
| `submissions.ai_parse.api_key_file` | 存放你自己的 API key 的文件路径（**需要自备 key**，代码不内置任何密钥）。 |
| `submissions.ai_parse.api_base` | OpenAI 兼容的 chat completions 接口地址，例如 OpenRouter 的接口。 |
| `submissions.ai_parse.models` | 模型名列表，按顺序尝试，第一个失败自动换下一个。 |
| `texts.welcome_extra` | 新人验证欢迎语全文覆盖（可用 `{minutes}` 占位验证分钟数）。留空用默认。 |
| `texts.mention_reply` | 群里 @ 机器人时的固定回复。留空用默认。 |
| `texts.group_rules` | 群里问「群规/规则」时的回复。留空用默认。 |

## 说明

- 语言：界面文案为中文，在 `bot.py` 里都是普通字符串，可自行替换。
- 机器人必须是群管理员（删消息、限制成员、邀请链接权限），否则群管功能会静默失败并在日志里打出 `API NOT OK`。
- 频道投稿发布要求机器人是频道管理员。

## 定制开发

这个模板是通用版：字段、文案、阈值都能自己改。如果你的社区有特殊流程（自定义投稿字段、审核规则、和其他系统打通等），需要定制版或代部署，可联系作者获取付费定制服务。

## License

MIT，见 [LICENSE](LICENSE)。
