# QuizZone Advanced - Rubika Bot API v3
# Python 3.10+
# Environment: RUBIKA_BOT_TOKEN, ADMIN_PASSWORD (required), DB_PATH (optional)
# Password-only first admin enrollment: the first successful private password login
# permanently binds the admin account in SQLite. This avoids a public OWNER_ID.

import os, time, json, sqlite3, random, hashlib, logging, re, secrets
from datetime import datetime, date
import requests
from flask import Flask, request, jsonify

TOKEN = os.getenv('RUBIKA_BOT_TOKEN', '').strip()
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', '').strip()
DB_PATH = os.getenv('DB_PATH', 'quizzone.sqlite3')
API_BASE = f'https://botapi.rubika.ir/v3/{TOKEN}'
POLL_DELAY = 2
SESSION_SECONDS = 120
ADMIN_SESSION_SECONDS = 1800
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
if not TOKEN: raise SystemExit('Missing RUBIKA_BOT_TOKEN')
if not ADMIN_PASSWORD: raise SystemExit('Missing ADMIN_PASSWORD')
http = requests.Session()

# ---- DB ----
def db():
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS users(
          user_id TEXT PRIMARY KEY, name TEXT, joined_at TEXT, last_seen TEXT,
          score INTEGER DEFAULT 0, games INTEGER DEFAULT 0, correct INTEGER DEFAULT 0,
          streak INTEGER DEFAULT 0, best_streak INTEGER DEFAULT 0, banned INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS groups(chat_id TEXT PRIMARY KEY,title TEXT,active INTEGER DEFAULT 0,activated_at TEXT);
        CREATE TABLE IF NOT EXISTS requests(code TEXT PRIMARY KEY,chat_id TEXT,requester TEXT,title TEXT,created_at TEXT,status TEXT DEFAULT 'pending');
        CREATE TABLE IF NOT EXISTS seen(message_id TEXT PRIMARY KEY,created_at TEXT);
        CREATE TABLE IF NOT EXISTS used_questions(user_id TEXT,qhash TEXT,PRIMARY KEY(user_id,qhash));
        CREATE TABLE IF NOT EXISTS games(chat_id TEXT PRIMARY KEY,user_id TEXT,question TEXT,answer TEXT,options TEXT,qhash TEXT,expires INTEGER,category TEXT);
        CREATE TABLE IF NOT EXISTS admin_sessions(user_id TEXT PRIMARY KEY,state TEXT,expires INTEGER);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
        CREATE TABLE IF NOT EXISTS daily(user_id TEXT,day TEXT,claimed INTEGER DEFAULT 0,PRIMARY KEY(user_id,day));
        CREATE TABLE IF NOT EXISTS achievements(user_id TEXT,achievement TEXT,earned_at TEXT,PRIMARY KEY(user_id,achievement));
        ''')
        # Migrate old sessions table if the earlier bot used it.
        try: c.execute('ALTER TABLE users ADD COLUMN last_seen TEXT')
        except sqlite3.OperationalError: pass
        try: c.execute('ALTER TABLE users ADD COLUMN streak INTEGER DEFAULT 0')
        except sqlite3.OperationalError: pass
        try: c.execute('ALTER TABLE users ADD COLUMN best_streak INTEGER DEFAULT 0')
        except sqlite3.OperationalError: pass
        try: c.execute('ALTER TABLE users ADD COLUMN banned INTEGER DEFAULT 0')
        except sqlite3.OperationalError: pass
        try: c.execute('ALTER TABLE games ADD COLUMN category TEXT')
        except sqlite3.OperationalError: pass

# ---- Rubika API ----
def api(method, payload=None):
    try:
        r = http.post(f'{API_BASE}/{method}', json=payload or {}, timeout=25)
        r.raise_for_status()
        body = r.json()
        if isinstance(body, dict) and body.get('status') not in (None, 'OK'):
            logging.warning('API %s: %s', method, body)
        return body if isinstance(body, dict) else {}
    except Exception as exc:
        logging.error('API %s failed: %s', method, exc)
        return {}

def data_of(resp):
    return resp.get('data') if isinstance(resp, dict) and isinstance(resp.get('data'), dict) else resp

def send(chat_id, text, inline_keypad=None):
    if chat_id and text:
        payload = {'chat_id': str(chat_id), 'text': str(text)[:4000]}
        if inline_keypad:
            payload['inline_keypad'] = inline_keypad
        api('sendMessage', payload)

def glass_button(text, button_id):
    return {'type': 'Simple', 'button_text': text, 'id': button_id}

def inline_keyboard(rows):
    return {'rows': [{'buttons': [glass_button(t, bid) for t, bid in row]} for row in rows]}

def get_updates(offset):
    payload = {'limit': 100}
    if offset: payload['offset_id'] = str(offset)
    return data_of(api('getUpdates', payload))

# ---- Parsing / utilities ----
def getv(d, *keys, default=None):
    if not isinstance(d, dict): return default
    for k in keys:
        if d.get(k) is not None: return d[k]
    return default

def extract_sender_id(msg):
    s = getv(msg, 'sender_id', 'sender', 'from', default={})
    if isinstance(s, dict): return str(getv(s, 'user_id', 'id', 'guid', default='') or '')
    return str(s or getv(msg, 'user_id', default='') or '')

def parse_update(u):
    msg = getv(u, 'new_message', 'message', default={})
    if not isinstance(msg, dict): msg = {}
    chat_id = str(getv(u, 'chat_id', default=getv(msg, 'chat_id', 'object_guid', default='')) or '')
    uid = extract_sender_id(msg)
    text = str(getv(msg, 'text', 'body', default='') or '').strip()
    msgid = str(getv(msg, 'message_id', 'id', default=getv(u, 'update_id', 'id', default='')) or '')
    chat = getv(u, 'chat', default=getv(msg, 'chat', default={}))
    ctype = str(getv(chat, 'type', default=getv(u, 'chat_type', default='')) or '').lower()
    title = str(getv(chat, 'title', 'name', default=getv(u, 'chat_title', default='گروه')) or 'گروه')
    name = str(getv(msg, 'sender_name', 'name', default=getv(getv(msg,'sender',default={}), 'name', default='کاربر')) or 'کاربر')
    sender_type = str(getv(msg, 'sender_type', default='') or '').lower()
    return chat_id, uid, text, name, title, msgid, ctype, sender_type

def private_chat(chat_id, uid, ctype):
    return ctype in ('private','user') or (bool(uid) and chat_id == uid)

def mark_seen(mid):
    if not mid: return True
    with db() as c:
        try: c.execute('INSERT INTO seen VALUES (?,?)', (mid, datetime.now().isoformat())); c.commit(); return True
        except sqlite3.IntegrityError: return False

def ensure_user(uid, name):
    if not uid: return
    now = datetime.now().isoformat()
    with db() as c:
        c.execute('INSERT OR IGNORE INTO users(user_id,name,joined_at,last_seen) VALUES(?,?,?,?)',(uid,name,now,now))
        c.execute('UPDATE users SET name=?,last_seen=? WHERE user_id=?',(name,now,uid)); c.commit()

def banned(uid):
    with db() as c:
        r = c.execute('SELECT banned FROM users WHERE user_id=?',(uid,)).fetchone()
    return bool(r and r['banned'])

def admin_id():
    with db() as c:
        r=c.execute("SELECT value FROM settings WHERE key='admin_user_id'").fetchone()
    return r['value'] if r else ''

def set_admin_id(uid):
    with db() as c: c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('admin_user_id',?)",(uid,)); c.commit()

# ---- Question engine (procedural: effectively endless variants) ----
def make_options(answer, distractors):
    vals=[]
    for v in [answer]+list(distractors):
        s=str(v)
        if s not in vals: vals.append(s)
    while len(vals)<4:
        if isinstance(answer,int): vals.append(str(answer+random.randint(1,30)))
        else: vals.append('گزینه دیگر')
    vals=vals[:4]; random.shuffle(vals)
    return vals

def generate_question():
    kind=random.choice(['add','sub','mul','division','square','sequence','odd','percent','fraction','unit','trivia'])
    if kind=='add':
        a,b=random.randint(11,99999),random.randint(11,99999); ans=a+b
        return f'{a} + {b} = ؟',ans,make_options(ans,[ans+random.randint(2,90),ans-random.randint(2,90),ans+100]),'ریاضی'
    if kind=='sub':
        a,b=random.randint(100,99999),random.randint(1,999); ans=a-b
        return f'{a} − {b} = ؟',ans,make_options(ans,[ans+random.randint(2,60),ans-random.randint(2,60),ans+100]),'ریاضی'
    if kind=='mul':
        a,b=random.randint(2,199),random.randint(2,99); ans=a*b
        return f'{a} × {b} = ؟',ans,make_options(ans,[ans+a,ans-b,ans+11]),'ریاضی'
    if kind=='division':
        b=random.randint(2,40); ans=random.randint(2,120); a=b*ans
        return f'{a} ÷ {b} = ؟',ans,make_options(ans,[ans+1,ans-1,ans+b]),'ریاضی'
    if kind=='square':
        a=random.randint(2,120); ans=a*a
        return f'مربع {a} چند است؟',ans,make_options(ans,[ans+a,ans-2,ans+2*a]),'ریاضی'
    if kind=='sequence':
        a=random.randint(-30,100); d=random.choice([i for i in range(-20,21) if i]); seq=[a+i*d for i in range(4)]; ans=seq[-1]+d
        return 'عدد بعدی دنباله چیست؟\n'+ '، '.join(map(str,seq))+'، ؟',ans,make_options(ans,[ans+d,ans-d,ans+random.randint(3,20)]),'هوش'
    if kind=='odd':
        vals=[random.randrange(1,100)*2-1 for _ in range(3)]; even=random.randrange(1,100)*2; vals.append(even); random.shuffle(vals)
        return 'کدام عدد زوج است؟\n'+'، '.join(map(str,vals)),even,make_options(even,vals),'هوش'
    if kind=='percent':
        p=random.choice([5,10,15,20,25,30,40,50,60,75]); n=random.randint(2,200)*10; ans=n*p//100
        return f'{p} درصدِ {n} چند می‌شود؟',ans,make_options(ans,[ans+p,ans+10,ans*2]),'ریاضی'
    if kind=='fraction':
        den=random.choice([2,3,4,5,6,8,10]); num=random.randint(1,den-1); mult=random.randint(2,50); ans=num*mult
        total=den*mult
        return f'{num}/{den} از {total} برابر چند است؟',ans,make_options(ans,[ans+mult,ans-num,ans+den]),'ریاضی'
    if kind=='unit':
        n=random.randint(1,300); kind2=random.choice(['m','kg','min'])
        if kind2=='m': ans=n*100; return f'{n} متر چند سانتی‌متر است؟',ans,make_options(ans,[n*10,n*1000,n+100]),'دانستنی'
        if kind2=='kg': ans=n*1000; return f'{n} کیلوگرم چند گرم است؟',ans,make_options(ans,[n*100,n*10,n+1000]),'دانستنی'
        ans=n*60; return f'{n} دقیقه چند ثانیه است؟',ans,make_options(ans,[n*30,n*100,n+60]),'دانستنی'
    trivia=[
      ('پایتخت ژاپن چیست؟','توکیو',['کیوتو','اوساکا','ناگویا'],'جغرافیا'),('بزرگ‌ترین سیاره منظومه شمسی کدام است؟','مشتری',['زمین','مریخ','زحل'],'علوم'),
      ('فرمول شیمیایی آب چیست؟','H₂O',['CO₂','O₂','NaCl'],'علوم'),('شاهنامه را چه کسی سروده است؟','فردوسی',['حافظ','سعدی','مولوی'],'ادبیات'),
      ('یک هفته چند روز دارد؟','۷',['۵','۶','۸'],'دانستنی'),('نور خورشید تقریباً چند دقیقه تا زمین می‌رسد؟','۸ دقیقه',['۱ دقیقه','۳۰ دقیقه','۶۰ دقیقه'],'علوم'),
      ('کدام جانور پستاندار است؟','دلفین',['کوسه','اختاپوس','ماهی تن'],'علوم'),('واحد جریان الکتریکی چیست؟','آمپر',['ولت','وات','اهم'],'علوم'),
      ('ایران در کدام قاره قرار دارد؟','آسیا',['اروپا','آفریقا','آمریکا'],'جغرافیا'),('عدد پی تقریباً چند است؟','۳٫۱۴',['۲٫۱۴','۴٫۱۳','۱٫۳۴'],'ریاضی'),
      ('بزرگ‌ترین اقیانوس جهان کدام است؟','آرام',['اطلس','هند','منجمد شمالی'],'جغرافیا'),('کدام گاز برای تنفس انسان ضروری است؟','اکسیژن',['هیدروژن','نیتروژن','هلیوم'],'علوم'),
      ('پایتخت ایتالیا کدام است؟','رم',['میلان','ونیز','ناپل'],'جغرافیا'),('سرعت نور در خلأ تقریباً چند است؟','۳۰۰ هزار کیلومتر بر ثانیه',['۳۰ هزار','۱۵۰ هزار','۵۰۰ هزار'],'علوم'),
      ('کدام سیاره به حلقه‌هایش مشهور است؟','زحل',['مریخ','عطارد','زمین'],'علوم'),('جمع اضلاع یک مثلث چند درجه است؟','۱۸۰ درجه',['۹۰ درجه','۲۷۰ درجه','۳۶۰ درجه'],'ریاضی'),
      ('زبان رسمی کشور برزیل چیست؟','پرتغالی',['اسپانیایی','فرانسوی','انگلیسی'],'جغرافیا'),('کدام یک فلز است؟','آهن',['گوگرد','اکسیژن','کربن'],'علوم'),
      ('پایتخت کانادا چیست؟','اتاوا',['تورنتو','ونکوور','مونترال'],'جغرافیا'),('کدام شاعر به غزل‌هایش معروف است؟','حافظ',['فردوسی','خیام','نظامی'],'ادبیات')]
    q,a,opts,cat=random.choice(trivia); return q,a,make_options(a,opts),cat

def unique_question(uid):
    for _ in range(80):
        q,a,opts,cat=generate_question(); h=hashlib.sha256(q.encode()).hexdigest()
        with db() as c:
            if c.execute('SELECT 1 FROM used_questions WHERE user_id=? AND qhash=?',(uid,h)).fetchone(): continue
            c.execute('INSERT OR IGNORE INTO used_questions VALUES(?,?)',(uid,h)); c.commit()
        return q,str(a),[str(x) for x in opts],h,cat
    # Fallback: very large generated numeric variant, not a hard end to the game.
    a,b=random.randint(100000,999999),random.randint(100000,999999); ans=a+b; q=f'{a} + {b} = ؟'; h=hashlib.sha256((q+str(time.time_ns())).encode()).hexdigest()
    with db() as c: c.execute('INSERT OR IGNORE INTO used_questions VALUES(?,?)',(uid,h)); c.commit()
    return q,str(ans),make_options(ans,[ans+17,ans-21,ans+99]),h,'ریاضی'

def start_game(chat_id, uid):
    q,a,opts,h,cat=unique_question(uid)
    with db() as c:
        c.execute('INSERT OR REPLACE INTO games(chat_id,user_id,question,answer,options,qhash,expires,category) VALUES(?,?,?,?,?,?,?,?)',(chat_id,uid,q,a,json.dumps(opts,ensure_ascii=False),h,int(time.time())+SESSION_SECONDS,cat)); c.commit()
    send(chat_id,f'🎯 چالش جدید | {cat}\n\n{q}\n\n'+'\n'.join(f'{i+1}) {o}' for i,o in enumerate(opts))+'\n\nشماره گزینه را بفرست (۱ تا ۴). /quiz برای سؤال بعدی')

def normalize_digits(s):
    return s.translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩','01234567890123456789'))

def answer_game(chat_id, uid, text):
    with db() as c: g=c.execute('SELECT * FROM games WHERE chat_id=?',(chat_id,)).fetchone()
    if not g or g['user_id']!=uid: return False
    if g['expires']<int(time.time()):
        with db() as c: c.execute('DELETE FROM games WHERE chat_id=?',(chat_id,)); c.commit()
        send(chat_id,'⏰ زمان این سؤال تمام شد. برای سؤال جدید /quiz را بزن.'); return True
    choice=normalize_digits(text).strip()
    if choice not in ('1','2','3','4'): return False
    opts=json.loads(g['options']); selected=str(opts[int(choice)-1]); correct=selected==str(g['answer'])
    with db() as c:
        if correct:
            c.execute('UPDATE users SET games=games+1,correct=correct+1,score=score+10,streak=streak+1 WHERE user_id=?',(uid,))
            c.execute('UPDATE users SET best_streak=MAX(best_streak,streak) WHERE user_id=?',(uid,))
            row=c.execute('SELECT streak,score,games,correct FROM users WHERE user_id=?',(uid,)).fetchone()
            bonus=5 if row['streak']%5==0 else 0
            if bonus: c.execute('UPDATE users SET score=score+? WHERE user_id=?',(bonus,uid))
        else:
            c.execute('UPDATE users SET games=games+1,streak=0 WHERE user_id=?',(uid,))
            row=c.execute('SELECT streak,score,games,correct FROM users WHERE user_id=?',(uid,)).fetchone(); bonus=0
        c.execute('DELETE FROM games WHERE chat_id=?',(chat_id,)); c.commit()
    if correct:
        msg=f'✅ پاسخ درست! +۱۰ امتیاز\n🔥 پشت‌سرهم: {row["streak"]}' + (f'\n🎁 جایزه زنجیره: +{bonus}' if bonus else '')
    else: msg=f'❌ پاسخ درست: {g["answer"]}\nزنجیره پاسخ‌ها از نو شروع شد.'
    send(chat_id,msg+'\n\nبرای ادامه /quiz')
    award_achievements(uid)
    return True

# ---- Progress / rewards ----
def award_achievements(uid):
    with db() as c:
        r=c.execute('SELECT score,games,correct,best_streak FROM users WHERE user_id=?',(uid,)).fetchone()
        if not r: return
        checks=[('first_game',r['games']>=1,'🎮 اولین بازی'),('ten_correct',r['correct']>=10,'🧠 ده پاسخ درست'),('streak5',r['best_streak']>=5,'🔥 زنجیره ۵'),('score100',r['score']>=100,'⭐ صد امتیاز')]
        for key,ok,label in checks:
            if ok:
                cur=c.execute('INSERT OR IGNORE INTO achievements VALUES(?,?,?)',(uid,key,datetime.now().isoformat()))
                if cur.rowcount: send(uid,'🏅 دستاورد جدید: '+label)
        c.commit()

def daily_reward(chat_id,uid):
    today=date.today().isoformat()
    with db() as c:
        if c.execute('SELECT 1 FROM daily WHERE user_id=? AND day=?',(uid,today)).fetchone(): send(chat_id,'🎁 جایزه روزانه امروز را قبلاً دریافت کردی. فردا دوباره سر بزن!'); return
        c.execute('INSERT INTO daily VALUES(?,?,1)',(uid,today)); c.execute('UPDATE users SET score=score+15 WHERE user_id=?',(uid,)); c.commit()
    send(chat_id,'🎁 جایزه روزانه دریافت شد: +۱۵ امتیاز!')

def leaderboard(chat_id):
    with db() as c: rows=c.execute('SELECT name,score,correct,games,best_streak FROM users WHERE banned=0 ORDER BY score DESC,correct DESC LIMIT 10').fetchall()
    if not rows: send(chat_id,'هنوز امتیازی ثبت نشده. اولین بازی را انجام بده!'); return
    out=['🏆 جدول امتیازات QuizZone','']
    for i,r in enumerate(rows,1): out.append(f'{i}. {r["name"]} — ⭐ {r["score"]} | درست {r["correct"]} | بازی {r["games"]}')
    send(chat_id,'\n'.join(out))

def profile(chat_id,uid):
    with db() as c:
        r=c.execute('SELECT name,score,games,correct,streak,best_streak FROM users WHERE user_id=?',(uid,)).fetchone()
        rank=c.execute('SELECT COUNT(*)+1 FROM users WHERE score>(SELECT score FROM users WHERE user_id=?)',(uid,)).fetchone()[0]
        ach=c.execute('SELECT achievement FROM achievements WHERE user_id=?',(uid,)).fetchall()
    if not r: send(chat_id,'پروفایل پیدا نشد.'); return
    send(chat_id,f'👤 {r["name"]}\n🏆 رتبه: {rank}\n⭐ امتیاز: {r["score"]}\n🎮 بازی‌ها: {r["games"]}\n✅ پاسخ درست: {r["correct"]}\n🔥 زنجیره فعلی: {r["streak"]}\n🏅 بهترین زنجیره: {r["best_streak"]}\n🎖 دستاوردها: {len(ach)}')

# ---- Admin ----
def admin_menu(chat_id):
    keyboard = inline_keyboard([
        [('📊 آمار کلی', 'adm:stats'), ('👥 کاربران', 'adm:users')],
        [('📨 درخواست‌ها', 'adm:requests'), ('👨‍👩‍👧 گروه‌ها', 'adm:groups')],
        [('🚪 خروج از پنل', 'adm:logout')]
    ])
    send(chat_id, '🛡 پنل مدیریت QuizZone\nیکی از بخش‌های زیر را انتخاب کن:', keyboard)

def admin_login(uid, chat_id):
    bound = admin_id()
    if bound and bound != uid:
        send(chat_id, '⛔ پنل قبلاً به حساب مدیر دیگری متصل شده است.')
        return
    if not bound:
        set_admin_id(uid)
    with db() as c:
        c.execute('INSERT OR REPLACE INTO admin_sessions VALUES(?,?,?)',
                  (uid, 'authorized', int(time.time()) + ADMIN_SESSION_SECONDS))
        c.commit()
    send(chat_id, '✅ رمز صحیح است؛ مستقیم وارد پنل مدیریت شدی.')
    admin_menu(chat_id)

def admin_auth(uid,chat_id,text):
    # The password itself is the login trigger; no /mohsenbot command is required.
    if text == ADMIN_PASSWORD:
        admin_login(uid, chat_id)
        return True
    with db() as c:
        s=c.execute('SELECT * FROM admin_sessions WHERE user_id=?',(uid,)).fetchone()
    if not s: return False
    if s['expires'] < int(time.time()):
        with db() as c: c.execute('DELETE FROM admin_sessions WHERE user_id=?',(uid,)); c.commit()
        send(chat_id,'⌛ نشست پنل منقضی شده؛ برای ورود دوباره رمز را ارسال کن.')
        return True
    return s['state'] == 'authorized'

def is_admin(uid):
    with db() as c: s=c.execute('SELECT state,expires FROM admin_sessions WHERE user_id=?',(uid,)).fetchone()
    return bool(s and s['state']=='authorized' and s['expires']>=int(time.time()) and admin_id()==uid)

def handle_admin(uid,chat_id,text,button_id=None):
    if not is_admin(uid): return False
    if button_id:
        action = button_id.removeprefix('adm:')
        if action == 'logout':
            with db() as c: c.execute('DELETE FROM admin_sessions WHERE user_id=?',(uid,)); c.commit()
            send(chat_id, 'از پنل خارج شدی.'); return True
        if action == 'stats': text='/stats'
        elif action == 'users': text='/users'
        elif action == 'requests': text='/requests'
        elif action == 'groups': text='/groups'
        elif action.startswith('approve:'): text='/approve ' + action.split(':',1)[1]
        elif action.startswith('reject:'): text='/reject ' + action.split(':',1)[1]
        else: return True
    if text=='/logout':
        with db() as c: c.execute('DELETE FROM admin_sessions WHERE user_id=?',(uid,)); c.commit()
        send(chat_id,'از پنل خارج شدی.'); return True
    if text=='/stats':
        with db() as c:
            n=c.execute('SELECT COUNT(*) FROM users').fetchone()[0]; active=c.execute('SELECT COUNT(*) FROM groups WHERE active=1').fetchone()[0]; pending=c.execute("SELECT COUNT(*) FROM requests WHERE status='pending'").fetchone()[0]; games=c.execute('SELECT COALESCE(SUM(games),0) FROM users').fetchone()[0]; total=c.execute('SELECT COALESCE(SUM(score),0) FROM users').fetchone()[0]
        send(chat_id,f'📊 آمار\nکاربران: {n}\nبازی‌های انجام‌شده: {games}\nگروه‌های فعال: {active}\nدرخواست‌های منتظر: {pending}\nمجموع امتیازات: {total}'); return True
    if text=='/users':
        with db() as c: rows=c.execute('SELECT user_id,name,score,games,banned FROM users ORDER BY last_seen DESC LIMIT 25').fetchall()
        send(chat_id,'👥 ۲۵ کاربر اخیر:\n'+('\n'.join(f'{r["name"]} | {r["user_id"]} | ⭐{r["score"]} | بازی {r["games"]} | '+('مسدود' if r['banned'] else 'فعال') for r in rows) if rows else 'کاربری نیست.')); return True
    if text=='/requests':
        with db() as c: rows=c.execute("SELECT code,chat_id,requester,title,created_at FROM requests WHERE status='pending' ORDER BY created_at DESC LIMIT 30").fetchall()
        
        if not rows:
            send(chat_id,'📨 درخواست معلقی وجود ندارد.')
        else:
            for r in rows:
                kb=inline_keyboard([[('✅ تأیید',f'adm:approve:{r["code"]}'),('❌ رد',f'adm:reject:{r["code"]}')]])
                send(chat_id,f'📨 درخواست فعال‌سازی\nگروه: {r["title"]}\nشناسه: {r["chat_id"]}\nدرخواست‌کننده: {r["requester"]}\nکد: {r["code"]}',kb)
        return True
    if text=='/groups':
        with db() as c: rows=c.execute('SELECT chat_id,title,activated_at FROM groups WHERE active=1 ORDER BY activated_at DESC').fetchall()
        send(chat_id,'🟢 گروه‌های فعال:\n'+('\n'.join(f'{r["title"]} | {r["chat_id"]} | {r["activated_at"]}' for r in rows) if rows else 'گروهی فعال نیست.')); return True
    m=re.match(r'^/(ban|unban)\s+(\S+)$',text)
    if m:
        act,target=m.groups()
        with db() as c: cur=c.execute('UPDATE users SET banned=? WHERE user_id=?',(1 if act=='ban' else 0,target)); c.commit()
        send(chat_id,'عملیات انجام شد.' if cur.rowcount else 'شناسه کاربر پیدا نشد.'); return True
    m=re.match(r'^/user\s+(\S+)$',text)
    if m:
        target=m.group(1)
        with db() as c: r=c.execute('SELECT * FROM users WHERE user_id=?',(target,)).fetchone()
        send(chat_id,(f'👤 {r["name"]}\nشناسه: {r["user_id"]}\nامتیاز: {r["score"]}\nبازی: {r["games"]}\nدرست: {r["correct"]}\nمسدود: {r["banned"]}\nعضویت: {r["joined_at"]}\nآخرین فعالیت: {r["last_seen"]}') if r else 'کاربر پیدا نشد.'); return True
    m=re.match(r'^/(approve|reject)\s+(\S+)$',text)
    if m:
        act,code=m.groups()
        with db() as c: req=c.execute('SELECT * FROM requests WHERE code=? AND status="pending"',(code,)).fetchone()
        if not req: send(chat_id,'درخواست پیدا نشد یا قبلاً بررسی شده.'); return True
        newstatus='approved' if act=='approve' else 'rejected'
        with db() as c:
            c.execute('UPDATE requests SET status=? WHERE code=?',(newstatus,code))
            if act=='approve': c.execute('INSERT OR REPLACE INTO groups(chat_id,title,active,activated_at) VALUES(?,?,1,?)',(req['chat_id'],req['title'],datetime.now().isoformat()))
            c.commit()
        send(req['chat_id'],'🎉 گروه تأیید و فعال شد! اکنون می‌توانید /quiz را اجرا کنید.' if act=='approve' else '❌ درخواست فعال‌سازی رد شد.'); send(chat_id,'انجام شد.'); return True
    if text.startswith('/'):
        send(chat_id,'دستور پنل نامعتبر است.'); return True
    return True

# ---- Group activation ----
def request_activation(chat_id,uid,title):
    with db() as c:
        pending=c.execute("SELECT code FROM requests WHERE chat_id=? AND status='pending'",(chat_id,)).fetchone()
        active=c.execute('SELECT active FROM groups WHERE chat_id=?',(chat_id,)).fetchone()
    if active and active['active']: send(chat_id,'این گروه از قبل فعال است.'); return
    if pending: send(chat_id,'برای این گروه یک درخواست در حال بررسی وجود دارد.'); return
    code='QZ-'+''.join(random.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(6))
    with db() as c: c.execute('INSERT INTO requests VALUES(?,?,?,?,?,?)',(code,chat_id,uid,title,datetime.now().isoformat(),'pending')); c.commit()
    send(chat_id,'📨 درخواست فعال‌سازی ثبت شد. پس از بررسی مدیر اطلاع داده می‌شود.');
    aid=admin_id()
    if aid:
        kb=inline_keyboard([[('✅ تأیید درخواست',f'adm:approve:{code}'),('❌ رد درخواست',f'adm:reject:{code}')]])
        send(aid,f'📨 درخواست جدید فعال‌سازی\nگروه: {title}\nشناسه: {chat_id}\nدرخواست‌کننده: {uid}\nکد: {code}',kb)

# ---- Routing ----
def handle(chat_id,uid,text,name,title,ctype,sender_type='',button_id=None):
    if not chat_id or not uid or not text: return
    # Ignore bot-originated updates to avoid loops.
    if sender_type in ('bot','rubika_bot'): return
    ensure_user(uid,name)
    if banned(uid): send(chat_id,'⛔ دسترسی شما محدود شده است.'); return
    private=private_chat(chat_id,uid,ctype)
    if private:
        # Admin password is sent as a normal private message; successful entry opens the panel.
        if text == ADMIN_PASSWORD:
            admin_auth(uid, chat_id, text)
            return
        if is_admin(uid):
            handle_admin(uid, chat_id, text, button_id)
            return
    if button_id and private and is_admin(uid):
        handle_admin(uid, chat_id, text, button_id)
        return
    if text in ('/start','شروع'):
        send(chat_id,'🎮 سلام! به QuizZone پیشرفته خوش آمدی.\n\n/quiz — سؤال جدید\n/leaderboard — جدول رتبه‌ها\n/profile — پروفایل\n/daily — جایزه روزانه\n/help — راهنما\n\nبرای فعال‌سازی در گروه، داخل گروه /activate را بفرست.'); return
    if text in ('/help','/menu','راهنما'):
        send(chat_id,'📚 راهنما\n/quiz سؤال جدید\n/leaderboard رتبه‌بندی\n/profile آمار شما\n/daily جایزه روزانه\n/activate درخواست فعال‌سازی گروه\n\nهر پاسخ درست ۱۰ امتیاز؛ هر ۵ پاسخ پیاپی یک جایزه ۵ امتیازی دارد.'); return
    if text=='/leaderboard': leaderboard(chat_id); return
    if text=='/profile': profile(chat_id,uid); return
    if text=='/daily': daily_reward(chat_id,uid); return
    if text=='/activate':
        if private: send(chat_id,'این دستور را داخل گروهی که می‌خواهی فعال شود بفرست.'); return
        request_activation(chat_id,uid,title); return
    if not private:
        with db() as c: g=c.execute('SELECT active FROM groups WHERE chat_id=?',(chat_id,)).fetchone()
        if not g or not g['active']:
            if text in ('/quiz','/leaderboard','/profile','/daily'): send(chat_id,'🔒 این گروه هنوز فعال نشده. برای درخواست فعال‌سازی /activate را بفرستید.')
            return
    if text=='/quiz': start_game(chat_id,uid); return
    if answer_game(chat_id,uid,text): return

# ---- Polling with offset persistence + dedup ----
def get_offset():
    with db() as c: r=c.execute("SELECT value FROM settings WHERE key='offset_id'").fetchone()
    return r['value'] if r else None

def save_offset(offset):
    if offset:
        with db() as c: c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('offset_id',?)",(str(offset),)); c.commit()

def main():
    init_db(); offset=get_offset(); logging.info('QuizZone started; one instance only; persisted offset=%s',bool(offset))
    while True:
        try:
            result=get_updates(offset)
            if not isinstance(result,dict): time.sleep(POLL_DELAY); continue
            updates=result.get('updates',[])
            if not isinstance(updates,list): updates=[]
            for u in updates:
                if not isinstance(u,dict): continue
                chat_id,uid,text,name,title,msgid,ctype,sender_type=parse_update(u)
                # Use message id or a deterministic fingerprint when absent.
                key=msgid or hashlib.sha256(json.dumps(u,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
                if not mark_seen(key): continue
                if chat_id and uid and text: handle(chat_id,uid,text,name,title,ctype,sender_type)
            next_offset=result.get('next_offset_id')
            if next_offset: offset=str(next_offset); save_offset(offset)
            time.sleep(POLL_DELAY)
        except KeyboardInterrupt: break
        except Exception: logging.exception('Polling error'); time.sleep(5)

# ---- Webhook server for Render ----
app = Flask(__name__)
init_db()  # Gunicorn imports the module without running __main__.

@app.get('/')
def health():
    return jsonify({'ok': True, 'service': 'QuizZone', 'webhook': '/webhook'})

def process_webhook_payload(payload):
    if not isinstance(payload, dict):
        return
    # Rubika may deliver regular updates or inline button callbacks in different envelopes.
    candidates = []
    if isinstance(payload.get('inline_message'), dict):
        candidates.append(payload['inline_message'])
    if isinstance(payload.get('update'), dict):
        candidates.append(payload['update'])
    if isinstance(payload.get('data'), dict):
        d = payload['data']
        if isinstance(d.get('inline_message'), dict): candidates.append(d['inline_message'])
        if isinstance(d.get('update'), dict): candidates.append(d['update'])
    if isinstance(payload.get('new_message'), dict) or isinstance(payload.get('message'), dict):
        candidates.append(payload)
    if not candidates:
        candidates.append(payload)
    for item in candidates:
        # Inline callback object has sender_id/chat_id/text/aux_data.
        msg = item.get('new_message') or item.get('message') or item
        if not isinstance(msg, dict): continue
        aux = msg.get('aux_data') or item.get('aux_data') or {}
        button_id = aux.get('button_id', '') if isinstance(aux, dict) else ''
        chat_id = str(item.get('chat_id') or msg.get('chat_id') or msg.get('object_guid') or '')
        uid = str(msg.get('sender_id') or item.get('sender_id') or '')
        text = str(msg.get('text') or item.get('text') or '').strip()
        msgid = str(msg.get('message_id') or item.get('message_id') or '')
        raw_type = str(item.get('chat_type') or msg.get('chat_type') or '').lower()
        if raw_type:
            ctype = raw_type
        elif chat_id.startswith('b0'):
            ctype = 'private'
        elif chat_id.startswith('g0'):
            ctype = 'group'
        elif chat_id.startswith('c0'):
            ctype = 'channel'
        else:
            ctype = 'group'
        title = str(item.get('chat_title') or msg.get('chat_title') or 'گروه')
        sender_type = str(msg.get('sender_type') or '')
        if msgid and not mark_seen(msgid):
            continue
        if chat_id and uid and (text or button_id):
            handle(chat_id, uid, text, str(msg.get('sender_name') or 'کاربر'), title, ctype, sender_type, button_id)

@app.post('/webhook')
@app.post('/receiveUpdate')
@app.post('/receiveInlineMessage')
def webhook():
    payload = request.get_json(silent=True) or {}
    try:
        process_webhook_payload(payload)
        return jsonify({'ok': True}), 200
    except Exception:
        logging.exception('Webhook processing failed')
        return jsonify({'ok': False}), 500

if __name__ == '__main__':
    init_db()
    port = int(os.getenv('PORT', '10000'))
    app.run(host='0.0.0.0', port=port)

