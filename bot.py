#!/usr/bin/env python3
# tg-group-guardian: Telegram group management + media submission review bot.
# Pure Python standard library, single file. All settings live in config.json
# (copy config.example.json and fill in your own values).
import json, os, re, time, urllib.request
from collections import defaultdict, deque

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE, 'config.json')
STATE_PATH = os.path.join(BASE, 'state.json')

DEFAULT_CONFIG = {
    'token_file': '/root/.tg-group-guardian_token',
    'channel_id': 0,
    'managed_group_ids': [],
    'super_admin_id': 0,
    'verify_timeout_seconds': 300,
    'verify_pass_message_ttl_seconds': 300,
    'warnings_before_mute': 3,
    'mute_seconds': 3600,
    'flood': {'max_messages': 6, 'window_seconds': 10, 'mute_seconds': 600},
    'banwords_file': 'banwords.txt',
    'submissions': {
        'enabled': True,
        'max_media': 30,
        'rate_limit_count': 5,
        'rate_limit_window_seconds': 3600,
        'fields': ['标题', '分类', '地区', '说明', '署名'],
        'rules_text': '',
        'ai_parse': {'enabled': False, 'api_key_file': '', 'api_base': '',
                     'models': []},
    },
    'texts': {
        'welcome_extra': '',
        'mention_reply': '',
        'group_rules': '',
    },
}

def _deep_merge(dst, src):
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_merge(dst[k], v)
        else:
            dst[k] = v
    return dst

def load_config():
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding='utf-8') as f:
            _deep_merge(cfg, json.load(f))
    return cfg

CFG = load_config()
TOKEN = open(CFG['token_file']).read().strip()
API = 'https://api.telegram.org/bot' + TOKEN + '/'
CHANNEL_ID = int(CFG['channel_id'])
SUPER_ADMIN = int(CFG['super_admin_id'])
MANAGED_GROUPS = [int(x) for x in CFG.get('managed_group_ids') or []]
VERIFY_TIMEOUT = int(CFG['verify_timeout_seconds'])
PASS_MSG_TTL = int(CFG['verify_pass_message_ttl_seconds'])
WARN_LIMIT = int(CFG['warnings_before_mute'])
MUTE_SECONDS = int(CFG['mute_seconds'])
FLOOD_N = int(CFG['flood']['max_messages'])
FLOOD_WINDOW = int(CFG['flood']['window_seconds'])
FLOOD_MUTE = int(CFG['flood']['mute_seconds'])
SUB_CFG = CFG['submissions']
SUB_ENABLED = bool(SUB_CFG['enabled'])
SUB_LIMIT = int(SUB_CFG['rate_limit_count'])
SUB_WINDOW = int(SUB_CFG['rate_limit_window_seconds'])
SUB_MAX_MEDIA = int(SUB_CFG['max_media'])
SUB_FIELDS = list(SUB_CFG['fields'])
AI_CFG = SUB_CFG['ai_parse']
TEXTS = CFG['texts']

DEFAULT_RULES = ('投稿规则：\n'
                 '1）必须附带照片或视频，纯文字不收；可以连发，机器人会自动合并成一条投稿。\n'
                 '2）请勿投稿：他人的个人隐私信息、违法内容、广告引流、重复或抄袭的内容。\n'
                 '3）投稿会先转给管理员审核，通过后发布到频道，并按你选择的方式匿名或署名。')
SUB_RULES = SUB_CFG['rules_text'] or DEFAULT_RULES
SUB_TEMPLATE = '\n'.join(f + '：' for f in SUB_FIELDS) + '\n（可以自行添加或删改栏目）'
MENTION_REPLY = TEXTS['mention_reply'] or '🤖 我是本群的管家机器人。投稿请私聊我发送照片或视频，进群问题也可以私聊我咨询。'
GROUP_RULES = TEXTS['group_rules'] or '📜 群规：友善交流｜禁止广告与链接｜禁止诈骗引流。违规内容会被自动删除，警告满 3 次禁言 1 小时。'

LINK_RE = re.compile(r'(https?://|t\.me/|www\.|\.com\b|\.top\b|\.xyz\b)', re.I)
BOT_USERNAME = ''

FULL_PERMS = dict(can_send_messages=True, can_send_audios=True, can_send_documents=True,
                  can_send_photos=True, can_send_videos=True, can_send_video_notes=True,
                  can_send_voice_notes=True, can_send_polls=True, can_send_other_messages=True,
                  can_add_web_page_previews=True)
NO_PERMS = dict(can_send_messages=False)

