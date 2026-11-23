# QuizZone Rubika Bot - procedural quiz + leaderboard + admin + group activation
# Requires: requests
# Configuration via environment variables (Render):
# RUBIKA_BOT_TOKEN, OWNER_ID, ADMIN_PASSWORD (default intentionally not embedded)

import os, time, json, sqlite3, random, hashlib, logging, re
from datetime import datetime
import requests

TOKEN = os.getenv('RUBIKA_BOT_TOKEN', '').strip()
OWNER_ID = os.getenv('OWNER_ID', '').strip()
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', '').strip()
API_BASE = f'https://botapi.rubika.ir/v3/{TOKEN}'
DB_PATH = os.getenv('DB_PATH', 'quizzone.sqlite3')
POLL_DELAY = 2
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

if not TOKEN:
    raise SystemExit('Missing RUBIKA_BOT_TOKEN environment variable')
if not OWNER_ID:
    raise SystemExit('Missing OWNER_ID environment variable (owner bot user id)')
if not ADMIN_PASSWORD:
    raise SystemExit('Missing ADMIN_PASSWORD environment variable')

session = requests.Session()

# ---- Database ----
def db():
    c = sqlite3.connect(DB_PATH, timeout=20)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS users(user_id TEXT PRIMARY KEY, name TEXT, joined_at TEXT, score INTEGER DEFAULT 0, games INTEGER DEFAULT 0, correct INTEGER DEFAULT 0, banned INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS groups(chat_id TEXT PRIMARY KEY, title TEXT, active INTEGER DEFAULT 0, activated_at TEXT);
        CREATE TABLE IF NOT EXISTS requests(code TEXT PRIMARY KEY, chat_id TEXT, requester TEXT, title TEXT, created_at TEXT, status TEXT DEFAULT 'pending');
        CREATE TABLE IF NOT EXISTS seen(update_key TEXT PRIMARY KEY, created_at TEXT);
        CREATE TABLE IF NOT EXISTS used_questions(user_id TEXT, qhash TEXT, PRIMARY KEY(user_id,qhash));
        CREATE TABLE IF NOT EXISTS sessions(chat_id TEXT PRIMARY KEY, user_id TEXT, question TEXT, answer TEXT, options TEXT, qhash TEXT, expires INTEGER);
        CREATE TABLE IF NOT EXISTS admin_sessions(user_id TEXT PRIMARY KEY, state TEXT, expires INTEGER);
        CREATE TABLE IF NOT EXISTS pending_bans(user_id TEXT PRIMARY KEY, action TEXT);
        ''')

# ---- API ----
def api(method, payload=None):
    payload = payload or {}
    try:
        r = session.post(f'{API_BASE}/{method}', json=payload, timeout=25)
        r.raise_for_status()
        data = r.json()
        if data.get('status') not in (None, 'OK'):
            logging.warning('API %s returned: %s', method, data)
        return data
    except Exception as e:
        logging.error('API request failed (%s): %s', method, e)
        return {}

def send(chat_id, text):
    if not chat_id or not text:
        return
    api('sendMessage', {'chat_id': str(chat_id), 'text': str(text)})

def get_updates():
    return api('getUpdates', {})

# ---- Helpers ----
def getv(obj, *keys, default=None):
    for k in keys:
        if isinstance(obj, dict) and obj.get(k) is not None:
            return obj[k]
    return default

def parse_update(u):
    # Supports common Bot API update layouts. Adjust to the exact payload if your bot API differs.
    msg = getv(u, 'message', 'new_message', 'update', default={})
    if not isinstance(msg, dict): msg = {}
    chat = getv(msg, 'chat', default={})
    if not isinstance(chat, dict): chat = {}
    sender = getv(msg, 'sender', 'from', default={})
    if not isinstance(sender, dict): sender = {}
    chat_id = getv(msg, 'chat_id', 'object_guid', default=getv(chat, 'chat_id', 'id', 'guid'))
    user_id = getv(msg, 'user_id', default=getv(sender, 'user_id', 'id', 'guid'))
    text = getv(msg, 'text', 'body', default='')
    name = getv(sender, 'name', 'first_name', default=getv(msg, 'name', default='کاربر'))
    title = getv(chat, 'title', 'name', default=getv(msg, 'chat_title', default='گروه'))
    message_id = getv(msg, 'message_id', 'id', default=getv(u, 'update_id', 'id'))
    chat_type = getv(chat, 'type', default=getv(msg, 'chat_type', 'type', default=''))
    return str(chat_id or ''), str(user_id or ''), str(text or '').strip(), str(name or 'کاربر'), str(title or 'گروه'), str(message_id or ''), str(chat_type or '')

def is_group(chat_id, chat_type, title):
    # Heuristic; Rubika group identifiers are commonly distinct from user IDs.
    return chat_type.lower() in ('group', 'supergroup') or (chat_id and chat_id != title and chat_id != OWNER_ID and chat_id != '')

def mark_seen(key):
    if not key: return True
    with db() as c:
        try:
            c.execute('INSERT INTO seen VALUES (?,?)', (key, datetime.now().isoformat()))
            c.commit(); return True
        except sqlite3.IntegrityError:
            return False

def ensure_user(uid, name):
    if not uid: return
    with db() as c:
        c.execute('INSERT OR IGNORE INTO users(user_id,name,joined_at) VALUES(?,?,?)', (uid, name, datetime.now().isoformat()))
        c.execute('UPDATE users SET name=? WHERE user_id=?', (name, uid))
        c.commit()

def banned(uid):
    with db() as c:
        r = c.execute('SELECT banned FROM users WHERE user_id=?', (uid,)).fetchone()
    return bool(r and r['banned'])

# ---- Procedural question engine ----
def make_question():
    # Large randomized space: arithmetic, sequences, logic, and stable trivia.
    kind = random.choice(['add','sub','mul','division','square','sequence','odd','percent','trivia'])
    if kind == 'add':
        a,b = random.randint(10,9999), random.randint(10,9999); ans=a+b
        return f'{a} + {b} چند می‌شود؟', ans, [ans,ans+random.randint(1,15),ans-random.randint(1,15),ans+random.randint(20,40)]
    if kind == 'sub':
        a,b = random.randint(100,9999), random.randint(1,99); ans=a-b
        return f'{a} − {b} چند می‌شود؟', ans, [ans,ans+random.randint(1,20),ans-random.randint(1,20),ans+100]
    if kind == 'mul':
        a,b = random.randint(2,99), random.randint(2,99); ans=a*b
        return f'{a} × {b} چند می‌شود؟', ans, [ans,ans+a,ans-b,ans+10]
    if kind == 'division':
        b=random.randint(2,30); ans=random.randint(2,100); a=b*ans
        return f'{a} ÷ {b} چند می‌شود؟', ans, [ans,ans+1,ans-1,ans+b]
    if kind == 'square':
        a=random.randint(2,60); ans=a*a
        return f'مربع عدد {a} چیست؟', ans, [ans,ans+a,ans-2,ans+2*a]
    if kind == 'sequence':
        a=random.randint(1,40); d=random.randint(2,18); seq=[a+i*d for i in range(4)]; ans=seq[-1]+d
        return f'عدد بعدی این دنباله چیست؟\n{seq[0]}، {seq[1]}، {seq[2]}، {seq[3]}، ؟', ans, [ans,ans+d,ans-d,ans+2]
    if kind == 'odd':
        vals=[random.randint(1,50)*2-1 for _ in range(3)]; even=random.randint(1,50)*2; vals.append(even); random.shuffle(vals)
        ans=even
        return 'کدام عدد زوج است؟\n'+'، '.join(map(str,vals)), ans, vals
    if kind == 'percent':
        p=random.choice([5,10,15,20,25,30,40,50]); n=random.randint(2,100)*10; ans=n*p//100
        return f'{p} درصدِ {n} چند است؟', ans, [ans,ans+p,ans+10,ans*2]
    trivia=[('پایتخت ژاپن کدام شهر است؟','توکیو',['توکیو','کیوتو','اوساکا','ناگویا']),('بزرگ‌ترین سیاره منظومه شمسی کدام است؟','مشتری',['مشتری','زمین','مریخ','زحل']),('نماد شیمیایی آب چیست؟','H₂O',['H₂O','CO₂','O₂','NaCl']),('نویسنده شاهنامه کیست؟','فردوسی',['فردوسی','حافظ','سعدی','مولوی']),('یک هفته چند روز دارد؟','۷',['۵','۶','۷','۸']),('نور خورشید برای رسیدن به زمین تقریباً چند دقیقه زمان می‌برد؟','۸ دقیقه',['۱ دقیقه','۸ دقیقه','۳۰ دقیقه','۶۰ دقیقه']),('کدام جانور پستاندار است؟','دلفین',['دلفین','کوسه','ماهی تُن','اختاپوس']),('واحد اندازه‌گیری شدت جریان برق چیست؟','آمپر',['ولت','آمپر','وات','اهم']),('قاره‌ای که ایران در آن قرار دارد چیست؟','آسیا',['آسیا','اروپا','آفریقا','آمریکا']),('عدد پی تقریباً چند است؟','۳٫۱۴',['۲٫۱۴','۳٫۱۴','۴٫۱۳','۱٫۳۴'])]
    q,a,opts=random.choice(trivia); return q,a,opts

def unique_question(uid):
    # Avoid repeating generated question text for this user. Retry a number of times,
    # then allow a new variant if the procedural pool is exhausted for a particular set.
    for _ in range(60):
        q,a,opts=make_question(); h=hashlib.sha256(q.encode('utf-8')).hexdigest()
        with db() as c:
            exists=c.execute('SELECT 1 FROM used_questions WHERE user_id=? AND qhash=?',(uid,h)).fetchone()
            if not exists:
                c.execute('INSERT OR IGNORE INTO used_questions VALUES (?,?)',(uid,h)); c.commit()
                opts=list(dict.fromkeys([str(x) for x in opts]));
                while len(opts)<4: opts.append(str(a))
                random.shuffle(opts)
                return q,str(a),opts,h
    q,a,opts=make_question(); h=hashlib.sha256((q+str(time.time_ns())).encode()).hexdigest()
    with db() as c: c.execute('INSERT OR IGNORE INTO used_questions VALUES (?,?)',(uid,h)); c.commit()
    opts=list(dict.fromkeys([str(x) for x in opts])); random.shuffle(opts)
    return q,str(a),opts,h

def start_game(chat_id, uid):
    q,a,opts,h=unique_question(uid)
    with db() as c:
        c.execute('INSERT OR REPLACE INTO sessions VALUES(?,?,?,?,?,?,?)',(chat_id,uid,q,a,json.dumps(opts,ensure_ascii=False),h,int(time.time())+90)); c.commit()
    send(chat_id, '🎯 سوال جدید\n\n'+q+'\n\n'+ '\n'.join(f'{i+1}) {o}' for i,o in enumerate(opts))+'\n\nشماره گزینه را بفرست (۱ تا ۴). برای سؤال بعد /quiz را بزن.')

def answer_game(chat_id, uid, text):
    with db() as c: s=c.execute('SELECT * FROM sessions WHERE chat_id=?',(chat_id,)).fetchone()
    if not s or s['user_id'] != uid or s['expires'] < int(time.time()): return False
    choice=re.sub(r'[^0-9]', '', text)
    if choice not in ('1','2','3','4'): return False
    opts=json.loads(s['options']); chosen=opts[int(choice)-1]
    correct=chosen==s['answer']
    with db() as c:
        c.execute('UPDATE users SET games=games+1, correct=correct+?, score=score+? WHERE user_id=?',(int(correct),10 if correct else 0,uid))
        c.execute('DELETE FROM sessions WHERE chat_id=?',(chat_id,)); c.commit()
    send(chat_id, ('✅ درست بود! +۱۰ امتیاز\n' if correct else f'❌ پاسخ درست: {s["answer"]}\n')+'برای ادامه /quiz را بفرست.')
    return True

# ---- Leaderboard / profile ----
def leaderboard(chat_id):
    with db() as c: rows=c.execute('SELECT name,score,games,correct FROM users WHERE banned=0 ORDER BY score DESC,correct DESC LIMIT 10').fetchall()
    if not rows: return send(chat_id,'هنوز امتیازی ثبت نشده!')
    out=['🏆 جدول امتیازات QuizZone','']
    for i,r in enumerate(rows,1): out.append(f'{i}. {r["name"]} — {r["score"]} امتیاز | {r["correct"]} پاسخ درست')
    send(chat_id,'\n'.join(out))

def profile(chat_id, uid):
    with db() as c: r=c.execute('SELECT name,score,games,correct FROM users WHERE user_id=?',(uid,)).fetchone()
    if not r: return send(chat_id,'پروفایل پیدا نشد.')
    send(chat_id,f'👤 {r["name"]}\n⭐ امتیاز: {r["score"]}\n🎮 بازی: {r["games"]}\n✅ پاسخ درست: {r["correct"]}')

# ---- Admin ----
def admin_prompt(uid, chat_id):
    if uid != OWNER_ID:
        send(chat_id,'⛔ دسترسی فقط برای مالک ربات است.'); return
    with db() as c: c.execute('INSERT OR REPLACE INTO admin_sessions VALUES(?,?,?)',(uid,'password',int(time.time())+180)); c.commit()
    send(chat_id,'🔐 رمز پنل مدیریت را در همین گفت‌وگوی خصوصی ارسال کن. (۳ دقیقه فرصت داری)')

def admin_menu(chat_id):
    send(chat_id,'🛠 پنل مدیریت\n\n/users — کاربران\n/stats — آمار\n/requests — درخواست گروه‌ها\n/groups — گروه‌های فعال\n/ban USER_ID — مسدود\n/unban USER_ID — رفع مسدودی\n/approve CODE — تأیید درخواست\n/reject CODE — رد درخواست\n/logout — خروج از پنل')

def admin_auth(uid, chat_id, text):
    with db() as c: s=c.execute('SELECT * FROM admin_sessions WHERE user_id=?',(uid,)).fetchone()
    if not s: return False
    if s['expires'] < int(time.time()):
        with db() as c: c.execute('DELETE FROM admin_sessions WHERE user_id=?',(uid,)); c.commit()
        send(chat_id,'⏰ نشست پنل منقضی شد. دوباره /mohsenbot را بزن.'); return True
    if s['state']=='password':
        if text == ADMIN_PASSWORD:
            with db() as c: c.execute('UPDATE admin_sessions SET state="authorized",expires=? WHERE user_id=?',(int(time.time())+1800,uid)); c.commit()
            send(chat_id,'✅ ورود موفق.'); admin_menu(chat_id)
        else:
            with db() as c: c.execute('DELETE FROM admin_sessions WHERE user_id=?',(uid,)); c.commit()
            send(chat_id,'❌ رمز اشتباه است. برای ورود دوباره /mohsenbot را بزن.')
        return True
    return s['state']=='authorized'

def is_admin(uid):
    with db() as c: s=c.execute('SELECT state,expires FROM admin_sessions WHERE user_id=?',(uid,)).fetchone()
    return bool(s and s['state']=='authorized' and s['expires']>=int(time.time()))

def handle_admin(uid, chat_id, text):
    if not is_admin(uid): return False
    if text == '/logout':
        with db() as c: c.execute('DELETE FROM admin_sessions WHERE user_id=?',(uid,)); c.commit()
        send(chat_id,'از پنل خارج شدی.'); return True
    if text == '/users':
        with db() as c: rows=c.execute('SELECT user_id,name,score,games,banned FROM users ORDER BY joined_at DESC LIMIT 30').fetchall()
        if not rows: send(chat_id,'کاربری ثبت نشده.'); return True
        send(chat_id,'👥 کاربران (۳۰ مورد اخیر):\n'+'\n'.join(f'{r["name"]} | ID: {r["user_id"]} | امتیاز {r["score"]} | بازی {r["games"]} | '+('🚫' if r['banned'] else 'فعال') for r in rows)); return True
    if text == '/stats':
        with db() as c:
            n=c.execute('SELECT COUNT(*) FROM users').fetchone()[0]; g=c.execute('SELECT COUNT(*) FROM groups WHERE active=1').fetchone()[0]; p=c.execute("SELECT COUNT(*) FROM requests WHERE status='pending'").fetchone()[0]; score=c.execute('SELECT COALESCE(SUM(score),0) FROM users').fetchone()[0]
        send(chat_id,f'📊 آمار\nکاربران: {n}\nگروه‌های فعال: {g}\nدرخواست‌های منتظر: {p}\nمجموع امتیازات: {score}'); return True
    if text == '/requests':
        with db() as c: rows=c.execute("SELECT code,chat_id,requester,title,created_at FROM requests WHERE status='pending' ORDER BY created_at DESC").fetchall()
        send(chat_id,'📨 درخواست‌های منتظر:\n'+('\n'.join(f'کد {r["code"]} | {r["title"]} | گروه {r["chat_id"]} | درخواست‌کننده {r["requester"]}' for r in rows) if rows else 'درخواستی نیست.')); return True
    if text == '/groups':
        with db() as c: rows=c.execute('SELECT chat_id,title,activated_at FROM groups WHERE active=1').fetchall()
        send(chat_id,'🟢 گروه‌های فعال:\n'+('\n'.join(f'{r["title"]} | {r["chat_id"]} | {r["activated_at"]}' for r in rows) if rows else 'گروه فعالی نیست.')); return True
    m=re.match(r'^/(ban|unban)\s+(\S+)$',text)
    if m:
        act, target=m.groups()
        with db() as c: c.execute('UPDATE users SET banned=? WHERE user_id=?',(1 if act=='ban' else 0,target)); c.commit()
        send(chat_id,'انجام شد (اگر شناسه معتبر باشد).'); return True
    m=re.match(r'^/(approve|reject)\s+(\S+)$',text)
    if m:
        act,code=m.groups()
        with db() as c: r=c.execute('SELECT * FROM requests WHERE code=? AND status="pending"',(code,)).fetchone()
        if not r: send(chat_id,'درخواست با این کد پیدا نشد یا قبلاً بررسی شده.'); return True
        if act=='approve':
            with db() as c:
                c.execute('UPDATE requests SET status="approved" WHERE code=?',(code,)); c.execute('INSERT OR REPLACE INTO groups(chat_id,title,active,activated_at) VALUES(?,?,1,?)',(r['chat_id'],r['title'],datetime.now().isoformat())); c.commit()
            send(r['chat_id'],f'🎉 درخواست فعال‌سازی تأیید شد! کد فعال‌سازی شما: {code}\nربات در این گروه فعال است.'); send(chat_id,'✅ گروه تأیید و فعال شد.')
        else:
            with db() as c: c.execute('UPDATE requests SET status="rejected" WHERE code=?',(code,)); c.commit()
            send(r['chat_id'],'❌ درخواست فعال‌سازی گروه رد شد. در صورت نیاز درخواست جدید ارسال کنید.'); send(chat_id,'درخواست رد شد.')
        return True
    if text.startswith('/'):
        send(chat_id,'دستور نامعتبر. /menu را بزن.'); return True
    return True

# ---- Group activation ----
def request_activation(chat_id, uid, title):
    code='QZ-'+''.join(random.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(6))
    with db() as c:
        c.execute('INSERT INTO requests(code,chat_id,requester,title,created_at,status) VALUES(?,?,?,?,?,?)',(code,chat_id,uid,title,datetime.now().isoformat(),'pending')); c.commit()
    send(chat_id,'📨 درخواست فعال‌سازی ثبت شد. پس از بررسی مالک، نتیجه در همین گروه اعلام می‌شود. فعلاً بازی در گروه غیرفعال است.')
    send(OWNER_ID,f'📨 درخواست فعال‌سازی گروه\nنام: {title}\nشناسه گروه: {chat_id}\nدرخواست‌کننده: {uid}\nکد: {code}\n\nبرای بررسی، پنل را باز کن: /mohsenbot سپس /requests و بعد /approve {code} یا /reject {code}')

# ---- Main routing ----
def handle(chat_id, uid, text, name, title, chat_type):
    if not chat_id or not uid or not text: return
    ensure_user(uid,name)
    if banned(uid):
        send(chat_id,'⛔ دسترسی شما به ربات محدود شده است.'); return

    # Admin flow should only run in private chat with owner. Avoid asking password in group.
    private = (chat_id == uid) or chat_type.lower() in ('private','user')
    if text == '/mohsenbot':
        if not private: send(chat_id,'برای امنیت، پنل مدیریت را فقط در گفت‌وگوی خصوصی با ربات باز کن.'); return
        admin_prompt(uid,chat_id); return
    if private and uid==OWNER_ID:
        if admin_auth(uid,chat_id,text):
            if text != ADMIN_PASSWORD: handle_admin(uid,chat_id,text)
            return
        if handle_admin(uid,chat_id,text): return

    if text in ('/start','شروع'):
        send(chat_id,'سلام 👋 به QuizZone خوش آمدی!\n\n/quiz — شروع سؤال\n/leaderboard — جدول امتیازات\n/profile — پروفایل\n/help — راهنما\n\nبرای فعال‌سازی در گروه، در گروه /activate را بفرست و منتظر تأیید مالک بمان.')
        return
    if text in ('/help','/menu','راهنما'):
        send(chat_id,'🎮 راهنما\n/quiz — سؤال جدید\n/leaderboard — رتبه‌بندی\n/profile — آمار شما\n/activate — درخواست فعال‌سازی گروه\n\nهر پاسخ درست ۱۰ امتیاز دارد.'); return
    if text == '/leaderboard': leaderboard(chat_id); return
    if text == '/profile': profile(chat_id,uid); return
    if text == '/activate':
        if private: send(chat_id,'این دستور را داخل گروهی که می‌خواهی فعال شود ارسال کن.'); return
        with db() as c: active=c.execute('SELECT active FROM groups WHERE chat_id=?',(chat_id,)).fetchone()
        if active and active['active']: send(chat_id,'این گروه از قبل فعال است.'); return
        request_activation(chat_id,uid,title); return

    # In groups, no quiz responses until approved.
    if not private:
        with db() as c: active=c.execute('SELECT active FROM groups WHERE chat_id=?',(chat_id,)).fetchone()
        if not active or not active['active']:
            if text in ('/quiz','/leaderboard','/profile'):
                send(chat_id,'🔒 ربات هنوز در این گروه فعال نشده. برای درخواست، /activate را ارسال کنید.')
            return
    if text == '/quiz': start_game(chat_id,uid); return
    if answer_game(chat_id,uid,text): return

# ---- Polling ----
def extract_updates(resp):
    data=resp.get('data',{}) if isinstance(resp,dict) else {}
    if isinstance(data,list): return data
    for k in ('updates','messages','update_list'):
        if isinstance(data,dict) and isinstance(data.get(k),list): return data[k]
    if isinstance(resp,dict):
        for k in ('updates','messages','update_list'):
            if isinstance(resp.get(k),list): return resp[k]
    return []

def main():
    init_db(); logging.info('QuizZone bot started. Keep only one running instance.')
    while True:
        try:
            resp=get_updates()
            updates=extract_updates(resp)
            for u in updates:
                if not isinstance(u,dict): continue
                chat_id,uid,text,name,title,msg_id,chat_type=parse_update(u)
                key=msg_id or getv(u,'update_id','id',default='')
                if key and not mark_seen(str(key)): continue
                if chat_id and uid and text:
                    handle(chat_id,uid,text,name,title,chat_type)
            time.sleep(POLL_DELAY)
        except KeyboardInterrupt:
            break
        except Exception:
            logging.exception('Polling error'); time.sleep(5)

if __name__=='__main__': main()


