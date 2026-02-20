import os
import sqlite3
import random
import time
import threading
import json
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext, CallbackQueryHandler

GAME_EMOJIS = {
    'Монетка': '🪙',
    'Минёр': '⛏️',
    'Джетпак': '🚀',
    'Слоты': '🎰',
    'Башня': '🗼',
}

def format_game_detail(gname, details_raw, amount, is_win, created_at):
    """Format a detailed game history view with proof data."""
    emoji = GAME_EMOJIS.get(gname, '🎮')
    sign = '+' if is_win else '-'
    result_line = f"{'✅ Выигрыш' if is_win else '❌ Проигрыш'} │ {sign}{amount} 💰"
    sep = "━━━━━━━━━━━━━━━━"
    try:
        data = json.loads(details_raw)
    except Exception:
        return f"{emoji} {gname}\n{sep}\n{result_line}\n{sep}\n📝 {details_raw}\n📅 {created_at}"

    lines = [f"{emoji} {gname.upper()}", sep, result_line, sep]

    if gname == 'Монетка':
        bet = data.get('bet', '?')
        moves = data.get('moves', [])
        coeff = data.get('coeff', 1)
        lines.append(f"💰 Ставка: {bet} | Коэффициент: x{coeff:.0f}")
        if moves:
            lines.append(f"🎲 Ходы: {' → '.join(moves)}")

    elif gname == 'Минёр':
        bet = data.get('bet', '?')
        mines_n = data.get('mines', '?')
        cleared = data.get('cleared', 0)
        mine_pos = set(data.get('mine_positions', []))
        lines.append(f"💰 Ставка: {bet} | 💣 Мин: {mines_n} | ✅ Открыто: {cleared}")
        lines.append(sep)
        lines.append("🗺️ Поле (💣=мина, 🟩=безопасно):")
        for row in range(5):
            cells_row = ["💣" if row*5+col in mine_pos else "🟩" for col in range(5)]
            lines.append(" ".join(cells_row))

    elif gname == 'Башня':
        bet = data.get('bet', '?')
        traps = data.get('traps', [])
        floor_reached = data.get('floor_reached', 0)
        result = data.get('result', '')
        lines.append(f"💰 Ставка: {bet} | Этажей пройдено: {floor_reached}/8")
        lines.append(sep)
        lines.append("🗺️ Карта башни (💣=ловушка):")
        for f in range(7, -1, -1):
            if f >= len(traps):
                continue
            trap = traps[f]
            cells = []
            for c in range(3):
                cells.append("💣" if c == trap else "⬜")
            if f >= floor_reached and not (f == floor_reached - 1 and result in ('cashout', 'top')):
                if result == 'boom' and f == floor_reached:
                    status = "💥"
                elif f > floor_reached or (result == 'boom' and f >= floor_reached):
                    status = "⬆️ не дошёл"
                else:
                    status = "✅"
            else:
                status = "✅"
            lines.append(f"Эт.{f+1}: {' '.join(cells)}  {status}")

    elif gname == 'Джетпак':
        bet = data.get('bet', '?')
        crash = data.get('crash', 0)
        collect = data.get('collect', None)
        result = data.get('result', '')
        lines.append(f"💰 Ставка: {bet}")
        lines.append(f"💥 Краш был на: {crash:.2f}x")
        if collect:
            action = "🤖 Авто-сбор" if result == 'auto' else "✋ Забрал"
            lines.append(f"{action} на: {collect:.2f}x")
        else:
            lines.append("💸 Не успел забрать")

    elif gname == 'Слоты':
        bet = data.get('bet', '?')
        reels = data.get('reels', [])
        mult = data.get('mult', 0)
        lines.append(f"💰 Ставка: {bet}")
        if reels:
            lines.append(f"🎰 Барабаны: {' │ '.join(reels)}")
        lines.append("🎉 Множитель: x" + str(mult) if mult > 1 else ("↩️ Возврат ставки" if mult == 1 else "💸 Промах"))

    lines.append(sep)
    lines.append(f"📅 {created_at}")
    return "\n".join(lines)

DB_PATH = 'users.db'

# ─────────── GLOBAL JETPACK STATE ───────────
# uid -> {'active': bool, 'crash': float, 'current': float, 'bet': int, 'crashed': bool}
jp_games = {}