def load_keywords():
    p = CFG['banwords_file']
    if not os.path.isabs(p):
        p = os.path.join(BASE, p)
    if os.path.exists(p):
        return [l.strip() for l in open(p, encoding='utf-8')
                if l.strip() and not l.strip().startswith('#')]
    return ['博彩', '赌博', '刷单', '菠菜', '六合彩', '时时彩', '收购账号', '高薪兼职', '日结工资']
KEYWORDS = load_keywords()

import http.client
_conn = None
def _get_conn():
    global _conn
    if _conn is None:
        _conn = http.client.HTTPSConnection('api.telegram.org', 443, timeout=70)
    return _conn

def api(method, **params):
    global _conn
    body = json.dumps(params)
    for attempt in range(2):
        try:
            c = _get_conn()
            c.request('POST', '/bot' + TOKEN + '/' + method, body=body, headers={'Content-Type': 'application/json'})
            r = c.getresponse()
            res = json.loads(r.read())
            if not res.get('ok'):
                print('API NOT OK:', method, res, flush=True)
            return res
        except Exception as e:
            print('API err', method, e, flush=True)
            try:
                _conn.close()
            except Exception:
                pass
            _conn = None
    return {}

def load_state():
    try:
        return json.load(open(STATE_PATH))
    except Exception:
        return {}
def save_state(s):
    tmp = STATE_PATH + '.tmp'
    json.dump(s, open(tmp, 'w'))
    os.replace(tmp, STATE_PATH)

state = load_state()
for k, v in {'warns': {}, 'pending': {}, 'subs': {}, 'sub_seq': 0, 'sub_times': {}}.items():
    state.setdefault(k, v)
flood = defaultdict(deque)

_admin_cache = {}
def is_admin(chat_id, user_id):
    if user_id == SUPER_ADMIN:
        return True
    key = (chat_id, user_id)
    now = time.time()
    hit = _admin_cache.get(key)
    if hit and now - hit[1] < 300:
        return hit[0]
    r = api('getChatMember', chat_id=chat_id, user_id=user_id)
    ok = r.get('result', {}).get('status') in ('administrator', 'creator')
    _admin_cache[key] = (ok, now)
    return ok

def restrict(chat_id, user_id, perms, until=0):
    p = dict(chat_id=chat_id, user_id=user_id, permissions=perms)
    if until:
        p['until_date'] = int(time.time()) + until
    return api('restrictChatMember', **p)

def send(chat_id, text, **kw):
    return api('sendMessage', chat_id=chat_id, text=text, **kw)

def uname(u):
    n = u.get('first_name', '')
    return n + (' (@' + u['username'] + ')') if u.get('username') else n

# ---------- group management ----------
def warn_and_maybe_mute(chat_id, user, reason):
    key = str(chat_id) + ':' + str(user['id'])
    state['warns'][key] = state['warns'].get(key, 0) + 1
    n = state['warns'][key]
    save_state(state)
    name = user.get('first_name', '用户')
    if n >= WARN_LIMIT:
        restrict(chat_id, user['id'], NO_PERMS, until=MUTE_SECONDS)
        send(chat_id, f'{name} 已累计警告 {WARN_LIMIT} 次（{reason}），禁言 {MUTE_SECONDS // 60} 分钟。')
    else:
        send(chat_id, f'⚠️ {name}：{reason}，已警告 {n}/{WARN_LIMIT} 次，满 {WARN_LIMIT} 次自动禁言。')

