# tg-group-guardian

English | [简体中文](README_zh.md)

A Telegram group-management + submission-review bot I run for my own community. Single file, stdlib only — `python3 bot.py`. Everything personal lives in `config.json`; the code has no group IDs, admin IDs or secrets baked in.

What it does:

- Group management — new members must pass a button verification within a time limit (default 5 min) or they are removed; verification and welcome messages clean up after themselves. Links and ads are auto-deleted, warnings stack up to a mute (default: 3 warnings = 1 hour). Banned words are a plain text file. Flood detection, plus reply-based admin commands: `/mute`, `/unmute`, `/kick`, `/ban`, `/unban <id>`, `/id`. Mention the bot, or use the submission/rules keywords, and it answers with an explainer (60 s cooldown so it doesn't spam).
- Submissions (optional, can be switched off entirely) — users DM photos/videos; consecutive sends merge into one post. The submitter adds a description, optionally structured by an AI pass (off by default, bring your own API key) and confirmed by the submitter first; then a super admin approves with a button and it posts to the channel. Anonymous or credited, rate-limited.
- Join requests — DM the bot for a single-use personal invite link; join requests are forwarded to the super admin to approve or reject.

Deploy: BotFather → save the token into its own file (chmod 600). `cp config.example.json config.json`, `cp banwords.example.txt banwords.txt`, fill both in. Run `python3 bot.py` in the foreground once to check it behaves, then park it under systemd (unit below). State (warning counts, pending verifications, submission queue) is `state.json` next to the script, created automatically.

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

Config keys you will actually touch: `token_file`, `channel_id`, `managed_group_ids` (empty = every group it is in), `super_admin_id`, `verify_timeout_seconds`, `warnings_before_mute`, `mute_seconds`, `flood.*`, `submissions.enabled`, `submissions.max_media`, `submissions.rate_limit_*`. The rest (AI parsing options, text overrides) are listed in `config.example.json`.

Notes: UI texts are Chinese string literals in `bot.py` — swap them freely. The bot must be a group admin (delete messages, restrict members, invite links) or moderation fails quietly with `API NOT OK` in the log; posting submissions needs channel admin too.

Custom work: fields, texts and thresholds are all yours to change. If your community has a weird flow and you'd rather pay than tinker, I also take custom / deployment gigs.

MIT, see [LICENSE](LICENSE).