# ─────────── DATABASE ───────────

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS game_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        uid INTEGER,
        game_name TEXT,
        details TEXT,
        amount INTEGER,
        is_win INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute("PRAGMA table_info(users)")
    cols = [r[1] for r in c.fetchall()]
    needed = ['last_hourly', 'jetpack_best', 'jetpack_auto', 'referrer_id', 'total_refs', 'last_wheel']
    if cols and not all(col in cols for col in needed):
        # Migrate: rebuild table with all columns
        c.execute("ALTER TABLE users RENAME TO users_old")
        c.execute('''CREATE TABLE users (
            id INTEGER PRIMARY KEY, username TEXT DEFAULT '',
            coins INTEGER DEFAULT 500, last_hourly TEXT DEFAULT NULL,
            consecutive_wins INTEGER DEFAULT 0, jetpack_best REAL DEFAULT 0.0,
            jetpack_auto REAL DEFAULT 0.0,
            referrer_id INTEGER DEFAULT NULL, total_refs INTEGER DEFAULT 0,
            last_wheel TEXT DEFAULT NULL)''')
        try:
            c.execute('''INSERT INTO users (id, username, coins, last_hourly, consecutive_wins, jetpack_best, jetpack_auto)
                         SELECT id, username, coins,
                                COALESCE(last_hourly, NULL),
                                COALESCE(consecutive_wins, 0),
                                COALESCE(jetpack_best, 0.0),
                                COALESCE(jetpack_auto, 0.0)
                         FROM users_old''')
        except Exception:
            pass
        c.execute("DROP TABLE users_old")
    else:
        c.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY, username TEXT DEFAULT '',
            coins INTEGER DEFAULT 500, last_hourly TEXT DEFAULT NULL,
            consecutive_wins INTEGER DEFAULT 0, jetpack_best REAL DEFAULT 0.0,
            jetpack_auto REAL DEFAULT 0.0,
            referrer_id INTEGER DEFAULT NULL, total_refs INTEGER DEFAULT 0,
            last_wheel TEXT DEFAULT NULL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS promocodes (
        code TEXT PRIMARY KEY, reward INTEGER,
        uses INTEGER DEFAULT 0, max_uses INTEGER DEFAULT NULL)''')
    c.execute("INSERT OR IGNORE INTO promocodes (code,reward,max_uses) VALUES ('912311',1488,NULL)")
    conn.commit(); conn.close()

def get_user(uid):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute('SELECT * FROM users WHERE id=?', (uid,))
    row = c.fetchone()
    if row is None:
        c.execute('INSERT INTO users (id) VALUES (?)', (uid,))
        conn.commit()
        row = (uid, '', 500, None, 0, 0.0, 0.0, None, 0, None)
    conn.close()
    return row

def can_spin_wheel(uid):
    row = get_user(uid)
    if len(row) < 10 or not row[9]: return True
    last = datetime.fromisoformat(row[9])
    return datetime.now() - last >= timedelta(hours=8)

def time_until_wheel(uid):
    row = get_user(uid)
    if len(row) < 10 or not row[9]: return "0м"
    last = datetime.fromisoformat(row[9])
    diff = timedelta(hours=8) - (datetime.now() - last)
    if diff.total_seconds() <= 0: return "0м"
    h = int(diff.total_seconds() // 3600)
    m = int((diff.total_seconds() % 3600) // 60)
    return f"{h}ч {m}м" if h > 0 else f"{m}м"

def get_leaderboard():
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute('SELECT id, username, coins FROM users ORDER BY coins DESC LIMIT 10')
    rows = c.fetchall()
    conn.close()
    return rows

def add_coins(uid, amount):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute('UPDATE users SET coins=coins+? WHERE id=?', (amount, uid))
    conn.commit(); conn.close()

def log_game(uid, name, details, amount, is_win):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute('INSERT INTO game_history (uid, game_name, details, amount, is_win) VALUES (?,?,?,?,?)',
              (uid, name, details, amount, 1 if is_win else 0))
    conn.commit(); conn.close()

def get_history_paged(uid, page=0, page_size=5):
    offset = page * page_size
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute('SELECT id, game_name, amount, is_win FROM game_history WHERE uid=? ORDER BY id DESC LIMIT ? OFFSET ?', (uid, page_size, offset))
    rows = c.fetchall()
    c.execute('SELECT COUNT(*) FROM game_history WHERE uid=?', (uid,))
    total = c.fetchone()[0]
    conn.close()
    return rows, total

def get_game_info(game_id):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute('SELECT game_name, details, amount, is_win, created_at FROM game_history WHERE id=?', (game_id,))
    row = c.fetchone()
    conn.close()
    return row

def set_field(uid, field, value):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute(f'UPDATE users SET {field}=? WHERE id=?', (value, uid))
    conn.commit(); conn.close()

def can_claim_hourly(uid):
    row = get_user(uid)
    if not row[3]: return True
    last = datetime.fromisoformat(row[3])
    return datetime.now() - last >= timedelta(hours=1)

def time_until_hourly(uid):
    row = get_user(uid)
    if not row[3]: return "0м"
    last = datetime.fromisoformat(row[3])
    diff = timedelta(hours=1) - (datetime.now() - last)
    if diff.total_seconds() <= 0: return "0м"
    m = int(diff.total_seconds() // 60)
    s = int(diff.total_seconds() % 60)
    return f"{m}м {s}с"

# ─────────── KEYBOARDS ───────────

def main_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎮 Игры", callback_data='games_menu'),
         InlineKeyboardButton("👤 Профиль", callback_data='profile')],
        [InlineKeyboardButton("🏆 Топ игроков", callback_data='leaderboard'),
         InlineKeyboardButton("🎁 Бонус", callback_data='hourly_bonus')],
        [InlineKeyboardButton("🎡 Колесо фортуны", callback_data='wheel_menu')],
        [InlineKeyboardButton("🎫 Промокод", callback_data='promo_enter'),
         InlineKeyboardButton("👥 Реферал", callback_data='referral')]
    ])

def games_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🪙 Монетка", callback_data='cf_menu'),
         InlineKeyboardButton("🎰 Слоты",   callback_data='slots_menu')],
        [InlineKeyboardButton("⛏️ Минёр",   callback_data='miner_menu'),
         InlineKeyboardButton("🗼 Башня",    callback_data='tower_menu')],
        [InlineKeyboardButton("🚀 Джетпак", callback_data='jp_menu')],
        [InlineKeyboardButton("🔙 Назад",   callback_data='main_menu')]
    ])

# ── СЛОТЫ: символы с весами ──
SLOTS_SYMBOLS = ['🍒', '🍋', '🔔', '⭐', '💎', '7️⃣']
SLOTS_WEIGHTS = [35, 25, 18, 12, 7, 3]  # сумма = 100, чем реже — тем ценнее
SLOTS_PAYOUTS = {
    ('🍒','🍒','🍒'): 3,
    ('🍋','🍋','🍋'): 5,
    ('🔔','🔔','🔔'): 10,
    ('⭐','⭐','⭐'): 15,
    ('💎','💎','💎'): 25,
    ('7️⃣','7️⃣','7️⃣'): 50,
}

def spin_slots():
    population = SLOTS_SYMBOLS
    weights = SLOTS_WEIGHTS
    return [random.choices(population, weights=weights, k=1)[0] for _ in range(3)]

def check_slots(reels, bet):
    t = tuple(reels)
    if t in SLOTS_PAYOUTS:
        return SLOTS_PAYOUTS[t], int(bet * SLOTS_PAYOUTS[t])
    # Два одинаковых — возврат ставки
    if reels[0]==reels[1] or reels[1]==reels[2] or reels[0]==reels[2]:
        return 1, bet
    return 0, 0

# ── БАШНЯ: коэффициенты по этажам ──
TOWER_FLOORS = 8
TOWER_COEFFS = [1.4, 1.9, 2.6, 3.5, 5.0, 7.5, 12.0, 25.0]  # за прохождение этажа

def tower_keyboard(floor, picked=None):
    """Generate tower keyboard. floor = current floor (0-indexed). picked = index of chosen cell."""
    kb = []
    for f in range(TOWER_FLOORS - 1, -1, -1):
        row = []
        for cell in range(3):
            if f > floor:
                row.append(InlineKeyboardButton("⬜", callback_data='dummy'))
            elif f == floor:
                row.append(InlineKeyboardButton("🟦", callback_data=f'tower_cell_{f}_{cell}'))
            else:
                row.append(InlineKeyboardButton("✅", callback_data='dummy'))
        kb.append(row)
    coeff = TOWER_COEFFS[floor] if floor < TOWER_FLOORS else TOWER_COEFFS[-1]
    kb.append([InlineKeyboardButton(f"💳 Забрать (x{coeff:.1f})", callback_data='tower_cashout')])
    kb.append([InlineKeyboardButton("🔙 Выйти", callback_data='tower_menu')])
    return InlineKeyboardMarkup(kb)

# ── КОЛЕСО ФОРТУНЫ ──
# EV ≈ 27 монет за бесплатный спин каждые 8ч — небольшой бонус, не ломает экономику
# Платный спин стоит 100 монет, EV = 27 - 100 = -73 (невыгодно спамить)
WHEEL_SECTORS = [
    ('Ничего 😔', 0, 50),
    ('+15 монет', 15, 20),
    ('+30 монет', 30, 15),
    ('+75 монет', 75, 8),
    ('+150 монет', 150, 5),
    ('+300 монет 🎉', 300, 2),
]
WHEEL_PAID_COST = 100  # стоимость платного спина

def miner_keyboard(opened, cells):
    kb = []
    for row in range(5):
        r = []
        for col in range(5):
            idx = row * 5 + col
            if opened[idx]:
                emoji = '💣' if cells[idx] == 'mine' else '💎'
                r.append(InlineKeyboardButton(emoji, callback_data='dummy'))
            else:
                r.append(InlineKeyboardButton('🟦', callback_data=f'miner_cell_{idx}'))
        kb.append(r)
    kb.append([InlineKeyboardButton("💳 Забрать выигрыш", callback_data='miner_cashout')])
    kb.append([InlineKeyboardButton("🔙 Выйти в меню", callback_data='miner_menu')])
    return InlineKeyboardMarkup(kb)

def calc_miner_coeff(mines, cleared, safe_count):
    if cleared == 0:
        return 1.0
    total = 25
    coeff = 1.0
    safe = safe_count
    for i in range(cleared):
        remaining_total = total - i
        remaining_safe = safe - i
        if remaining_safe <= 0:
            break
        coeff *= remaining_total / remaining_safe
    return round(coeff * 0.95, 2)

# ─────────── JETPACK GAME LOOP ───────────

def jp_fly_loop(uid, bot, chat_id, msg_id, crash, bet):
    """Background thread: updates coefficient every 2.5s to reduce API spam."""
    coeff = 1.00
    GRACE = 2.5

    while True:
        time.sleep(2.5)

        game = jp_games.get(uid)
        if not game or not game['active']:
            break

        # Динамический шаг: чем выше полет, тем быстрее растет (геометрическая прогрессия)
        # Начинаем с 0.18 каждые 2.5с. При x10 шаг будет около 1.8.
        step = round(0.18 * (coeff ** 1.2), 2)
        coeff = round(coeff + step, 2)
        jp_games[uid]['current'] = coeff

        # Авто-сбор
        auto = game.get('auto', 0.0)
        if auto > 1.0 and coeff >= auto:
            # Превращаем в обычный сбор, но по цене 'auto'
            jp_games[uid]['active'] = False
            add_coins(uid, int(bet * auto))
            log_game(uid, "Джетпак", json.dumps({'bet': bet, 'crash': crash, 'collect': auto, 'result': 'auto'}), int(bet * auto), True)
            row = get_user(uid)
            try:
                bot.edit_message_text(
                    chat_id=chat_id, message_id=msg_id,
                    text=f"🤖 Авто-сбор сработал на {auto:.2f}x!\n💰 Выиграно: {int(bet*auto)} монет\n💰 Баланс: {row[2]} монет",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 Играть снова", callback_data='jp_menu')],
                        [InlineKeyboardButton("🔙 Главное меню", callback_data='main_menu')]
                    ])
                )
            except Exception: pass
            break

        if coeff >= crash:
            # CRASH — record crash time, give grace period
            jp_games[uid]['active'] = False
            jp_games[uid]['crashed'] = True
            jp_games[uid]['crashed_at'] = time.time()
            log_game(uid, "Джетпак", json.dumps({'bet': bet, 'crash': crash, 'collect': None, 'result': 'crash'}), bet, False)
            row = get_user(uid)
            bar = "💥" * min(int(crash), 10)
            try:
                bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=msg_id,
                    text=(
                        f"🚀 Джетпак | Ставка: {bet} монет\n\n"
                        f"{bar}\n"
                        f"💥 КРАШ на {crash:.2f}x!\n"
                        f"Потеряли {bet} монет.\n"
                        f"💰 Баланс: {row[2]} монет"
                    ),
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 Играть снова", callback_data='jp_menu')],
                        [InlineKeyboardButton("🔙 Главное меню", callback_data='main_menu')]
                    ])
                )
            except Exception:
                pass
            break
        else:
            # Still flying — update display
            winnings = int(bet * coeff)
            height = min(int((coeff - 1.0) / 0.5) + 1, 10)
            try:
                bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=msg_id,
                    text=(
                        f"{'🚀' * height}\n"
                        f"═══════════════\n"
                        f"🔥 Коэффициент: {coeff:.2f}x\n"
                        f"💰 Выигрыш: {winnings} монет\n"
                        f"(Ставка: {bet} монет)\n"
                        f"═══════════════\n"
                        f"Нажмите ЗАБРАТЬ пока не поздно!"
                    ),
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton(f"💳 Забрать {winnings} монет!", callback_data='jp_collect')]
                    ])
                )
            except Exception:
                pass

# ─────────── START ───────────

def start(update: Update, context: CallbackContext):
    uid = update.effective_user.id
    user = update.effective_user
    is_new = get_user(uid)[2] == 500  # freshly created

    # Save username
    uname = user.username or user.first_name or ''
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute('UPDATE users SET username=? WHERE id=?', (uname, uid))
    conn.commit(); conn.close()

    # Handle referral
    args = context.args
    if args and args[0].startswith('ref_'):
        try:
            referrer_id = int(args[0].replace('ref_', ''))
            if referrer_id != uid:
                row = get_user(uid)
                if row[7] is None:  # not yet referred
                    set_field(uid, 'referrer_id', referrer_id)
                    add_coins(referrer_id, 200)
                    conn2 = sqlite3.connect(DB_PATH); c2 = conn2.cursor()
                    c2.execute('UPDATE users SET total_refs=total_refs+1 WHERE id=?', (referrer_id,))
                    conn2.commit(); conn2.close()
                    # Notify referrer
                    try:
                        update.bot.send_message(referrer_id, f"👥 По вашей ссылке пришёл новый игрок!\n+200 монет на баланс! 🎉")
                    except Exception:
                        pass
        except (ValueError, IndexError):
            pass

    row = get_user(uid)
    update.message.reply_text(
        f"👋 Добро пожаловать, {uname}!\n💰 Баланс: {row[2]} монет\n\nВыберите действие:",
        reply_markup=main_menu_kb()
    )

# ─────────── BUTTON HANDLER ───────────

def btn(update: Update, context: CallbackContext):
    q = update.callback_query
    uid = q.from_user.id
    d = q.data
    try:
        q.answer()
    except Exception:
        pass

    try:
        _btn_handler(q, uid, d, context)
    except Exception as e:
        if 'Message is not modified' in str(e):
            pass  # silently ignore duplicate clicks
        else:
            raise

def _btn_handler(q, uid, d, context):
    # ── ГЛАВНОЕ МЕНЮ ──
    if d == 'main_menu':
        row = get_user(uid)
        q.edit_message_text(
            f"🏠 Главное меню\n💰 Баланс: {row[2]} монет",
            reply_markup=main_menu_kb()
        )

    elif d == 'profile':
        row = get_user(uid)
        # profile: (uid, username, coins, last_hourly, wins, jp_best, jp_auto, referrer_id, total_refs, last_wheel)
        uname = row[1] if row[1] else f"ID:{uid}"
        msg = (
            f"👤 Профиль: {uname}\n"
            f" Баланс: {row[2]} монет\n"
            f"🚀 Рекорд Jetpack: {row[5]:.2f}x\n"
            f"👥 Рефералов: {row[8]}\n"
            f"📅 Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n"
        )
        q.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📜 История игр", callback_data='history')],
            [InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]
        ]))

    elif d.startswith('history'):
        page = 0
        if d != 'history' and '_' in d:
            try: page = int(d.rsplit('_', 1)[-1])
            except: page = 0
        
        rows, total = get_history_paged(uid, page)
        pages = (total + 4) // 5 or 1
        if not rows:
            text = "📜 История игр пуста.\n\nСыграйте в любую игру!"
            kb = [[InlineKeyboardButton("🔙 К профилю", callback_data='profile')]]
        else:
            text = f"📜 История игр\n━━━━━━━━━━━━━━━━\nСтраница {page+1} из {pages} | Всего: {total}\n\nНажмите на игру для деталей:"
            kb = []
            for gid, gname, amount, is_win in rows:
                g_emoji = GAME_EMOJIS.get(gname, '🎮')
                res_emoji = "✅" if is_win else "❌"
                sign = "+" if is_win else "-"
                kb.append([InlineKeyboardButton(
                    f"{res_emoji} {g_emoji} {gname}: {sign}{amount} 💰",
                    callback_data=f'gameview_{gid}_{page}'
                )])
            nav = []
            if page > 0:
                nav.append(InlineKeyboardButton("◀️", callback_data=f'history_{page-1}'))
            nav.append(InlineKeyboardButton(f"{page+1}/{pages}", callback_data='dummy'))
            if (page + 1) * 5 < total:
                nav.append(InlineKeyboardButton("▶️", callback_data=f'history_{page+1}'))
            if len(nav) > 1: kb.append(nav)
            kb.append([InlineKeyboardButton("🔙 К профилю", callback_data='profile')])
        
        q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

    elif d.startswith('gameview_'):
        parts = d.split('_')
        gid = int(parts[1])
        back_page = int(parts[2])
        g = get_game_info(gid)
        if not g:
            q.answer("Игра не найдена", show_alert=True); return
        gname, details, amount, is_win, created_at = g
        msg = format_game_detail(gname, details, amount, is_win, created_at)
        q.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Назад к списку", callback_data=f'history_{back_page}')]
        ]))

    elif d == 'games_menu':
        q.edit_message_text("🎮 Выберите игру:", reply_markup=games_menu_kb())

    elif d == 'dummy':
        pass  # ignore clicks on revealed miner cells

    # ── ЕЖЕЧАСНЫЙ БОНУС ──
    elif d == 'hourly_bonus':
        if can_claim_hourly(uid):
            q.edit_message_text(
                "🎁 Ежечасный бонус!\nУгадайте число от 1 до 3 — введите в чат:",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Отмена", callback_data='main_menu')]]))
            context.user_data['state'] = 'hourly_guess'
        else:
            q.edit_message_text(
                f"⏰ Следующий бонус через: {time_until_hourly(uid)}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]]))

    # ── ПРОМОКОД ──
    elif d == 'promo_enter':
        q.edit_message_text(
            "🎫 Введите промокод в чат:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Отмена", callback_data='main_menu')]]))
        context.user_data['state'] = 'promo'

    # ════════════════════════════
    # ── МОНЕТКА ──
    # ════════════════════════════
    elif d == 'cf_menu':
        bet = context.user_data.get('cf_bet', 0)
        row = get_user(uid)
        can_start = bet > 0
        q.edit_message_text(
            f"🪙 Монетка\n💰 Баланс: {row[2]} монет\nСтавка: {bet} монет",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("▶️ Начать игру", callback_data='cf_start') if can_start
                 else InlineKeyboardButton("▶️ Начать (сначала сделайте ставку)", callback_data='cf_need_bet')],
                [InlineKeyboardButton(f"💰 Сделать ставку ({bet} монет)", callback_data='cf_set_bet')],
                [InlineKeyboardButton("🔙 Главное меню", callback_data='main_menu')]
            ])
        )

    elif d == 'cf_need_bet':
        q.answer("Сначала сделайте ставку!", show_alert=True)

    elif d == 'cf_set_bet':
        q.edit_message_text(
            "💰 Введите сумму ставки для Монетки:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='cf_menu')]]))
        context.user_data['state'] = 'cf_bet'

    elif d == 'cf_start':
        bet = context.user_data.get('cf_bet', 0)
        row = get_user(uid)
        if bet <= 0:
            q.answer("Сначала сделайте ставку!", show_alert=True); return
        if bet > row[2]:
            q.answer("Недостаточно монет!", show_alert=True); return
        add_coins(uid, -bet)
        context.user_data['cf_active'] = True
        context.user_data['cf_coeff'] = 1.0
        context.user_data['cf_moves'] = []  # reset moves for this session
        q.edit_message_text(
            f"🪙 Монетка | Ставка: {bet} монет\nВыберите: орёл или решка?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🦅 Орёл", callback_data='cf_heads'),
                 InlineKeyboardButton("🪙 Решка", callback_data='cf_tails')],
                [InlineKeyboardButton("❌ Выйти (ставка сгорит)", callback_data='cf_forfeit')]
            ])
        )

    elif d in ('cf_heads', 'cf_tails'):
        if not context.user_data.get('cf_active', False):
            q.answer("Игра не активна! Начните новую игру.", show_alert=True); return
        bet = context.user_data.get('cf_bet', 0)
        coeff = context.user_data.get('cf_coeff', 1.0)
        choice = 'heads' if d == 'cf_heads' else 'tails'
        result = random.choice(['heads', 'tails'])
        won = (choice == result)
        result_emoji = "🦅 Орёл" if result == 'heads' else "🪙 Решка"

        if won:
            new_coeff = coeff * 2
            context.user_data['cf_coeff'] = new_coeff
            context.user_data.setdefault('cf_moves', []).append(f"✅{result_emoji}")
            potential = int(bet * new_coeff)
            q.edit_message_text(
                f"🎉 Выпало: {result_emoji} — Угадали!\n\nСтавка: {bet} монет\n🔥 Коэффициент: {new_coeff:.0f}x\n💰 Возможный выигрыш: {potential} монет\n\nПродолжить или забрать?",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🦅 Орёл", callback_data='cf_heads'),
                     InlineKeyboardButton("🪙 Решка", callback_data='cf_tails')],
                    [InlineKeyboardButton(f"💳 Забрать {potential} монет", callback_data='cf_cashout')]
                ])
            )
        else:
            context.user_data['cf_active'] = False
            context.user_data['cf_coeff'] = 1.0
            moves = context.user_data.get('cf_moves', [])
            moves.append(f"❌{result_emoji}")
            log_game(uid, "Монетка", json.dumps({'bet': bet, 'moves': moves, 'coeff': int(coeff), 'result': 'loss'}), bet, False)
            row = get_user(uid)
            q.edit_message_text(
                f"😞 Выпало: {result_emoji} — Не угадали!\nВы проиграли {bet} монет.\n💰 Баланс: {row[2]} монет",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Играть снова", callback_data='cf_menu')],
                    [InlineKeyboardButton("🔙 Главное меню", callback_data='main_menu')]
                ])
            )

    elif d == 'cf_cashout':
        bet = context.user_data.get('cf_bet', 0)
        coeff = context.user_data.get('cf_coeff', 1.0)
        winnings = int(bet * coeff)
        add_coins(uid, winnings)
        moves = context.user_data.get('cf_moves', [])
        log_game(uid, "Монетка", json.dumps({'bet': bet, 'moves': moves, 'coeff': int(coeff), 'result': 'cashout'}), winnings, True)
        context.user_data['cf_active'] = False
        context.user_data['cf_coeff'] = 1.0
        context.user_data['cf_moves'] = []
        row = get_user(uid)
        profit = winnings - bet
        q.edit_message_text(
            f"✅ Выигрыш забран!\n💰 +{winnings} монет (x{coeff:.0f}) | Прибыль: +{profit}\n💰 Баланс: {row[2]} монет",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Играть снова", callback_data='cf_menu')],
                [InlineKeyboardButton("🔙 Главное меню", callback_data='main_menu')]
            ])
        )

    elif d == 'cf_forfeit':
        context.user_data['cf_active'] = False
        context.user_data['cf_coeff'] = 1.0
        row = get_user(uid)
        q.edit_message_text(
            f"❌ Вы вышли. Ставка потеряна.\n💰 Баланс: {row[2]} монет",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Главное меню", callback_data='main_menu')]]))

    # ════════════════════════════
    # ── МИНЁР ──
    # ════════════════════════════
    elif d == 'miner_menu':
        bet = context.user_data.get('miner_bet', 0)
        mines = context.user_data.get('miner_mines', 5)
        row = get_user(uid)
        can_start = bet > 0
        q.edit_message_text(
            f"⛏️ Минёр\n💰 Баланс: {row[2]} монет\nСтавка: {bet} монет | Мин: {mines}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("▶️ Начать игру", callback_data='miner_start') if can_start
                 else InlineKeyboardButton("▶️ Начать (сделайте ставку)", callback_data='miner_need_bet')],
                [InlineKeyboardButton(f"💰 Изменить ставку ({bet})", callback_data='miner_set_bet')],
                [InlineKeyboardButton(f"💣 Изменить мины ({mines})", callback_data='miner_set_mines')],
                [InlineKeyboardButton("🔙 Назад", callback_data='games_menu')]
            ])
        )

    elif d == 'miner_need_bet':
        q.answer("Сначала сделайте ставку!", show_alert=True)

    elif d == 'miner_set_bet':
        q.edit_message_text(
            "💰 Введите сумму ставки для Минёра:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='miner_menu')]]))
        context.user_data['state'] = 'miner_bet'

    elif d == 'miner_set_mines':
        q.edit_message_text("💣 Выберите количество мин:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("3",  callback_data='miner_mines_3'),
                 InlineKeyboardButton("5",  callback_data='miner_mines_5'),
                 InlineKeyboardButton("10", callback_data='miner_mines_10')],
                [InlineKeyboardButton("15", callback_data='miner_mines_15'),
                 InlineKeyboardButton("20", callback_data='miner_mines_20'),
                 InlineKeyboardButton("24", callback_data='miner_mines_24')],
                [InlineKeyboardButton("✏️ Своё число", callback_data='miner_mines_custom')],
                [InlineKeyboardButton("🔙 Назад", callback_data='miner_menu')]
            ])
        )

    elif d.startswith('miner_mines_'):
        val = d.replace('miner_mines_', '')
        if val == 'custom':
            q.edit_message_text(
                "💣 Введите количество мин (3-24):",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='miner_menu')]]))
            context.user_data['state'] = 'miner_mines'
        else:
            mines = int(val)
            context.user_data['miner_mines'] = mines
            bet = context.user_data.get('miner_bet', 0)
            row = get_user(uid)
            can_start = bet > 0
            q.edit_message_text(
                f"⛏️ Минёр\n💰 Баланс: {row[2]} монет\nСтавка: {bet} монет | Мин: {mines}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("▶️ Начать игру", callback_data='miner_start') if can_start
                     else InlineKeyboardButton("▶️ Начать (сделайте ставку)", callback_data='miner_need_bet')],
                    [InlineKeyboardButton(f"💰 Изменить ставку ({bet})", callback_data='miner_set_bet')],
                    [InlineKeyboardButton(f"💣 Изменить мины ({mines})", callback_data='miner_set_mines')],
                    [InlineKeyboardButton("🔙 Назад", callback_data='games_menu')]
                ])
            )

    elif d == 'miner_start':
        bet = context.user_data.get('miner_bet', 0)
        mines = context.user_data.get('miner_mines', 5)
        row = get_user(uid)
        if bet <= 0:
            q.answer("Сначала сделайте ставку!", show_alert=True); return
        if bet > row[2]:
            q.answer("Недостаточно монет!", show_alert=True); return

        add_coins(uid, -bet)
        cells = ['safe'] * 25
        for pos in random.sample(range(25), mines):
            cells[pos] = 'mine'

        context.user_data['miner_cells'] = cells
        context.user_data['miner_opened'] = [False] * 25
        context.user_data['miner_active'] = True
        context.user_data['miner_cleared'] = 0

        safe_count = 25 - mines
        coeff = calc_miner_coeff(mines, 0, safe_count)
        row2 = get_user(uid)
        q.edit_message_text(
            f"⛏️ Минёр | Ставка: {bet} монет | Мин: {mines}\n💰 Баланс: {row2[2]} монет\nКоэффициент: {coeff:.2f}x | Выигрыш: {int(bet*coeff)} монет",
            reply_markup=miner_keyboard(context.user_data['miner_opened'], cells)
        )

    elif d.startswith('miner_cell_'):
        if not context.user_data.get('miner_active', False):
            q.answer("Игра не активна!", show_alert=True); return

        idx = int(d.replace('miner_cell_', ''))
        cells = context.user_data.get('miner_cells', [])
        opened = context.user_data.get('miner_opened', [False] * 25)
        bet = context.user_data.get('miner_bet', 0)
        mines = context.user_data.get('miner_mines', 5)
        cleared = context.user_data.get('miner_cleared', 0)

        if not cells or opened[idx]:
            q.answer("Уже открыто!", show_alert=True); return

        opened[idx] = True
        context.user_data['miner_opened'] = opened

        if cells[idx] == 'mine':
            for i in range(25):
                if cells[i] == 'mine':
                    opened[i] = True
            context.user_data['miner_active'] = False
            mine_pos = [i for i, c in enumerate(cells) if c == 'mine']
            log_game(uid, "Минёр", json.dumps({'bet': bet, 'mines': mines, 'mine_positions': mine_pos, 'cleared': cleared, 'result': 'boom'}), bet, False)
            row = get_user(uid)
            q.edit_message_text(
                f"💥 Бум! Вы попали на мину.\nПотеряли {bet} монет.\n💰 Баланс: {row[2]} монет",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Новая игра", callback_data='miner_menu')],
                    [InlineKeyboardButton("🔙 Главное меню", callback_data='main_menu')]
                ])
            )
        else:
            cleared += 1
            context.user_data['miner_cleared'] = cleared
            safe_count = 25 - mines
            coeff = calc_miner_coeff(mines, cleared, safe_count)
            winnings = int(bet * coeff)

            if cleared == safe_count:
                add_coins(uid, winnings)
                context.user_data['miner_active'] = False
                mine_pos2 = [i for i, c in enumerate(cells) if c == 'mine']
                log_game(uid, "Минёр", json.dumps({'bet': bet, 'mines': mines, 'mine_positions': mine_pos2, 'cleared': cleared, 'result': 'full'}), winnings, True)
                row = get_user(uid)
                q.edit_message_text(
                    f"🎉 Все ячейки открыты!\n💰 +{winnings} монет (x{coeff:.2f})\n💰 Баланс: {row[2]} монет",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 Новая игра", callback_data='miner_menu')],
                        [InlineKeyboardButton("🔙 Главное меню", callback_data='main_menu')]
                    ])
                )
            else:
                q.edit_message_text(
                    f"⛏️ Минёр | Ставка: {bet} | Мин: {mines}\n✅ Открыто: {cleared} | Коэффициент: {coeff:.2f}x\n💰 Выигрыш: {winnings} монет",
                    reply_markup=miner_keyboard(opened, cells)
                )

    elif d == 'miner_cashout':
        if not context.user_data.get('miner_active', False):
            q.answer("Нет активной игры!", show_alert=True); return
        bet = context.user_data.get('miner_bet', 0)
        mines = context.user_data.get('miner_mines', 5)
        cleared = context.user_data.get('miner_cleared', 0)
        safe_count = 25 - mines
        coeff = calc_miner_coeff(mines, cleared, safe_count)
        winnings = int(bet * coeff)
        add_coins(uid, winnings)
        context.user_data['miner_active'] = False
        mine_pos3 = [i for i, c in enumerate(context.user_data.get('miner_cells', [])) if c == 'mine']
        log_game(uid, "Минёр", json.dumps({'bet': bet, 'mines': mines, 'mine_positions': mine_pos3, 'cleared': cleared, 'result': 'cashout'}), winnings, True)
        row = get_user(uid)
        profit = winnings - bet
        q.edit_message_text(
            f"✅ Выигрыш забран!\n💰 +{winnings} монет (x{coeff:.2f}) | Прибыль: +{profit}\n💰 Баланс: {row[2]} монет",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Новая игра", callback_data='miner_menu')],
                [InlineKeyboardButton("🔙 Главное меню", callback_data='main_menu')]
            ])
        )

    # ════════════════════════════
    # ── ДЖЕТПАК ──
    # ════════════════════════════
    elif d == 'jp_menu':
        # Stop any active game for this user
        if uid in jp_games:
            jp_games[uid]['active'] = False
        bet = context.user_data.get('jp_bet', 0)
        auto = context.user_data.get('jp_auto', 0.0)
        row = get_user(uid)
        auto_txt = f"{auto:.2f}x" if auto > 1.0 else "Выкл"
        can_start = bet > 0
        q.edit_message_text(
            f"🚀 Джетпак\n💰 Баланс: {row[2]} монет\nСтавка: {bet} монет | Авто-сбор: {auto_txt}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("▶️ Начать игру", callback_data='jp_start') if can_start
                 else InlineKeyboardButton("▶️ Начать (сделайте ставку)", callback_data='jp_need_bet')],
                [InlineKeyboardButton(f"💰 Ставка ({bet})", callback_data='jp_set_bet'),
                 InlineKeyboardButton(f"🤖 Авто ({auto_txt})", callback_data='jp_set_auto')],
                [InlineKeyboardButton("🔙 Назад", callback_data='games_menu')]
            ])
        )

    elif d == 'jp_need_bet':
        q.answer("Сначала сделайте ставку!", show_alert=True)

    elif d == 'jp_set_bet':
        q.edit_message_text(
            "💰 Введите сумму ставки для Джетпака:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='jp_menu')]]))
        context.user_data['state'] = 'jp_bet'

    elif d == 'jp_set_auto':
        q.edit_message_text(
            "🤖 Введите коэффициент авто-сбора (напр. 2.5 или 2,5)\nВведите 0 — чтобы выключить:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='jp_menu')]]))
        context.user_data['state'] = 'jp_auto'

    elif d == 'jp_start':
        bet = context.user_data.get('jp_bet', 0)
        row = get_user(uid)
        if bet <= 0:
            q.answer("Сначала сделайте ставку!", show_alert=True); return
        if bet > row[2]:
            q.answer("Недостаточно монет!", show_alert=True); return
        if jp_games.get(uid, {}).get('active', False):
            q.answer("Игра уже идёт!", show_alert=True); return

        # Generate crash point: standard formula P(crash >= x) = 0.95/x
        r = random.random()
        if r < 0.05:
            crash = 0.00  # instant bust
        else:
            crash = round(0.95 / (1.0 - r), 2)

        auto = context.user_data.get('jp_auto', 0.0)

        # Deduct bet immediately
        add_coins(uid, -bet)
        row2 = get_user(uid)

        # Instant crash?
        if crash == 0.00:
            q.edit_message_text(
                f"🚀 Джетпак | Ставка: {bet} монет\n\n💥💀 МГНОВЕННЫЙ КРАШ на 0.00x!\nПотеряли {bet} монет.\n💰 Баланс: {row2[2]} монет",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Играть снова", callback_data='jp_menu')],
                    [InlineKeyboardButton("🔙 Главное меню", callback_data='main_menu')]
                ])
            )
            return

        # Auto-collect at crash if auto <= crash and auto > 1.0 (handled in thread)
        # Register game state
        jp_games[uid] = {
            'active': True,
            'crash': crash,
            'current': 1.00,
            'bet': bet,
            'auto': auto,
            'crashed': False,
            'crashed_at': 0
        }

        # Edit message to show the start
        q.edit_message_text(
            f"🚀\n═══════════════\n🔥 Коэффициент: 1.00x\n💰 Выигрыш: {bet} монет\n(Ставка: {bet} монет)\n═══════════════\nНажмите ЗАБРАТЬ пока не поздно!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"💳 Забрать {bet} монет!", callback_data='jp_collect')]
            ])
        )

        # Start background thread
        chat_id = q.message.chat_id
        msg_id = q.message.message_id
        bot = q.bot

        # Check auto-cashout: if auto <= crash, the thread will handle it
        t = threading.Thread(
            target=jp_fly_loop,
            args=(uid, bot, chat_id, msg_id, crash, bet),
            daemon=True
        )
        t.start()

    # ════════════════════════════
    # ── СЛОТЫ ──
    # ════════════════════════════
    elif d == 'slots_menu':
        bet = context.user_data.get('slots_bet', 0)
        row = get_user(uid)
        q.edit_message_text(
            f"🎰 Слоты\n💰 Баланс: {row[2]} монет\nСтавка: {bet} монет\n\nКомбинации:\n🍒x3 = 3x | 🍋x3 = 5x | 🔔x3 = 10x\n⭐x3 = 15x | 💎x3 = 25x | 7️⃣x3 = 50x\nДва одинаковых = возврат ставки",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎰 Крутить!", callback_data='slots_spin') if bet > 0
                 else InlineKeyboardButton("🎰 Крутить (сделайте ставку)", callback_data='slots_need_bet')],
                [InlineKeyboardButton(f"💰 Ставка ({bet})", callback_data='slots_set_bet')],
                [InlineKeyboardButton("🔙 Назад", callback_data='games_menu')]
            ])
        )

    elif d == 'slots_need_bet':
        q.answer("Сначала сделайте ставку!", show_alert=True)

    elif d == 'slots_set_bet':
        q.edit_message_text("💰 Введите сумму ставки для Слотов:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='slots_menu')]]))
        context.user_data['state'] = 'slots_bet'

    elif d == 'slots_spin':
        bet = context.user_data.get('slots_bet', 0)
        row = get_user(uid)
        if bet <= 0:
            q.answer("Сначала сделайте ставку!", show_alert=True); return
        if bet > row[2]:
            q.answer("Недостаточно монет!", show_alert=True); return
        add_coins(uid, -bet)
        reels = spin_slots()
        mult, winnings = check_slots(reels, bet)
        display = ' | '.join(reels)
        slots_details = json.dumps({'bet': bet, 'reels': reels, 'mult': mult, 'winnings': winnings})
        if mult == 0:
            log_game(uid, "Слоты", slots_details, bet, False)
            msg = f"🎰 {display}\n\nПромах! Потеряли {bet} монет."
        elif mult == 1:
            add_coins(uid, winnings)
            log_game(uid, "Слоты", slots_details, winnings, True)
            msg = f"🎰 {display}\n\nДва одинаковых — возврат ставки! +{winnings} монет."
        else:
            add_coins(uid, winnings)
            log_game(uid, "Слоты", slots_details, winnings, True)
            msg = f"🎰 {display}\n\n🎉 ВЫИГРЫШ! x{mult} = +{winnings} монет!"
        row2 = get_user(uid)
        profit = winnings - bet
        q.edit_message_text(
            f"{msg}\n💰 Баланс: {row2[2]} монет",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎰 Ещё раз!", callback_data='slots_spin')],
                [InlineKeyboardButton(f"💰 Ставка ({bet})", callback_data='slots_set_bet')],
                [InlineKeyboardButton("🔙 Выйти", callback_data='slots_menu')]
            ])
        )

    # ════════════════════════════
    # ── БАШНЯ ──
    # ════════════════════════════
    elif d == 'tower_menu':
        bet = context.user_data.get('tower_bet', 0)
        row = get_user(uid)
        coeffs_txt = " → ".join([f"{c:.1f}x" for c in TOWER_COEFFS])
        q.edit_message_text(
            f"🗼 Башня\n💰 Баланс: {row[2]} монет\nСтавка: {bet} монет\n\n8 этажей. На каждом 3 ячейки — 1 опасная.\nКоэффициенты: {coeffs_txt}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("▶️ Начать", callback_data='tower_start') if bet > 0
                 else InlineKeyboardButton("▶️ Начать (сделайте ставку)", callback_data='tower_need_bet')],
                [InlineKeyboardButton(f"💰 Ставка ({bet})", callback_data='tower_set_bet')],
                [InlineKeyboardButton("🔙 Назад", callback_data='games_menu')]
            ])
        )

    elif d == 'tower_need_bet':
        q.answer("Сначала сделайте ставку!", show_alert=True)

    elif d == 'tower_set_bet':
        q.edit_message_text("💰 Введите сумму ставки для Башни:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='tower_menu')]]))
        context.user_data['state'] = 'tower_bet'

    elif d == 'tower_start':
        bet = context.user_data.get('tower_bet', 0)
        row = get_user(uid)
        if bet <= 0:
            q.answer("Сначала сделайте ставку!", show_alert=True); return
        if bet > row[2]:
            q.answer("Недостаточно монет!", show_alert=True); return
        add_coins(uid, -bet)
        # Generate trap positions for each floor
        traps = [random.randint(0, 2) for _ in range(TOWER_FLOORS)]
        context.user_data['tower_traps'] = traps
        context.user_data['tower_floor'] = 0
        context.user_data['tower_active'] = True
        row2 = get_user(uid)
        coeff = TOWER_COEFFS[0]
        q.edit_message_text(
            f"🗼 Башня | Ставка: {bet}\n💰 Баланс: {row2[2]}\nЭтаж 1/{TOWER_FLOORS} | Следующий коэффициент: {coeff:.1f}x\nВозможный выигрыш: {int(bet*coeff)} монет",
            reply_markup=tower_keyboard(0)
        )

    elif d.startswith('tower_cell_'):
        if not context.user_data.get('tower_active', False):
            q.answer("Нет активной игры!", show_alert=True); return
        parts = d.split('_')
        floor = int(parts[2])
        cell = int(parts[3])
        current_floor = context.user_data.get('tower_floor', 0)
        if floor != current_floor:
            q.answer("Это не текущий этаж!", show_alert=True); return
        bet = context.user_data.get('tower_bet', 0)
        traps = context.user_data.get('tower_traps', [])
        trap = traps[floor] if floor < len(traps) else -1

        if cell == trap:
            # Boom!
            context.user_data['tower_active'] = False
            log_game(uid, "Башня", json.dumps({'bet': bet, 'traps': traps, 'floor_reached': floor, 'result': 'boom'}), bet, False)
            row = get_user(uid)
            q.edit_message_text(
                f"💥 Бум! Ловушка на этаже {floor+1}!\nПотеряли {bet} монет.\n💰 Баланс: {row[2]} монет",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Играть снова", callback_data='tower_menu')],
                    [InlineKeyboardButton("🔙 Главное меню", callback_data='main_menu')]
                ])
            )
        else:
            # Safe! Go up
            next_floor = floor + 1
            context.user_data['tower_floor'] = next_floor
            coeff = TOWER_COEFFS[floor]  # coeff for PASSING this floor
            winnings = int(bet * coeff)

            if next_floor >= TOWER_FLOORS:
                # Top of tower!
                add_coins(uid, winnings)
                context.user_data['tower_active'] = False
                log_game(uid, "Башня", json.dumps({'bet': bet, 'traps': traps, 'floor_reached': TOWER_FLOORS, 'coeff': coeff, 'result': 'top'}), winnings, True)
                row = get_user(uid)
                q.edit_message_text(
                    f"🏆 Вы добрались до вершины!\n💰 +{winnings} монет (x{coeff:.1f})\n💰 Баланс: {row[2]} монет",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 Играть снова", callback_data='tower_menu')],
                        [InlineKeyboardButton("🔙 Главное меню", callback_data='main_menu')]
                    ])
                )
            else:
                next_coeff = TOWER_COEFFS[next_floor]
                row = get_user(uid)
                q.edit_message_text(
                    f"🗼 Башня | Этаж {next_floor+1}/{TOWER_FLOORS}\nТекущий выигрыш: {winnings} монет (x{coeff:.1f})\nСледующий: {int(bet*next_coeff)} монет (x{next_coeff:.1f})\n💰 Баланс: {row[2]} монет",
                    reply_markup=tower_keyboard(next_floor)
                )

    elif d == 'tower_cashout':
        if not context.user_data.get('tower_active', False):
            q.answer("Нет активной игры!", show_alert=True); return
        floor = context.user_data.get('tower_floor', 0)
        bet = context.user_data.get('tower_bet', 0)
        if floor == 0:
            q.answer("Сначала пройдите хотя бы один этаж!", show_alert=True); return
        coeff = TOWER_COEFFS[floor - 1]
        winnings = int(bet * coeff)
        add_coins(uid, winnings)
        context.user_data['tower_active'] = False
        log_game(uid, "Башня", json.dumps({'bet': bet, 'traps': context.user_data.get('tower_traps', []), 'floor_reached': floor, 'coeff': coeff, 'result': 'cashout'}), winnings, True)
        row = get_user(uid)
        profit = winnings - bet
        q.edit_message_text(
            f"✅ Выигрыш забран на {floor} этаже!\n💰 +{winnings} монет (x{coeff:.1f}) | Прибыль: +{profit}\n💰 Баланс: {row[2]} монет",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Играть снова", callback_data='tower_menu')],
                [InlineKeyboardButton("🔙 Главное меню", callback_data='main_menu')]
            ])
        )

    # ════════════════════════════
    # ── КОЛЕСО ФОРТУНЫ ──
    # ════════════════════════════
    elif d == 'wheel_menu':
        row = get_user(uid)
        free = can_spin_wheel(uid)
        free_txt = "✅ Бесплатное вращение доступно!" if free else f"⏰ Следующее через {time_until_wheel(uid)}"
        q.edit_message_text(
            f"🎡 Колесо фортуны\n💰 Баланс: {row[2]} монет\n{free_txt}\n\nСекторы:\nНичего (50%) | +15 (20%) | +30 (15%)\n+75 (8%) | +150 (5%) | +300 (2%)\n\nБесплатно каждые 8 часов.\nПлатное вращение: {WHEEL_PAID_COST} монет.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎡 Крутить бесплатно!", callback_data='wheel_free') if free
                 else InlineKeyboardButton(f"🎡 Крутить за {WHEEL_PAID_COST} монет", callback_data='wheel_paid')],
                [InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]
            ])
        )

    elif d in ('wheel_free', 'wheel_paid'):
        row = get_user(uid)
        if d == 'wheel_paid':
            if row[2] < WHEEL_PAID_COST:
                q.answer(f"Недостаточно монет! Нужно {WHEEL_PAID_COST}.", show_alert=True); return
            add_coins(uid, -WHEEL_PAID_COST)
        else:
            if not can_spin_wheel(uid):
                q.answer(f"Подождите ещё {time_until_wheel(uid)}", show_alert=True); return
        # Spin!
        set_field(uid, 'last_wheel', datetime.now().isoformat())
        names = [s[0] for s in WHEEL_SECTORS]
        rewards = [s[1] for s in WHEEL_SECTORS]
        weights = [s[2] for s in WHEEL_SECTORS]
        chosen = random.choices(list(zip(names, rewards)), weights=weights, k=1)[0]
        name, reward = chosen
        if reward == 0:
            msg = f"🎡 Выпало: {name}\nНичего не выиграли."
        elif reward == -1:
            old = get_user(uid)[2]
            add_coins(uid, old)  # double balance = add current balance
            new_bal = get_user(uid)[2]
            msg = f"🎡 Выпало: {name}!\n💰 Баланс удвоен: {old} → {new_bal} монет! 🎉"
        else:
            add_coins(uid, reward)
            msg = f"🎡 Выпало: {name}!\n🎉 +{reward} монет!"
        row2 = get_user(uid)
        q.edit_message_text(
            f"{msg}\n💰 Баланс: {row2[2]} монет",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"🎡 Платное вращение ({WHEEL_PAID_COST} монет)", callback_data='wheel_paid')],
                [InlineKeyboardButton("🔙 Главное меню", callback_data='main_menu')]
            ])
        )

    # ════════════════════════════
    # ── ТАБЛИЦА ЛИДЕРОВ ──
    # ════════════════════════════
    elif d == 'leaderboard':
        leaders = get_leaderboard()
        medals = ['🥇', '🥈', '🥉', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣', '🔟']
        text = "🏆 Топ-10 игроков:\n\n"
        for i, (lid, uname, coins) in enumerate(leaders):
            name = uname if uname else f"ID:{lid}"
            text += f"{medals[i]} {name} — {coins} монет\n"
        q.edit_message_text(text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]]))

    # ════════════════════════════
    # ── РЕФЕРАЛЬНАЯ СИСТЕМА ──
    # ════════════════════════════
    elif d == 'referral':
        row = get_user(uid)
        refs = row[8] if len(row) > 8 else 0
        earned = refs * 200
        bot_info = q.bot.get_me()
        bot_username = bot_info.username
        ref_link = f"https://t.me/{bot_username}?start=ref_{uid}"
        q.edit_message_text(
            f"👥 Реферальная система\n\n"
            f"Приглашайте друзей и получайте 200 монет за каждого!\n\n"
            f"🔗 Ваша ссылка:\n{ref_link}\n\n"
            f"👥 Приглашено: {refs} чел.\n"
            f"💰 Заработано: {earned} монет",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]]))

    elif d == 'jp_collect':
        game = jp_games.get(uid)
        GRACE = 2.5  # matching the loop interval
        crashed_recently = (
            game and game.get('crashed') and
            (time.time() - game.get('crashed_at', 0)) < GRACE
        )
        if not game or (not game['active'] and not crashed_recently):
            # Already crashed and grace period expired
            q.answer("💥 Слишком поздно! Джетпак уже разбился.", show_alert=True)
            return

        # Cashout!
        coeff = game['current']
        bet = game['bet']
        crash = game['crash']
        game['active'] = False

        winnings = int(bet * coeff)
        add_coins(uid, winnings)
        log_game(uid, "Джетпак", json.dumps({'bet': bet, 'crash': crash, 'collect': coeff, 'result': 'collect'}), winnings, True)
        row = get_user(uid)
        profit = winnings - bet

        # Update record
        if coeff > row[5]:
            set_field(uid, 'jetpack_best', coeff)
        row = get_user(uid)

        q.edit_message_text(
            f"✅ Забрали на {coeff:.2f}x!\n💰 Выигрыш: {winnings} монет | Прибыль: +{profit}\n💰 Баланс: {row[2]} монет\n(Краш был бы на {crash:.2f}x)",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Играть снова", callback_data='jp_menu')],
                [InlineKeyboardButton("🔙 Главное меню", callback_data='main_menu')]
            ])
        )

# ─────────── СООБЩЕНИЯ ───────────

def handle_text(update: Update, context: CallbackContext):
    uid = update.effective_user.id
    text = update.message.text.strip()
    state = context.user_data.get('state', '')

    if state == 'hourly_guess':
        try:
            guess = int(text)
            if guess < 1 or guess > 3:
                update.message.reply_text("❌ Введите число от 1 до 3!")
                return
            if not can_claim_hourly(uid):
                update.message.reply_text(f"⏰ Подождите ещё {time_until_hourly(uid)}")
                context.user_data['state'] = ''
                return
            actual = random.randint(1, 3)
            set_field(uid, 'last_hourly', datetime.now().isoformat())
            if guess == actual:
                add_coins(uid, 100)
                row = get_user(uid)
                update.message.reply_text(f"🎉 Правильно! Загадано: {actual}\n+100 монет!\n💰 Баланс: {row[2]} монет")
            else:
                update.message.reply_text(f"😔 Неверно. Загадано: {actual}\nПопробуйте снова через час.")
        except ValueError:
            update.message.reply_text("❌ Введите число от 1 до 3!")
            return
        context.user_data['state'] = ''

    elif state == 'promo':
        context.user_data['state'] = ''
        back_kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Главное меню", callback_data='main_menu')]])
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute('SELECT reward, max_uses, uses FROM promocodes WHERE code=?', (text,))
        promo = c.fetchone()
        if promo:
            reward, max_uses, uses = promo
            if max_uses is None or uses < max_uses:
                add_coins(uid, reward)
                c.execute('UPDATE promocodes SET uses=uses+1 WHERE code=?', (text,))
                conn.commit()
                row = get_user(uid)
                update.message.reply_text(f"🎉 Промокод активирован! +{reward} монет!\n💰 Баланс: {row[2]} монет", reply_markup=back_kb)
            else:
                update.message.reply_text("❌ Промокод уже исчерпан.", reply_markup=back_kb)
        else:
            update.message.reply_text("❌ Промокод не найден.", reply_markup=back_kb)
        conn.close()

    elif state == 'cf_bet':
        try:
            amount = int(text)
            row = get_user(uid)
            if amount <= 0:
                update.message.reply_text("❌ Ставка должна быть больше 0! Введите снова:",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='cf_menu')]]))
                return
            if amount > row[2]:
                update.message.reply_text(f"❌ Недостаточно монет! У вас {row[2]}. Введите меньшую сумму:",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='cf_menu')]]))
                return
            context.user_data['state'] = ''
            context.user_data['cf_bet'] = amount
            context.user_data['cf_active'] = False
            context.user_data['cf_coeff'] = 1.0
            update.message.reply_text(
                f"🪙 Монетка\n💰 Баланс: {row[2]} монет\nСтавка: {amount} монет",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("▶️ Начать игру", callback_data='cf_start')],
                    [InlineKeyboardButton(f"💰 Изменить ставку ({amount} монет)", callback_data='cf_set_bet')],
                    [InlineKeyboardButton("🔙 Главное меню", callback_data='main_menu')]
                ])
            )
        except ValueError:
            update.message.reply_text("❌ Введите корректное целое число!")

    elif state == 'miner_bet':
        try:
            amount = int(text)
            row = get_user(uid)
            if amount <= 0:
                update.message.reply_text("❌ Ставка должна быть больше 0! Введите снова:",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='miner_menu')]]))
                return
            if amount > row[2]:
                update.message.reply_text(f"❌ Недостаточно монет! У вас {row[2]}. Введите меньшую сумму:",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='miner_menu')]]))
                return
            context.user_data['state'] = ''
            context.user_data['miner_bet'] = amount
            mines = context.user_data.get('miner_mines', 5)
            update.message.reply_text(
                f"⛏️ Минёр\n💰 Баланс: {row[2]} монет\nСтавка: {amount} монет | Мин: {mines}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("▶️ Начать игру", callback_data='miner_start')],
                    [InlineKeyboardButton(f"💰 Изменить ставку ({amount})", callback_data='miner_set_bet')],
                    [InlineKeyboardButton(f"💣 Изменить мины ({mines})", callback_data='miner_set_mines')],
                    [InlineKeyboardButton("🔙 Назад", callback_data='games_menu')]
                ])
            )
        except ValueError:
            update.message.reply_text("❌ Введите корректное целое число!")

    elif state == 'miner_mines':
        try:
            count = int(text)
            if count < 3 or count > 24:
                update.message.reply_text("❌ Введите число от 3 до 24:",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='miner_menu')]]))
                return
            context.user_data['state'] = ''
            context.user_data['miner_mines'] = count
            bet = context.user_data.get('miner_bet', 0)
            row = get_user(uid)
            can_start = bet > 0
            update.message.reply_text(
                f"✅ Мин: {count}\n💰 Баланс: {row[2]} монет | Ставка: {bet}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("▶️ Начать игру", callback_data='miner_start') if can_start
                     else InlineKeyboardButton("▶️ Начать (сделайте ставку)", callback_data='miner_need_bet')],
                    [InlineKeyboardButton(f"💰 Изменить ставку ({bet})", callback_data='miner_set_bet')],
                    [InlineKeyboardButton(f"💣 Изменить мины ({count})", callback_data='miner_set_mines')],
                    [InlineKeyboardButton("🔙 Назад", callback_data='games_menu')]
                ])
            )
        except ValueError:
            update.message.reply_text("❌ Введите корректное целое число!")

    elif state == 'jp_bet':
        try:
            amount = int(text)
            row = get_user(uid)
            if amount <= 0:
                update.message.reply_text("❌ Ставка должна быть больше 0! Введите снова:",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='jp_menu')]]))
                return
            if amount > row[2]:
                update.message.reply_text(f"❌ Недостаточно монет! У вас {row[2]}. Введите меньшую сумму:",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='jp_menu')]]))
                return
            context.user_data['state'] = ''
            context.user_data['jp_bet'] = amount
            auto = context.user_data.get('jp_auto', 0.0)
            auto_txt = f"{auto:.2f}x" if auto > 1.0 else "Выкл"
            update.message.reply_text(
                f"🚀 Джетпак\n💰 Баланс: {row[2]} монет\nСтавка: {amount} монет | Авто-сбор: {auto_txt}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("▶️ Начать игру", callback_data='jp_start')],
                    [InlineKeyboardButton(f"💰 Ставка ({amount})", callback_data='jp_set_bet'),
                     InlineKeyboardButton(f"🤖 Авто ({auto_txt})", callback_data='jp_set_auto')],
                    [InlineKeyboardButton("🔙 Назад", callback_data='games_menu')]
                ])
            )
        except ValueError:
            update.message.reply_text("❌ Введите корректное целое число!")

    elif state == 'jp_auto':
        try:
            val = float(text.replace(',', '.'))
            if val < 0:
                update.message.reply_text("❌ Введите число >= 0! Введите снова:",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='jp_menu')]]))
                return
            context.user_data['state'] = ''
            context.user_data['jp_auto'] = val
            bet = context.user_data.get('jp_bet', 0)
            auto_txt = f"{val:.2f}x" if val > 1.0 else "Выкл"
            row = get_user(uid)
            update.message.reply_text(
                f"🚀 Джетпак\n💰 Баланс: {row[2]} монет\nСтавка: {bet} монет | Авто-сбор: {auto_txt}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("▶️ Начать игру", callback_data='jp_start') if bet > 0
                     else InlineKeyboardButton("▶️ Начать (сделайте ставку)", callback_data='jp_need_bet')],
                    [InlineKeyboardButton(f"💰 Ставка ({bet})", callback_data='jp_set_bet'),
                     InlineKeyboardButton(f"🤖 Авто ({auto_txt})", callback_data='jp_set_auto')],
                    [InlineKeyboardButton("🔙 Назад", callback_data='games_menu')]
                ])
            )
        except ValueError:
            update.message.reply_text("❌ Введите корректное число (например 2.5 или 2,5):",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='jp_menu')]]))

    elif state == 'slots_bet':
        try:
            amount = int(text)
            row = get_user(uid)
            if amount <= 0:
                update.message.reply_text("❌ Ставка должна быть больше 0! Введите снова:",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='slots_menu')]]))
                return
            if amount > row[2]:
                update.message.reply_text(f"❌ Недостаточно монет! У вас {row[2]}. Введите меньшую сумму:",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='slots_menu')]]))
                return
            context.user_data['state'] = ''
            context.user_data['slots_bet'] = amount
            update.message.reply_text(
                f"🎰 Слоты\n💰 Баланс: {row[2]} монет\nСтавка: {amount} монет",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🎰 Крутить!", callback_data='slots_spin')],
                    [InlineKeyboardButton(f"💰 Изменить ставку ({amount})", callback_data='slots_set_bet')],
                    [InlineKeyboardButton("🔙 Назад", callback_data='games_menu')]
                ])
            )
        except ValueError:
            update.message.reply_text("❌ Введите корректное целое число!")

    elif state == 'tower_bet':
        try:
            amount = int(text)
            row = get_user(uid)
            if amount <= 0:
                update.message.reply_text("❌ Ставка должна быть больше 0! Введите снова:",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='tower_menu')]]))
                return
            if amount > row[2]:
                update.message.reply_text(f"❌ Недостаточно монет! У вас {row[2]}. Введите меньшую сумму:",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='tower_menu')]]))
                return
            context.user_data['state'] = ''
            context.user_data['tower_bet'] = amount
            update.message.reply_text(
                f"🗼 Башня\n💰 Баланс: {row[2]} монет\nСтавка: {amount} монет",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("▶️ Начать", callback_data='tower_start')],
                    [InlineKeyboardButton(f"💰 Изменить ставку ({amount})", callback_data='tower_set_bet')],
                    [InlineKeyboardButton("🔙 Назад", callback_data='games_menu')]
                ])
            )
        except ValueError:
            update.message.reply_text("❌ Введите корректное целое число!")

    else:
        update.message.reply_text("Используйте кнопки. Напишите /start для начала.")

# ─────────── MAIN ───────────

def main():
    init_db()
    token = os.getenv('BOT_TOKEN', 'YOUR_BOT_TOKEN')
    # Optimize for lag: increased timeouts and request parameters
    updater = Updater(token=token, use_context=True, request_kwargs={
        'read_timeout': 10,
        'connect_timeout': 10
    })
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CallbackQueryHandler(btn))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_text))
    print("Bot started!")
    # clean=True to skip old updates that could cause lag spikes on restart
    updater.start_polling(drop_pending_updates=True, timeout=30)
    updater.idle()

if __name__ == '__main__':
    main()