def handle_new_members(msg):
    chat_id = msg['chat']['id']
    minutes = max(1, VERIFY_TIMEOUT // 60)
    for u in msg['new_chat_members']:
        if u.get('is_bot'):
            continue
        restrict(chat_id, u['id'], NO_PERMS)
        kb = {'inline_keyboard': [[{'text': '✅ 我是真人，点我完成验证', 'callback_data': 'verify:' + str(u['id'])}]]}
        if TEXTS['welcome_extra']:
            welcome = TEXTS['welcome_extra'].replace('{minutes}', str(minutes))
        else:
            welcome = (f"欢迎 {u.get('first_name','新朋友')} 加入！请在 {minutes} 分钟内点击下方按钮完成真人验证，否则将被移出群聊。"
                       '验证后请遵守群规：禁止广告、链接与引流。')
        if SUB_ENABLED:
            welcome += '\n\n📮 想投稿分享照片或视频，可以私聊我。'
        r = send(chat_id, welcome, reply_markup=kb)
        mid = r.get('result', {}).get('message_id')
        state['pending'][str(chat_id) + ':' + str(u['id'])] = {'deadline': time.time() + VERIFY_TIMEOUT, 'msg': mid}
    save_state(state)

def sweep_timeouts():
    now = time.time()
    changed = False
    for key, info in list(state['pending'].items()):
        if now > info['deadline']:
            chat_id, user_id = key.split(':')
            api('banChatMember', chat_id=int(chat_id), user_id=int(user_id))
            api('unbanChatMember', chat_id=int(chat_id), user_id=int(user_id), only_if_banned=True)
            if info.get('msg'):
                try:
                    api('deleteMessage', chat_id=int(chat_id), message_id=info['msg'])
                except Exception:
                    pass
            state['pending'].pop(key, None)
            changed = True
    if changed:
        save_state(state)

def handle_group_command(msg):
    chat_id = msg['chat']['id']
    user = msg['from']
    anon_admin = bool(msg.get('sender_chat')) and user.get('id') == 1087968824
    if not anon_admin and not is_admin(chat_id, user['id']):
        return True
    text = msg.get('text', '')
    cmd = text.split()[0].split('@')[0].lower()
    reply = msg.get('reply_to_message')
    target = reply['from'] if reply else None
    args = text.split()[1:]
    if cmd == '/id':
        if target:
            send(chat_id, f"用户 {target.get('first_name','')} 的 ID：{target['id']}")
        return True
    if not target and cmd in ('/mute', '/unmute', '/kick', '/ban'):
        send(chat_id, '请回复对方任意一条消息再发这个命令。')
        return True
    if cmd == '/mute':
        mins = int(args[0]) if args and args[0].isdigit() else 60
        restrict(chat_id, target['id'], NO_PERMS, until=mins * 60)
        send(chat_id, f"已禁言 {target.get('first_name','')} {mins} 分钟。")
    elif cmd == '/unmute':
        restrict(chat_id, target['id'], FULL_PERMS)
        send(chat_id, f"已解除 {target.get('first_name','')} 的禁言。")
    elif cmd == '/kick':
        api('banChatMember', chat_id=chat_id, user_id=target['id'])
        api('unbanChatMember', chat_id=chat_id, user_id=target['id'], only_if_banned=True)
        send(chat_id, f"已将 {target.get('first_name','')} 移出群聊。")
    elif cmd == '/ban':
        api('banChatMember', chat_id=chat_id, user_id=target['id'])
        send(chat_id, f"已封禁 {target.get('first_name','')}。")
    elif cmd == '/unban' and args and args[0].lstrip('-').isdigit():
        api('unbanChatMember', chat_id=int(chat_id), user_id=int(args[0]), only_if_banned=True)
        send(chat_id, '已解封该用户。')
    return True

_kw_cool = {}
def keyword_reply(chat_id, text):
    if not text:
        return False
    hit = None
    if '投稿' in text and SUB_ENABLED:
        hit = ('tougao', '📮 想投稿？私聊我发照片或视频就行（可以连发，会自动合并；纯文字不收）。详细规则私聊我发 /start 就能看到。')
    elif '群规' in text or '规则' in text:
        hit = ('guize', GROUP_RULES)
    if not hit:
        return False
    key = (chat_id, hit[0])
    now = time.time()
    if now - _kw_cool.get(key, 0) < 60:
        return True
    _kw_cool[key] = now
    send(chat_id, hit[1])
    return True

def mention_reply(chat_id, msg, text):
    if not BOT_USERNAME:
        return False
    me = '@' + BOT_USERNAME.lower()
    hit = bool(text) and me in text.lower()
    if not hit:
        for e in msg.get('entities', []):
            if e.get('type') == 'mention':
                seg = (text or '')[e['offset']:e['offset'] + e['length']]
                if seg.lower() == me:
                    hit = True
    if not hit:
        return False
    key = (chat_id, 'mention')
    now = time.time()
    if now - _kw_cool.get(key, 0) < 60:
        return True
    _kw_cool[key] = now
    send(chat_id, MENTION_REPLY)
    return True

def handle_group_message(msg):
    chat = msg.get('chat', {})
    if MANAGED_GROUPS and chat.get('id') not in MANAGED_GROUPS:
        return
    if 'new_chat_members' in msg:
        handle_new_members(msg)
        return
    user = msg.get('from')
    if not user:
        return
    anon_admin = bool(msg.get('sender_chat')) and user.get('id') == 1087968824
    if user.get('is_bot') and not anon_admin:
        return
    chat_id = chat['id']
    text = msg.get('text') or msg.get('caption') or ''
    if text.startswith('/') and handle_group_command(msg):
        return
    if mention_reply(chat_id, msg, text):
        return
    if keyword_reply(chat_id, text):
        return
    if anon_admin or is_admin(chat_id, user['id']):
        return
    dq = flood[(chat_id, user['id'])]
    now = time.time()
    dq.append(now)
    while dq and now - dq[0] > FLOOD_WINDOW:
        dq.popleft()
    if len(dq) > FLOOD_N:
        restrict(chat_id, user['id'], NO_PERMS, until=FLOOD_MUTE)
        api('deleteMessage', chat_id=chat_id, message_id=msg['message_id'])
        send(chat_id, f"{user.get('first_name','')} 刷屏，已禁言 {FLOOD_MUTE // 60} 分钟。")
        dq.clear()
        return
    has_link = bool(LINK_RE.search(text)) or any(e.get('type') in ('url', 'text_link') for e in msg.get('entities', []))
    hit_kw = next((k for k in KEYWORDS if k in text), None)
    if has_link:
        api('deleteMessage', chat_id=chat_id, message_id=msg['message_id'])
        warn_and_maybe_mute(chat_id, user, '禁止发送链接/广告')
    elif hit_kw:
        api('deleteMessage', chat_id=chat_id, message_id=msg['message_id'])
        warn_and_maybe_mute(chat_id, user, f'消息包含违禁词「{hit_kw}」')

# ---------- submissions (private chat, media required) ----------
burst_buf = {}

def _media_item(msg):
    if 'photo' in msg:
        return ('photo', msg['photo'][-1]['file_id'])
    if 'video' in msg:
        return ('video', msg['video']['file_id'])
    return None

def create_submission(user, msgs, items):
    uid = user['id']
    now = time.time()
    times = [t for t in state['sub_times'].get(str(uid), []) if now - t < SUB_WINDOW]
    if len(times) >= SUB_LIMIT:
        send(uid, '你投稿太频繁了，请过一会儿再来。')
        return
    times.append(now)
    state['sub_times'][str(uid)] = times
    state['sub_seq'] += 1
    sid = str(state['sub_seq'])
    caption = next((m.get('caption', '') for m in msgs if m.get('caption')), '')
    state['subs'][sid] = {'from': uid, 'name': uname(user), 'username': user.get('username'),
                          'msg': msgs[0]['message_id'], 'items': items,
                          'media': items[0][0], 'file_id': items[0][1],
                          'caption': caption, 'desc': '', 'mode': None, 'status': 'descing'}
    save_state(state)
    kb = {'inline_keyboard': [[{'text': '⏭ 跳过介绍', 'callback_data': 'subskip:' + sid}]]}
    send(uid, f'投稿 #{sid} 收到（共 {len(items)} 个照片/视频）！\n把资料发给我就行：随便写一段介绍，我会（在开启自动整理时）帮你整理成统一格式给你确认；也可以照下面的模板填。不想写就点「跳过介绍」。', reply_markup=kb)
    send(uid, SUB_TEMPLATE)

def _ai_key():
    p = AI_CFG.get('api_key_file') or ''
    if not p:
        return ''
    try:
        return open(p).read().strip()
    except Exception:
        return ''

def ai_parse_submission(text):
    # Optional: extract the configured submission fields from free text with an
    # OpenAI-compatible chat API. Disabled by default; requires your own API
    # key file (see config.example.json). Returns None when off/unavailable,
    # and the caller then keeps the submitter's raw text.
    if not AI_CFG.get('enabled'):
        return None
    key = _ai_key()
    base = AI_CFG.get('api_base') or ''
    if not key or not base:
        return None
    prompt = ('你是投稿信息整理助手。从下面这段话里提取信息，只输出一个 JSON 对象，不要任何解释、不要代码块标记。'
              '字段固定为：' + '、'.join(SUB_FIELDS) + '。'
              '原文没提到的字段填空字符串 ""，绝对不要编造或猜测。'
              '\n原文：' + text)
    for model in AI_CFG.get('models') or []:
        try:
            body = json.dumps({'model': model, 'messages': [{'role': 'user', 'content': prompt}], 'temperature': 0}).encode()
            req = urllib.request.Request(base, data=body,
                                         headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read())
            out = data['choices'][0]['message']['content'].strip()
            out = re.sub(r'```(json)?', '', out).strip()
            try:
                d = json.loads(out)
            except Exception:
                d = json.loads(out[out.index('{'):out.rindex('}') + 1])
            return {f: str(d.get(f, '')).strip()[:200] for f in SUB_FIELDS}
        except Exception:
            continue
    return None

def _looks_like_template(text):
    return sum(1 for f in SUB_FIELDS if (f + '：') in text or (f + ':') in text) >= 3

def _format_fields(d, all_fields=False):
    lines = []
    for f in SUB_FIELDS:
        v = d.get(f, '')
        if v or all_fields:
            lines.append(f + '：' + v)
    return '\n'.join(lines)

def send_confirm_prompt(sid):
    sub = state['subs'][sid]
    kb = {'inline_keyboard': [[{'text': '✅ 就这样', 'callback_data': 'subconfirm:' + sid}, {'text': '📝 给我模板自己填', 'callback_data': 'submanual:' + sid}]]}
    send(sub['from'], f'投稿 #{sid}：我帮你整理好了（见下）。对就点「✅ 就这样」；哪项不对，直接再发一段正确的给我，我重新整理。\n\n' + _format_fields(sub.get('draft', {}), all_fields=True), reply_markup=kb)

def handle_sub_confirm(cb):
    sid = cb['data'].split(':')[1]
    sub = state['subs'].get(sid)
    if not sub or sub['status'] != 'confirming':
        api('answerCallbackQuery', callback_query_id=cb['id'], text='这条投稿已经处理了')
        return
    if cb['from']['id'] != sub['from']:
        api('answerCallbackQuery', callback_query_id=cb['id'], text='这不是你的投稿', show_alert=True)
        return
    sub['desc'] = _format_fields(sub.get('draft', {}))
    sub['status'] = 'choosing'
    sub.pop('draft', None)
    save_state(state)
    api('answerCallbackQuery', callback_query_id=cb['id'], text='好，就按这个来')
    send_mode_prompt(sid)

def handle_sub_manual(cb):
    sid = cb['data'].split(':')[1]
    sub = state['subs'].get(sid)
    if not sub or sub['status'] != 'confirming' or cb['from']['id'] != sub['from']:
        api('answerCallbackQuery', callback_query_id=cb['id'], text='这条投稿已经处理了')
        return
    sub['status'] = 'descing'
    sub.pop('draft', None)
    save_state(state)
    api('answerCallbackQuery', callback_query_id=cb['id'], text='好，发你模板')
    send(sub['from'], '好，把下面模板填好发给我：')
    send(sub['from'], SUB_TEMPLATE)

def send_mode_prompt(sid):
    sub = state['subs'][sid]
    kb = {'inline_keyboard': [[{'text': '🕶 匿名发布', 'callback_data': 'submode:a:' + sid}, {'text': '👤 带我的用户名', 'callback_data': 'submode:n:' + sid}]]}
    send(sub['from'], f'投稿 #{sid}：再选一下发布方式（选完才会转给管理员审核）：', reply_markup=kb)

def handle_desc_input(msg):
    uid = msg['from']['id']
    cand = [s for s, sub in state['subs'].items() if sub['from'] == uid and sub['status'] in ('descing', 'confirming')]
    if not cand:
        return False
    sid = max(cand, key=lambda x: int(x))
    sub = state['subs'][sid]
    text = (msg.get('text') or '')[:2000]
    if _looks_like_template(text):
        sub['desc'] = text
        sub['status'] = 'choosing'
        sub.pop('draft', None)
        save_state(state)
        send_mode_prompt(sid)
        return True
    draft = ai_parse_submission(text)
    if draft is None:
        sub['desc'] = text
        sub['status'] = 'choosing'
        save_state(state)
        if AI_CFG.get('enabled'):
            send(uid, '自动整理没成功，先按你发的原文收下了。')
        send_mode_prompt(sid)
        return True
    sub['draft'] = draft
    sub['status'] = 'confirming'
    save_state(state)
    send_confirm_prompt(sid)
    return True

def handle_desc_skip(cb):
    sid = cb['data'].split(':')[1]
    sub = state['subs'].get(sid)
    if not sub or sub['status'] not in ('descing', 'confirming') or cb['from']['id'] != sub['from']:
        api('answerCallbackQuery', callback_query_id=cb['id'], text='这条投稿已经处理了')
        return
    sub['status'] = 'choosing'
    save_state(state)
    api('answerCallbackQuery', callback_query_id=cb['id'], text='已跳过介绍')
    send_mode_prompt(sid)

def handle_media_entry(msg):
    user = msg['from']
    uid = user['id']
    item = _media_item(msg)
    if item is None:
        send(uid, f'❌ 投稿必须附带照片或视频，纯文字不收哦。把照片或视频发给我就行，可以连发，我会自动合并成一条投稿（一次最多 {SUB_MAX_MEDIA} 个）。')
        return
    buf = burst_buf.setdefault(uid, {'msgs': [], 'items': [], 'deadline': 0})
    buf['msgs'].append(msg)
    buf['items'].append(item)
    buf['deadline'] = time.time() + 3
    if len(buf['items']) >= SUB_MAX_MEDIA:
        flush_burst(uid)

def flush_burst(uid):
    buf = burst_buf.pop(uid, None)
    if not buf:
        return
    create_submission(buf['msgs'][0]['from'], buf['msgs'], buf['items'])

delayed_deletes = []

def sweep_deletes():
    now = time.time()
    keep = []
    for when, cid, mid in delayed_deletes:
        if now >= when:
            try:
                api('deleteMessage', chat_id=cid, message_id=mid)
            except Exception:
                pass
        else:
            keep.append((when, cid, mid))
    delayed_deletes[:] = keep

def sweep_albums():
    now = time.time()
    for uid in [u for u, b in list(burst_buf.items()) if now >= b['deadline']]:
        flush_burst(uid)

def handle_sub_mode(cb):
    _, m, sid = cb['data'].split(':')
    sub = state['subs'].get(sid)
    if not sub or sub['status'] != 'choosing':
        api('answerCallbackQuery', callback_query_id=cb['id'], text='这条投稿已经处理了')
        return
    if cb['from']['id'] != sub['from']:
        api('answerCallbackQuery', callback_query_id=cb['id'], text='这不是你的投稿', show_alert=True)
        return
    sub['mode'] = 'anon' if m == 'a' else 'named'
    sub['status'] = 'pending'
    save_state(state)
    mode_txt = '匿名' if m == 'a' else '带用户名'
    api('answerCallbackQuery', callback_query_id=cb['id'], text='已选' + mode_txt + '发布')
    items = sub.get('items') or [[sub['media'], sub['file_id']]]
    kb = {'inline_keyboard': [[{'text': '✅ 通过并发布', 'callback_data': 'subok:' + sid}, {'text': '❌ 拒绝', 'callback_data': 'subno:' + sid}]]}
    send(SUPER_ADMIN, f'📥 新投稿 #{sid}，来自 {sub["name"]}（共 {len(items)} 个文件，发布方式：{mode_txt}），下方即原文：', reply_markup=kb)
    if sub.get('desc'):
        send(SUPER_ADMIN, '📝 总介绍：\n' + sub['desc'])
    if len(items) > 1:
        for k in range(0, len(items), 10):
            chunk = [{'type': t, 'media': f} for t, f in items[k:k + 10]]
            api('sendMediaGroup', chat_id=SUPER_ADMIN, media=chunk)
    else:
        api('copyMessage', chat_id=SUPER_ADMIN, from_chat_id=sub['from'], message_id=sub['msg'])
    send(sub['from'], f'投稿 #{sid} 已按「{mode_txt}」转给管理员审核，通过后发布到频道，我会通知你。')

def _split_caption(txt, limit=1024):
    if len(txt) <= limit:
        return txt, ''
    cut = txt.rfind('\n', 0, limit)
    if cut < limit // 2:
        cut = txt.rfind(' ', 0, limit)
    if cut < limit // 2:
        cut = limit
    return txt[:cut].rstrip(), txt[cut:].strip()

def handle_sub_decision(cb, ok):
    sid = cb['data'].split(':')[1]
    sub = state['subs'].get(sid)
    if not sub or sub['status'] != 'pending':
        api('answerCallbackQuery', callback_query_id=cb['id'], text='这条投稿已处理过了')
        return
    sub['status'] = 'approved' if ok else 'rejected'
    save_state(state)
    if ok:
        items = sub.get('items') or [[sub['media'], sub['file_id']]]
        desc = sub.get('desc') or sub.get('caption', '')
        suffix = ''
        if sub.get('mode') == 'named':
            who = '@' + sub['username'] if sub.get('username') else sub['name'].split(' (')[0]
            suffix = '—— 投稿来自 ' + who
        posted = False
        if len(items) > 1:
            txt = desc + ('\n\n' + suffix if suffix else '')
            cap, rest = _split_caption(txt.strip()) if txt.strip() else ('', '')
            ok_all = True
            for k in range(0, len(items), 10):
                chunk = [{'type': t, 'media': f} for t, f in items[k:k + 10]]
                if k == 0 and cap:
                    chunk[0]['caption'] = cap
                r = api('sendMediaGroup', chat_id=CHANNEL_ID, media=chunk)
                ok_all = ok_all and bool(r.get('ok'))
            posted = ok_all
            if posted and rest:
                api('sendMessage', chat_id=CHANNEL_ID, text=rest[:4000])
        else:
            cap_full = desc
            if suffix:
                cap_full = (cap_full + '\n\n' + suffix).strip()
            if cap_full:
                cap, rest = _split_caption(cap_full)
                if sub.get('media') == 'photo':
                    r = api('sendPhoto', chat_id=CHANNEL_ID, photo=sub['file_id'], caption=cap)
                else:
                    r = api('sendVideo', chat_id=CHANNEL_ID, video=sub['file_id'], caption=cap)
                posted = bool(r.get('ok'))
                if posted and rest:
                    api('sendMessage', chat_id=CHANNEL_ID, text=rest[:4000])
            if not posted and not cap_full:
                api('copyMessage', chat_id=CHANNEL_ID, from_chat_id=sub['from'], message_id=sub['msg'])
                posted = True
        if not posted:
            api('copyMessage', chat_id=CHANNEL_ID, from_chat_id=sub['from'], message_id=sub['msg'])
        send(sub['from'], f'🎉 你的投稿 #{sid} 已通过审核，发布到频道了！')
        api('answerCallbackQuery', callback_query_id=cb['id'], text='已发布到频道')
    else:
        send(sub['from'], f'你的投稿 #{sid} 这次没有通过，欢迎修改后再投。')
        api('answerCallbackQuery', callback_query_id=cb['id'], text='已拒绝并通知投稿人')
    try:
        api('editMessageReplyMarkup', chat_id=cb['message']['chat']['id'], message_id=cb['message']['message_id'], reply_markup={'inline_keyboard': []})
    except Exception:
        pass

# ---------- join flows ----------
def start_dm_join(user):
    uid = user['id']
    r = api('getChatMember', chat_id=CHANNEL_ID, user_id=uid)
    if r.get('result', {}).get('status') in ('member', 'administrator', 'creator'):
        send(uid, '你已经是成员啦，不用重复申请。')
        return
    r = api('createChatInviteLink', chat_id=CHANNEL_ID, member_limit=1, name='dm-auto')
    link = r.get('result', {}).get('invite_link')
    if link:
        send(uid, f'🎉 这是你的专属进群链接，点它就能加入（仅限你一人使用）：\n{link}')
        send(SUPER_ADMIN, f'👋 {uname(user)}（ID {uid}）刚通过机器人自动进群了。')
    else:
        send(uid, '链接生成失败，请稍后再试一次。（机器人需要是目标群/频道的管理员）')

def handle_join_request(req):
    chat_id = req['chat']['id']
    user = req['from']
    uid = user['id']
    title = req['chat'].get('title', '群')
    kb = {'inline_keyboard': [[{'text': '✅ 批准进群', 'callback_data': f'joinok:{chat_id}:{uid}'}, {'text': '❌ 拒绝', 'callback_data': f'joinno:{chat_id}:{uid}'}]]}
    send(SUPER_ADMIN, f'🙋 新的进群申请（链接申请「{title}」），来自 {uname(user)}（ID {uid}）：', reply_markup=kb)
    send(uid, f'你好 {user.get("first_name","")}！你申请加入「{title}」的请求已经转给管理员了，通过后你会收到通知，请稍等。')

def handle_join_decision(cb, ok):
    _, chat_id, uid = cb['data'].split(':')
    if ok:
        r = api('approveChatJoinRequest', chat_id=int(chat_id), user_id=int(uid))
        if r.get('ok'):
            send(int(uid), '🎉 你的进群申请通过了，欢迎加入！')
            api('answerCallbackQuery', callback_query_id=cb['id'], text='已批准')
        else:
            api('answerCallbackQuery', callback_query_id=cb['id'], text='批准失败：申请可能已过期或被处理', show_alert=True)
    else:
        r = api('declineChatJoinRequest', chat_id=int(chat_id), user_id=int(uid))
        if r.get('ok'):
            send(int(uid), '抱歉，你的进群申请这次没有通过。')
            api('answerCallbackQuery', callback_query_id=cb['id'], text='已拒绝')
        else:
            api('answerCallbackQuery', callback_query_id=cb['id'], text='拒绝失败：申请可能已过期或被处理', show_alert=True)
    try:
        api('editMessageReplyMarkup', chat_id=cb['message']['chat']['id'], message_id=cb['message']['message_id'], reply_markup={'inline_keyboard': []})
    except Exception:
        pass

# ---------- callbacks & private ----------
def handle_callback(cb):
    data = cb.get('data', '')
    if data.startswith('verify:'):
        target = int(data.split(':')[1])
        clicker = cb['from']['id']
        chat_id = cb['message']['chat']['id']
        if clicker != target:
            api('answerCallbackQuery', callback_query_id=cb['id'], text='这不是你的验证按钮', show_alert=True)
            return
        restrict(chat_id, clicker, FULL_PERMS)
        key = str(chat_id) + ':' + str(clicker)
        info = state['pending'].pop(key, None)
        save_state(state)
        api('answerCallbackQuery', callback_query_id=cb['id'], text='验证通过，欢迎！')
        if info and info.get('msg'):
            api('deleteMessage', chat_id=chat_id, message_id=info['msg'])
        r = send(chat_id, f"🎉 {cb['from'].get('first_name','')} 验证通过，欢迎加入！发帖请勿带广告与链接，祝玩得开心。")
        _vmid = r.get('result', {}).get('message_id') if isinstance(r, dict) else None
        if _vmid and PASS_MSG_TTL > 0:
            delayed_deletes.append((time.time() + PASS_MSG_TTL, chat_id, _vmid))
    elif data == 'join_start':
        api('answerCallbackQuery', callback_query_id=cb['id'])
        start_dm_join(cb['from'])
    elif data == 'tougao_hint':
        api('answerCallbackQuery', callback_query_id=cb['id'])
        send(cb['from']['id'], SUB_RULES + f'\n\n👉 直接把照片或视频发给我就行，可以连发（一次最多 {SUB_MAX_MEDIA} 个），发完我会问你要不要给整组加一段总介绍。')
    elif data.startswith('subskip:'):
        handle_desc_skip(cb)
    elif data.startswith('subconfirm:'):
        handle_sub_confirm(cb)
    elif data.startswith('submanual:'):
        handle_sub_manual(cb)
    elif data.startswith('submode:'):
        handle_sub_mode(cb)
    elif data.startswith('subok:'):
        handle_sub_decision(cb, True)
    elif data.startswith('subno:'):
        handle_sub_decision(cb, False)
    elif data.startswith('joinok:'):
        handle_join_decision(cb, True)
    elif data.startswith('joinno:'):
        handle_join_decision(cb, False)

def handle_private(msg):
    user = msg['from']
    text = msg.get('text', '')
    if text.startswith('/start'):
        buttons = [[{'text': '🙋 申请进群', 'callback_data': 'join_start'}]]
        if SUB_ENABLED:
            buttons[0].append({'text': '📮 我要投稿', 'callback_data': 'tougao_hint'})
            body = ('你好！我是本社区的管家机器人。\n\n'
                    '🙋 想进群：点下方「申请进群」，会给你一条专属链接；\n'
                    '📮 想投稿：不用点任何按钮，直接把照片或视频发给我就行。\n\n'
                    '投稿规则 👇\n' + SUB_RULES)
        else:
            body = '你好！我是本社区的管家机器人。点下方「申请进群」，会给你一条专属进群链接。'
        send(user['id'], body, reply_markup={'inline_keyboard': buttons})
        return
    if text.strip() in ('进群', '加入', '申请进群', '我想进群', 'join', '/join'):
        start_dm_join(user)
        return
    if not SUB_ENABLED:
        if _media_item(msg) is not None or text:
            send(user['id'], '本机器人未开启投稿功能。想进群请发 /start 点「申请进群」。')
        return
    if text and handle_desc_input(msg):
        return
    handle_media_entry(msg)

def main():
    global BOT_USERNAME
    r = api('getMe')
    BOT_USERNAME = r.get('result', {}).get('username', '')
    print('tg-group-guardian started as @' + (BOT_USERNAME or '?'), flush=True)
    offset = 0
    while True:
        r = api('getUpdates', offset=offset, timeout=(3 if burst_buf else 50), allowed_updates=['message', 'callback_query', 'chat_join_request'])
        for upd in r.get('result', []):
            offset = upd['update_id'] + 1
            try:
                if 'callback_query' in upd:
                    handle_callback(upd['callback_query'])
                elif 'chat_join_request' in upd:
                    handle_join_request(upd['chat_join_request'])
                elif 'message' in upd:
                    m = upd['message']
                    if m.get('chat', {}).get('type') == 'private':
                        handle_private(m)
                    elif m.get('chat', {}).get('type') in ('group', 'supergroup'):
                        handle_group_message(m)
            except Exception as e:
                print('handle err', e, flush=True)
        sweep_timeouts()
        sweep_albums()
        sweep_deletes()

if __name__ == '__main__':
    main()
