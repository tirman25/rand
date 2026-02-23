import os
import sqlite3
import random
import time
import threading
import json
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext, CallbackQueryHandler

# ─────────── КОНФИГУРАЦИЯ ───────────
ADMINS = [5237005284]  # ID админа

GAME_EMOJIS = {
    'Монетка': '🪙',
    'Минёр': '⛏️',
    'Джетпак': '🚀',
    'Слоты': '🎰',
    'Башня': '🗼',
    'Свечи': '📊',
}

# Список всех игр для фильтров (всегда доступен)
ALL_GAMES = list(GAME_EMOJIS.keys())

def format_game_detail(gname, details_raw, amount, is_win, created_at, is_rolled_back=False):
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
        traps_count = data.get('traps_count', 1)
        result = data.get('result', '')
        lines.append(f"💰 Ставка: {bet} | Этажей пройдено: {floor_reached}/{TOWER_FLOORS} | Бомб: {traps_count}")
        lines.append(sep)
        lines.append("🗺️ Карта башни (💣=ловушка):")
        for f in range(min(len(traps), TOWER_FLOORS) - 1, -1, -1):
            if f >= len(traps):
                continue
            floor_traps = traps[f]
            cells = []
            for c in range(3):
                # Для совместимости: если floor_traps - число, преобразуем в список
                if isinstance(floor_traps, int):
                    floor_traps = [floor_traps]
                cells.append("💣" if c in floor_traps else "⬜")
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

    elif gname == 'Свечи':
        bet = data.get('bet', '?')
        moves = data.get('moves', [])
        coeff = data.get('coeff', 1)
        result = data.get('result', '')
        lines.append(f"💰 Ставка: {bet} | Коэффициент: x{coeff:.1f}")
        if moves:
            lines.append(f"📊 Ходы: {' → '.join(moves)}")

    lines.append(sep)
    # Форматируем дату правильно
    if created_at:
        # created_at может быть строкой в формате ISO или timestamp
        try:
            if isinstance(created_at, str):
                # Убираем пробелы и проверяем формат
                created_at = created_at.strip()
                # Если есть T (ISO формат) или пробел
                if 'T' in created_at:
                    date_part = created_at.split('T')[0]
                elif ' ' in created_at:
                    date_part = created_at.split(' ')[0]
                else:
                    date_part = created_at[:10] if len(created_at) >= 10 else created_at
                
                # Проверяем, что дата валидна (формат YYYY-MM-DD)
                if len(date_part) == 10 and date_part.count('-') == 2:
                    lines.append(f"📅 {date_part}")
                else:
                    lines.append(f"📅 {created_at}")
            else:
                # Если это число (timestamp)
                try:
                    dt = datetime.fromtimestamp(float(created_at))
                    lines.append(f"📅 {dt.strftime('%Y-%m-%d')}")
                except:
                    lines.append(f"📅 {created_at}")
        except Exception as e:
            lines.append(f"📅 Дата неизвестна")
    else:
        lines.append(f"📅 Дата неизвестна")

    # Проверяем is_rolled_back: 1 = откатан, 0 или None = не откатан
    if is_game_rolled_back(is_rolled_back):
        lines.append(sep)
        lines.append("↩️ Эта игра была откачена")

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
        is_rolled_back INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute("PRAGMA table_info(users)")
    cols = [r[1] for r in c.fetchall()]
    needed = ['last_hourly', 'jetpack_best', 'jetpack_auto', 'referrer_id', 'total_refs', 'last_wheel', 'registration_time', 'last_activity', 'daily_refs', 'last_daily_ref_reset', 'is_blocked', 'channel_subscribed', 'channel_reward_received', 'channel_last_check']
    if cols and not all(col in cols for col in needed):
        # Migrate: rebuild table with all columns
        c.execute("ALTER TABLE users RENAME TO users_old")
        c.execute('''CREATE TABLE users (
            id INTEGER PRIMARY KEY, username TEXT DEFAULT '',
            coins INTEGER DEFAULT 500, last_hourly TEXT DEFAULT NULL,
            consecutive_wins INTEGER DEFAULT 0, jetpack_best REAL DEFAULT 0.0,
            jetpack_auto REAL DEFAULT 0.0,
            referrer_id INTEGER DEFAULT NULL, total_refs INTEGER DEFAULT 0,
            last_wheel TEXT DEFAULT NULL,
            registration_time TEXT DEFAULT NULL,
            last_activity TEXT DEFAULT NULL,
            daily_refs INTEGER DEFAULT 0,
            last_daily_ref_reset TEXT DEFAULT NULL,
            is_blocked INTEGER DEFAULT 0,
            channel_subscribed INTEGER DEFAULT 0,
            channel_reward_received INTEGER DEFAULT 0,
            channel_last_check TEXT DEFAULT NULL)''')
        try:
            c.execute('''INSERT INTO users (id, username, coins, last_hourly, consecutive_wins, jetpack_best, jetpack_auto, referrer_id, total_refs, last_wheel, registration_time, last_activity)
                         SELECT id, username, coins,
                                COALESCE(last_hourly, NULL),
                                COALESCE(consecutive_wins, 0),
                                COALESCE(jetpack_best, 0.0),
                                COALESCE(jetpack_auto, 0.0),
                                COALESCE(referrer_id, NULL),
                                COALESCE(total_refs, 0),
                                COALESCE(last_wheel, NULL),
                                COALESCE(registration_time, NULL),
                                COALESCE(last_activity, NULL)
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
            last_wheel TEXT DEFAULT NULL,
            registration_time TEXT DEFAULT NULL,
            last_activity TEXT DEFAULT NULL,
            daily_refs INTEGER DEFAULT 0,
            last_daily_ref_reset TEXT DEFAULT NULL,
            is_blocked INTEGER DEFAULT 0,
            channel_subscribed INTEGER DEFAULT 0,
            channel_reward_received INTEGER DEFAULT 0,
            channel_last_check TEXT DEFAULT NULL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS promocodes (
        code TEXT PRIMARY KEY, reward INTEGER,
        uses INTEGER DEFAULT 0, max_uses INTEGER DEFAULT NULL)''')

    # Расширенная таблица промокодов
    c.execute("PRAGMA table_info(promocodes)")
    promo_cols = [r[1] for r in c.fetchall()]
    promo_needed = ['deleted', 'max_per_user', 'created_by', 'created_at']
    if not promo_cols or not all(col in promo_cols for col in promo_needed):
        c.execute("ALTER TABLE promocodes RENAME TO promocodes_old")
        c.execute('''CREATE TABLE promocodes (
            code TEXT PRIMARY KEY,
            reward INTEGER,
            uses INTEGER DEFAULT 0,
            max_uses INTEGER DEFAULT NULL,
            max_per_user INTEGER DEFAULT 1,
            deleted INTEGER DEFAULT 0,
            created_by INTEGER DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        try:
            c.execute('''INSERT INTO promocodes (code, reward, uses, max_uses)
                         SELECT code, reward, uses, max_uses FROM promocodes_old''')
        except Exception:
            pass
        c.execute("DROP TABLE promocodes_old")
    else:
        c.execute('''CREATE TABLE IF NOT EXISTS promocodes (
            code TEXT PRIMARY KEY,
            reward INTEGER,
            uses INTEGER DEFAULT 0,
            max_uses INTEGER DEFAULT NULL,
            max_per_user INTEGER DEFAULT 1,
            deleted INTEGER DEFAULT 0,
            created_by INTEGER DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    # Новые таблицы
    c.execute('''CREATE TABLE IF NOT EXISTS promo_usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT,
        uid INTEGER,
        used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (code) REFERENCES promocodes(code),
        FOREIGN KEY (uid) REFERENCES users(id))''')

    # Миграция для добавления created_at в promo_usage если её нет
    c.execute("PRAGMA table_info(promo_usage)")
    pu_cols = [r[1] for r in c.fetchall()]
    if pu_cols and 'created_at' not in pu_cols:
        c.execute("ALTER TABLE promo_usage ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")

    c.execute('''CREATE TABLE IF NOT EXISTS admin_broadcasts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        message_type TEXT DEFAULT 'text',
        content TEXT,
        file_id TEXT,
        scheduled_at TIMESTAMP,
        sent_at TIMESTAMP,
        status TEXT DEFAULT 'pending',
        created_by INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    c.execute('''CREATE TABLE IF NOT EXISTS admin_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        admin_id INTEGER,
        action TEXT,
        target_type TEXT,
        target_id INTEGER,
        details TEXT,
        is_rolled_back INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    # Миграция для удаления промокода glino228 и записей использования
    c.execute('DELETE FROM promo_usage WHERE code=?', ('glino228',))
    c.execute('DELETE FROM promocodes WHERE code=?', ('glino228',))

    # Миграция таблицы admin_logs если она существует в старом формате
    c.execute("PRAGMA table_info(admin_logs)")
    log_cols = [r[1] for r in c.fetchall()]
    if log_cols and 'admin_id' not in log_cols:
        # Таблица существует но без admin_id - пересоздаём
        c.execute("ALTER TABLE admin_logs RENAME TO admin_logs_old")
        c.execute('''CREATE TABLE admin_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER,
            action TEXT,
            target_type TEXT,
            target_id INTEGER,
            details TEXT,
            is_rolled_back INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        try:
            c.execute('''INSERT INTO admin_logs (action, target_type, target_id, details, created_at)
                         SELECT action, target_type, target_id, details, created_at FROM admin_logs_old''')
        except Exception:
            pass
        c.execute("DROP TABLE admin_logs_old")
    elif log_cols and 'is_rolled_back' not in log_cols:
        # Добавляем поле is_rolled_back если его нет
        c.execute("ALTER TABLE admin_logs ADD COLUMN is_rolled_back INTEGER DEFAULT 0")

    # Миграция таблицы admins
    c.execute("PRAGMA table_info(admins)")
    admin_cols = [r[1] for r in c.fetchall()]
    if admin_cols and 'added_by' not in admin_cols:
        # Таблица существует но в старом формате - пересоздаём
        c.execute("ALTER TABLE admins RENAME TO admins_old")
        c.execute('''CREATE TABLE admins (
            id INTEGER PRIMARY KEY,
            added_by INTEGER,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        try:
            c.execute('''INSERT INTO admins (id)
                         SELECT id FROM admins_old''')
        except Exception:
            pass
        c.execute("DROP TABLE admins_old")
    else:
        c.execute('''CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY,
            added_by INTEGER,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    # Добавляем админа по умолчанию если его нет
    c.execute("INSERT OR IGNORE INTO admins (id, added_by) VALUES (?, ?)", (ADMINS[0] if ADMINS else 0, 0))

    # Миграция таблицы game_history для добавления is_rolled_back
    c.execute("PRAGMA table_info(game_history)")
    gh_cols = [r[1] for r in c.fetchall()]
    if gh_cols and 'is_rolled_back' not in gh_cols:
        c.execute("ALTER TABLE game_history ADD COLUMN is_rolled_back INTEGER DEFAULT 0")

    # Исправление null значений в is_rolled_back - заменяем на 0
    c.execute("UPDATE game_history SET is_rolled_back = 0 WHERE is_rolled_back IS NULL")
    c.execute("UPDATE admin_logs SET is_rolled_back = 0 WHERE is_rolled_back IS NULL")

    conn.commit(); conn.close()

def get_user(uid):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute('SELECT * FROM users WHERE id=?', (uid,))
    row = c.fetchone()
    if row is None:
        c.execute('INSERT INTO users (id, registration_time) VALUES (?, ?)', (uid, datetime.now().isoformat()))
        conn.commit()
        row = (uid, '', 500, None, 0, 0.0, 0.0, None, 0, None, datetime.now().isoformat(), None, 0, None, 0, 0, 0, None)
    conn.close()
    return row

def update_last_activity(uid):
    """Update user's last activity timestamp and check channel subscription"""
    set_field(uid, 'last_activity', datetime.now().isoformat())

    # Check channel subscription status periodically (1/20 chance)
    # Только если пользователь уже получил награду
    if random.random() < 0.05:
        row = get_user(uid)
        if len(row) > 16 and row[16]:  # channel_reward_received
            # User received reward, check if still subscribed
            from telegram import Bot

            try:
                bot = Bot(token=os.getenv('BOT_TOKEN', 'YOUR_BOT_TOKEN'))
                is_subscribed = check_channel_subscription_sync(bot, uid)
                update_channel_subscription_status(uid, is_subscribed)

                if not is_subscribed:
                    # User unsubscribed, remove 200 coins
                    row2 = get_user(uid)
                    if row2[2] >= 200:
                        add_coins(uid, -200)
                    else:
                        # Если монет меньше 200, списываем все
                        add_coins(uid, -row2[2])
                    set_field(uid, 'channel_reward_received', 0)
                    try:
                        bot.send_message(uid, "⚠️ Вы отписались от канала @dihwn_tgk!\n-200 монет списано с баланса.")
                    except Exception:
                        pass
            except Exception as e:
                print(f"Error in subscription check: {e}")

def check_and_award_pending_referrals(uid):
    """Check if user is now eligible for referral bonus and award if so"""
    row = get_user(uid)

    # Check if user has a referrer and is now eligible for bonus
    if len(row) > 7 and row[7] is not None and can_receive_referral_bonus(uid):
        referrer_id = row[7]

        # Award bonus to referrer
        add_coins(referrer_id, 200)

        # Update total refs count for referrer
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('UPDATE users SET total_refs=total_refs+1 WHERE id=?', (referrer_id,))
        conn.commit()
        conn.close()

        # Notify referrer
        try:
            from telegram import Bot
            bot = Bot(token=os.getenv('BOT_TOKEN', 'YOUR_BOT_TOKEN'))
            bot.send_message(referrer_id, f"👥 Ваш реферал стал активным!\n+200 монет на баланс! 🎉")
        except Exception:
            pass

        return True

    return False

def can_receive_referral_bonus(uid):
    """Check if user can receive referral bonus based on activity"""
    row = get_user(uid)
    if len(row) < 12 or not row[11]:  # no registration_time
        return False

    registration_time = datetime.fromisoformat(row[11])
    time_since_registration = datetime.now() - registration_time

    # User must be registered for at least 5 minutes to receive referral bonus
    return time_since_registration.total_seconds() >= 300  # 5 minutes

def reset_daily_refs_if_needed(uid):
    """Reset daily refs counter if new day has started"""
    row = get_user(uid)
    if len(row) < 14 or not row[13]:  # no last_daily_ref_reset
        # First time - set to today
        set_field(uid, 'last_daily_ref_reset', datetime.now().date().isoformat())
        set_field(uid, 'daily_refs', 0)
        return True

    last_reset_date = datetime.fromisoformat(row[13]).date()
    today = datetime.now().date()

    if last_reset_date < today:
        # New day - reset counter
        set_field(uid, 'last_daily_ref_reset', today.isoformat())
        set_field(uid, 'daily_refs', 0)
        return True

    return False

def can_add_referral(referrer_id):
    """Check if referrer can add more referrals today"""
    reset_daily_refs_if_needed(referrer_id)
    row = get_user(referrer_id)

    if len(row) < 13:
        return True  # no daily_refs field yet, so allow

    daily_refs = row[12] or 0
    max_daily_refs = 10  # maximum 10 referrals per day

    return daily_refs < max_daily_refs

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

def get_history_paged(uid, page=0, page_size=5, rolled_back=None, game_name=None, is_win=None):
    """Get user's game history with pagination and optional filters

    Args:
        uid: user id
        page: page number (0-indexed)
        page_size: number of items per page (use -1 for all)
        rolled_back: None (all), False (not rolled back), True (rolled back)
        game_name: filter by game name (None = all games)
        is_win: True (wins only), False (losses only), None (all)
    """
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()

    # Build WHERE clause
    conditions = ["uid=?"]
    params = [uid]
    
    if rolled_back is not None:
        if rolled_back:
            conditions.append("is_rolled_back=1")
        else:
            conditions.append("(is_rolled_back=0 OR is_rolled_back IS NULL)")
    
    if game_name:
        conditions.append("game_name=?")
        params.append(game_name)
    
    if is_win is not None:
        conditions.append("is_win=?")
        params.append(1 if is_win else 0)
    
    where_clause = " AND ".join(conditions)
    
    # Get total count
    c.execute(f'SELECT COUNT(*) FROM game_history WHERE {where_clause}', params)
    total = c.fetchone()[0]
    
    # Get rows
    if page_size > 0:
        offset = page * page_size
        c.execute(f'SELECT id, game_name, amount, is_win, is_rolled_back, created_at FROM game_history WHERE {where_clause} ORDER BY id DESC LIMIT ? OFFSET ?',
                  params + [page_size, offset])
    else:
        # page_size = -1 means get all
        c.execute(f'SELECT id, game_name, amount, is_win, is_rolled_back, created_at FROM game_history WHERE {where_clause} ORDER BY id DESC', params)
    
    rows = c.fetchall()
    conn.close()
    return rows, total

def get_all_games():
    """Get list of all game names"""
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute('SELECT DISTINCT game_name FROM game_history ORDER BY game_name')
    games = [r[0] for r in c.fetchall()]
    conn.close()
    return games

def get_game_info(game_id):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute('SELECT game_name, details, amount, is_win, is_rolled_back, created_at FROM game_history WHERE id=?', (game_id,))
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

# ─────────── ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ───────────

def is_game_rolled_back(is_rolled_back):
    """Check if game is rolled back. Returns True if is_rolled_back == 1, False otherwise (including None)"""
    # Обрабатываем разные типы данных
    if is_rolled_back is None:
        return False
    if isinstance(is_rolled_back, int):
        return is_rolled_back == 1
    if isinstance(is_rolled_back, str):
        return is_rolled_back == '1' or is_rolled_back == 'True'
    return bool(is_rolled_back)

# ─────────── KEYBOARDS ───────────

def main_menu_kb(uid=None):
    kb = [
        [InlineKeyboardButton("🎮 Игры", callback_data='games_menu'),
         InlineKeyboardButton("👤 Профиль", callback_data='profile')],
        [InlineKeyboardButton("🏆 Топ игроков", callback_data='leaderboard'),
         InlineKeyboardButton("🎁 Бонус", callback_data='hourly_bonus')],
        [InlineKeyboardButton("🎡 Колесо фортуны", callback_data='wheel_menu')],
        [InlineKeyboardButton("🎫 Промокод", callback_data='promo_enter'),
         InlineKeyboardButton("👥 Реферал", callback_data='referral')]
    ]

    # Добавляем кнопку админ-панели только для админов
    if uid is not None and is_admin(uid):
        kb.append([InlineKeyboardButton("🔧 Админ-Панель", callback_data='admin_menu')])

    return InlineKeyboardMarkup(kb)

def games_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🪙 Монетка", callback_data='cf_menu'),
         InlineKeyboardButton("🎰 Слоты",   callback_data='slots_menu')],
        [InlineKeyboardButton("⛏️ Минёр",   callback_data='miner_menu'),
         InlineKeyboardButton("🗼 Башня",    callback_data='tower_menu')],
        [InlineKeyboardButton("🚀 Джетпак", callback_data='jp_menu'),
         InlineKeyboardButton("📊 Свечи",    callback_data='candles_menu')],
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
TOWER_FLOORS = 12  # Увеличено с 8 до 12 этажей

# Коэффициенты для 1 бомбы (стандартный режим)
# Расчёт: каждый этаж увеличивает риск, но и награду
# Вероятность пройти этаж = 2/3 (66.7%)
# Матожидание: 0.667 * coeff_next должно быть >= 1 для привлекательности
TOWER_COEFFS_1BOMB = [1.5, 2.0, 2.8, 4.0, 5.5, 8.0, 12.0, 18.0, 28.0, 42.0, 65.0, 100.0]

# Коэффициенты для 2 бомб (хардкорный режим)
# Вероятность пройти этаж = 1/3 (33.3%) - выше риск, выше награда
# Матожидание: 0.333 * coeff_next должно быть >= 1
TOWER_COEFFS_2BOMBS = [2.0, 4.0, 8.0, 16.0, 32.0, 64.0, 130.0, 260.0, 520.0, 1050.0, 2100.0, 4200.0]

def tower_keyboard(floor, traps_count=1):
    """Generate tower keyboard. floor = current floor (0-indexed). traps_count = 1 or 2 bombs per floor."""
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
    
    # Выбираем коэффициенты в зависимости от количества бомб
    coeffs = TOWER_COEFFS_2BOMBS if traps_count == 2 else TOWER_COEFFS_1BOMB
    coeff = coeffs[floor] if floor < TOWER_FLOORS else coeffs[-1]
    
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
    """Calculate miner coefficient with balanced economy.
    Higher commission for more mines to prevent abuse."""
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

    # Dynamic commission based on number of mines:
    # 3 mines: 8%, 5 mines: 10%, 10 mines: 12%, 15 mines: 14%, 20-24 mines: 15%
    if mines <= 3:
        commission = 0.92
    elif mines <= 5:
        commission = 0.90
    elif mines <= 10:
        commission = 0.88
    elif mines <= 15:
        commission = 0.86
    else:
        commission = 0.85

    return round(coeff * commission, 2)

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

def is_admin(uid):
    """Check if user is admin"""
    if uid in ADMINS:
        return True
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT id FROM admins WHERE id=?', (uid,))
    result = c.fetchone()
    conn.close()
    return result is not None

def start(update: Update, context: CallbackContext):
    uid = update.effective_user.id
    user = update.effective_user
    is_new = get_user(uid)[2] == 500  # freshly created

    # Save username
    uname = user.username or user.first_name or ''
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute('UPDATE users SET username=? WHERE id=?', (uname, uid))
    conn.commit(); conn.close()

    # Handle referral with simple bot protection
    args = context.args
    if args and args[0].startswith('ref_'):
        try:
            referrer_id = int(args[0].replace('ref_', ''))
            if referrer_id != uid:
                row = get_user(uid)
                if row[7] is None:  # not yet referred
                    # Store referrer_id temporarily in user_data for confirmation
                    context.user_data['pending_referrer'] = referrer_id

                    # Show simple human verification
                    update.message.reply_text(
                        "🤖 Проверка: Вы человек?",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("✅ Да, я человек", callback_data='confirm_human_yes')],
                            [InlineKeyboardButton("❌ Нет, я бот", callback_data='confirm_human_no')]
                        ])
                    )
                    return
                else:
                    update.message.reply_text("⚠️ Вы уже были приглашены кем-то ранее.")
        except (ValueError, IndexError):
            pass

    row = get_user(uid)
    update.message.reply_text(
        f"👋 Добро пожаловать, {uname}!\n💰 Баланс: {row[2]} монет\n\nВыберите действие:",
        reply_markup=main_menu_kb(uid)
    )

def admin_command(update: Update, context: CallbackContext):
    """Admin panel command"""
    uid = update.effective_user.id
    if not is_admin(uid):
        update.message.reply_text("❌ У вас нет доступа к админ-панели!")
        return

    update.message.reply_text(
        "🔧 Админ-панель\n\nВыберите действие:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 Статистика", callback_data='admin_stats')],
            [InlineKeyboardButton("👥 Пользователи", callback_data='admin_users')],
            [InlineKeyboardButton("📢 Рассылки", callback_data='admin_broadcasts')],
            [InlineKeyboardButton("🎫 Промокоды", callback_data='admin_promos')],
            [InlineKeyboardButton("👨‍💻 Админы", callback_data='admin_admins')],
            [InlineKeyboardButton("📜 Логи", callback_data='admin_logs')],
            [InlineKeyboardButton("💰 Глобальный баланс", callback_data='admin_global_balance')],
            [InlineKeyboardButton("🔙 Выход", callback_data='main_menu')]
        ])
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

    # Check if user is blocked (except for admin functions)
    if not d.startswith('admin_') and not is_admin(uid):
        row = get_user(uid)
        is_blocked = row[14] if len(row) > 14 else 0
        if is_blocked:
            try:
                q.edit_message_text(
                    "🚫 Вы заблокированы!\n\nОбратитесь к администратору.",
                    reply_markup=None
                )
            except Exception:
                pass
            return

    try:
        _btn_handler(q, uid, d, context)
    except Exception as e:
        if 'Message is not modified' in str(e):
            pass  # silently ignore duplicate clicks
        else:
            raise

# ─────────── ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ НОВЫХ ФУНКЦИЙ ───────────

# ─────────── CHANNEL SUBSCRIPTION ───────────
CHANNEL_USERNAME = 'dihwn_tgk'

def check_channel_subscription_sync(bot, uid):
    """Check if user is subscribed to the channel (sync version for ptb 13.x)"""
    try:
        # Для python-telegram-bot 13.x используем синхронный метод
        chat_member = bot.get_chat_member(chat_id=f'@{CHANNEL_USERNAME}', user_id=uid)
        status = chat_member.status
        print(f"DEBUG: User {uid} subscription status: {status}")
        return status in ['member', 'administrator', 'creator']
    except Exception as e:
        print(f"Error checking subscription: {e}")
        # Если бот не админ канала, возвращаем True для теста
        # Уберите эту строку после добавления бота в админы канала!
        return False

async def check_channel_subscription(bot, uid):
    """Check if user is subscribed to the channel (async version)"""
    try:
        member = await bot.get_chat_member(f'@{CHANNEL_USERNAME}', uid)
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        print(f"Error checking subscription (async): {e}")
        return False

def update_channel_subscription_status(uid, is_subscribed):
    """Update user's channel subscription status"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE users SET channel_subscribed=?, channel_last_check=? WHERE id=?',
              (1 if is_subscribed else 0, datetime.now().isoformat(), uid))
    conn.commit()
    conn.close()

def get_channel_reward_status(uid):
    """Check if user received channel reward"""
    row = get_user(uid)
    return row[16] if len(row) > 16 else 0  # channel_reward_received

def set_channel_reward_received(uid):
    """Mark that user received channel reward"""
    set_field(uid, 'channel_reward_received', 1)

# ─────────── USER MANAGEMENT ───────────
def block_user(uid):
    """Block user"""
    set_field(uid, 'is_blocked', 1)

def unblock_user(uid):
    """Unblock user"""
    set_field(uid, 'is_blocked', 0)

def is_user_blocked(uid):
    """Check if user is blocked"""
    row = get_user(uid)
    return row[14] if len(row) > 14 else 0  # is_blocked

# ─────────── PROMO CODES EXTENDED ───────────
def create_promocode(code, reward, max_uses=None, max_per_user=1, created_by=None):
    """Create a new promocode"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute('''INSERT INTO promocodes (code, reward, max_uses, max_per_user, created_by)
                     VALUES (?, ?, ?, ?, ?)''', (code, reward, max_uses, max_per_user, created_by))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def delete_promocode(code):
    """Delete promocode completely"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Delete from promocodes table
    c.execute('DELETE FROM promocodes WHERE code=?', (code,))
    # Delete from promo_usage table
    c.execute('DELETE FROM promo_usage WHERE code=?', (code,))
    conn.commit()
    conn.close()

def clear_all_promocodes():
    """Delete ALL promocodes and their usage records"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Delete all promo usage records first
    c.execute('DELETE FROM promo_usage')
    # Delete all promocodes
    c.execute('DELETE FROM promocodes')
    conn.commit()
    conn.close()

def get_all_promocodes(include_deleted=False):
    """Get all promocodes"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if include_deleted:
        c.execute('SELECT * FROM promocodes ORDER BY created_at DESC')
    else:
        c.execute('SELECT * FROM promocodes WHERE deleted=0 ORDER BY created_at DESC')
    promocodes = c.fetchall()
    conn.close()
    return promocodes

def get_promocode_usage(code):
    """Get promocode usage statistics"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''SELECT pu.uid, u.username, pu.used_at FROM promo_usage pu
                 JOIN users u ON pu.uid = u.id
                 WHERE pu.code = ? ORDER BY pu.used_at DESC''', (code,))
    usage = c.fetchall()
    conn.close()
    return usage

def check_promocode_usage_count(uid, code):
    """Check how many times user used this promocode"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM promo_usage WHERE uid=? AND code=?', (uid, code))
    count = c.fetchone()[0]
    conn.close()
    return count

# ─────────── ADMIN LOGS ───────────
def log_admin_action(admin_id, action, target_type, target_id, details=None):
    """Log admin action"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''INSERT INTO admin_logs (admin_id, action, target_type, target_id, details)
                 VALUES (?, ?, ?, ?, ?)''', (admin_id, action, target_type, target_id, details))
    conn.commit()
    conn.close()

# ─────────── STATISTICS HELPER FUNCTIONS ───────────
def get_stats_by_period(period='all'):
    """Get statistics by time period: day, week, month, year, all"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Time filter
    time_filter = ""
    if period == 'day':
        time_filter = "WHERE created_at > date('now', '-1 day')"
    elif period == 'week':
        time_filter = "WHERE created_at > date('now', '-7 days')"
    elif period == 'month':
        time_filter = "WHERE created_at > date('now', '-1 month')"
    elif period == 'year':
        time_filter = "WHERE created_at > date('now', '-1 year')"

    # Build WHERE clause for game_history queries
    if time_filter:
        where_clause = time_filter.replace('WHERE ', '')
    else:
        where_clause = ""

    # Total users
    c.execute('SELECT COUNT(*) FROM users')
    total_users = c.fetchone()[0]

    # Active users (last 24 hours)
    c.execute('SELECT COUNT(*) FROM users WHERE last_activity > datetime("now", "-24 hours")')
    active_users = c.fetchone()[0]

    # Total coins in circulation
    c.execute('SELECT SUM(coins) FROM users')
    total_coins = c.fetchone()[0] or 0

    # Total games played
    if where_clause:
        c.execute(f'SELECT COUNT(*) FROM game_history WHERE {where_clause}')
    else:
        c.execute('SELECT COUNT(*) FROM game_history')
    total_games = c.fetchone()[0]

    # Total wins/losses
    if where_clause:
        c.execute(f'SELECT COUNT(*) FROM game_history WHERE {where_clause} AND is_win=1')
        total_wins = c.fetchone()[0]
        c.execute(f'SELECT COUNT(*) FROM game_history WHERE {where_clause} AND is_win=0')
        total_losses = c.fetchone()[0]
    else:
        c.execute('SELECT COUNT(*) FROM game_history WHERE is_win=1')
        total_wins = c.fetchone()[0]
        c.execute('SELECT COUNT(*) FROM game_history WHERE is_win=0')
        total_losses = c.fetchone()[0]

    # Total won/lost
    if where_clause:
        c.execute(f'SELECT SUM(CASE WHEN is_win=1 THEN amount ELSE 0 END), SUM(CASE WHEN is_win=0 THEN amount ELSE 0 END) FROM game_history WHERE {where_clause}')
    else:
        c.execute('SELECT SUM(CASE WHEN is_win=1 THEN amount ELSE 0 END), SUM(CASE WHEN is_win=0 THEN amount ELSE 0 END) FROM game_history')
    total_won, total_lost = c.fetchone()

    # New users registered (no created_at in users table, use registration_time)
    if where_clause:
        c.execute(f'SELECT COUNT(*) FROM users WHERE registration_time > date("now", "-1 day")' if period == 'day' else
                  f'SELECT COUNT(*) FROM users WHERE registration_time > date("now", "-7 days")' if period == 'week' else
                  f'SELECT COUNT(*) FROM users WHERE registration_time > date("now", "-1 month")' if period == 'month' else
                  f'SELECT COUNT(*) FROM users WHERE registration_time > date("now", "-1 year")' if period == 'year' else
                  'SELECT COUNT(*) FROM users')
    else:
        c.execute('SELECT COUNT(*) FROM users')
    new_users = c.fetchone()[0]

    # Promocodes used - use used_at column instead of created_at
    if where_clause:
        c.execute(f'SELECT COUNT(*) FROM promo_usage WHERE used_at > date("now", "-1 day")' if period == 'day' else
                  f'SELECT COUNT(*) FROM promo_usage WHERE used_at > date("now", "-7 days")' if period == 'week' else
                  f'SELECT COUNT(*) FROM promo_usage WHERE used_at > date("now", "-1 month")' if period == 'month' else
                  f'SELECT COUNT(*) FROM promo_usage WHERE used_at > date("now", "-1 year")' if period == 'year' else
                  'SELECT COUNT(*) FROM promo_usage')
    else:
        c.execute('SELECT COUNT(*) FROM promo_usage')
    promos_used = c.fetchone()[0]

    conn.close()

    return {
        'total_users': total_users,
        'active_users': active_users,
        'total_coins': total_coins,
        'total_games': total_games,
        'total_wins': total_wins,
        'total_losses': total_losses,
        'total_won': total_won or 0,
        'total_lost': total_lost or 0,
        'new_users': new_users,
        'promos_used': promos_used
    }

def get_game_stats_by_period(game_name, period='all'):
    """Get game statistics by time period"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Build time filter
    time_conditions = []
    if period == 'day':
        time_conditions.append("created_at > date('now', '-1 day')")
    elif period == 'week':
        time_conditions.append("created_at > date('now', '-7 days')")
    elif period == 'month':
        time_conditions.append("created_at > date('now', '-1 month')")
    elif period == 'year':
        time_conditions.append("created_at > date('now', '-1 year')")

    # Build WHERE clause
    where_parts = ["game_name=?"]
    where_parts.extend(time_conditions)
    where_clause = " AND ".join(where_parts)

    # Total games
    c.execute(f'SELECT COUNT(*) FROM game_history WHERE {where_clause}', (game_name,))
    total_games = c.fetchone()[0]

    # Wins/Losses
    c.execute(f'SELECT COUNT(*) FROM game_history WHERE {where_clause} AND is_win=1', (game_name,))
    wins = c.fetchone()[0]
    c.execute(f'SELECT COUNT(*) FROM game_history WHERE {where_clause} AND is_win=0', (game_name,))
    losses = c.fetchone()[0]

    # Total bet/won
    c.execute(f'SELECT SUM(CASE WHEN is_win=1 THEN amount ELSE 0 END), SUM(CASE WHEN is_win=0 THEN amount ELSE 0 END) FROM game_history WHERE {where_clause}', (game_name,))
    total_won, total_lost = c.fetchone()

    # Unique players
    c.execute(f'SELECT COUNT(DISTINCT uid) FROM game_history WHERE {where_clause}', (game_name,))
    unique_players = c.fetchone()[0]

    conn.close()

    return {
        'total_games': total_games,
        'wins': wins,
        'losses': losses,
        'total_won': total_won or 0,
        'total_lost': total_lost or 0,
        'unique_players': unique_players
    }

def rollback_game(game_id):
    """Rollback a specific game - toggles between rolled and not rolled"""
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute('SELECT * FROM game_history WHERE id=?', (game_id,))
    game = c.fetchone()
    if not game:
        conn.close()
        return False, "Игра не найдена"

    game_id, game_uid, gname, details, amount, is_win, is_rolled_back, created_at = game

    # Получаем текущий статус - проверяем, откатана ли игра
    is_currently_rolled = is_game_rolled_back(is_rolled_back)

    if is_currently_rolled:
        # === ОБРАТНЫЙ ОТКАТ (снимаем откат) ===
        # Игра была откатана: если был выигрыш - вычли монеты, если проигрыш - добавили
        # Теперь возвращаем всё обратно:
        # - Если был выигрыш: возвращаем вычтенные монеты
        # - Если был проигрыш: забираем добавленные монеты
        
        if is_win:
            # Был выигрыш, при откате вычли - возвращаем
            add_coins(game_uid, amount)
            sign = "+"
            action = "возвращены"
        else:
            # Был проигрыш, при откате добавили - забираем
            add_coins(game_uid, -amount)
            sign = "-"
            action = "списаны"
        
        # Помечаем как НЕоткатанную (ставим 0)
        c.execute('UPDATE game_history SET is_rolled_back=0 WHERE id=?', (game_id,))
        conn.commit()
        conn.close()
        return True, f"✅ Отмена отката: {sign}{amount} монет {action} пользователю"
    else:
        # === ПЕРВЫЙ ОТКАТ ===
        # Игра не откатана: если выигрыш - вычесть монеты, если проигрыш - добавить
        
        if is_win:
            # Выигрыш - вычитаем монеты
            add_coins(game_uid, -amount)
            sign = "-"
            action = "списаны"
        else:
            # Проигрыш - добавляем монеты
            add_coins(game_uid, amount)
            sign = "+"
            action = "возвращены"

        # Помечаем как откаченную (ставим 1)
        c.execute('UPDATE game_history SET is_rolled_back=1 WHERE id=?', (game_id,))
        conn.commit()
        conn.close()
        return True, f"↩️ Откат игры: {sign}{amount} монет {action} пользователю"

def rollback_admin_log(log_id, admin_id):
    """Rollback an admin log action - can be done multiple times (reverse each time)

    Returns (success, message)
    """
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute('SELECT * FROM admin_logs WHERE id=?', (log_id,))
    log = c.fetchone()
    if not log:
        conn.close()
        return False, "Лог не найден"

    log_id, log_admin_id, action, target_type, target_id, details, is_rolled_back, created_at = log

    # Проверяем текущий статус отката
    is_rolled = is_game_rolled_back(is_rolled_back)

    # Откатываем действие в зависимости от типа и статуса
    success = True
    msg = ""

    if is_rolled:
        # ОБРАТНЫЙ ОТКАТ - возвращаем всё обратно
        if action == 'add_balance':
            # Было: добавили монеты, откат: вычли монеты
            # Обратный откат: возвращаем монеты
            try:
                amount = int(details.split()[0])
                add_coins(target_id, amount)
                msg = f"ОБРАТНЫЙ откат: возвращено {amount} монет пользователю {target_id}"
            except:
                success = False
                msg = "Ошибка при обратном откате"

        elif action == 'sub_balance':
            # Было: вычли монеты, откат: вернули монеты
            # Обратный откат: снова вычитаем
            try:
                amount = int(details.split()[0])
                add_coins(target_id, -amount)
                msg = f"ОБРАТНЫЙ откат: повторно вычтено {amount} монет у пользователя {target_id}"
            except:
                success = False
                msg = "Ошибка при обратном откате"

        elif action == 'block_user':
            # Было: заблокировали, откат: разблокировали
            # Обратный откат: снова блокируем
            set_field(target_id, 'is_blocked', 1)
            msg = f"ОБРАТНЫЙ откат: пользователь {target_id} снова заблокирован"

        elif action == 'unblock_user':
            # Было: разблокировали, откат: заблокировали
            # Обратный откат: снова разблокируем
            set_field(target_id, 'is_blocked', 0)
            msg = f"ОБРАТНЫЙ откат: пользователь {target_id} снова разблокирован"

        elif action == 'delete_promo':
            # Было: удалили промокод, откат: восстановили
            # Обратный откат: снова удаляем
            conn = sqlite3.connect(DB_PATH); c = conn.cursor()
            c.execute('UPDATE promocodes SET deleted=1 WHERE code=?', (str(target_id),))
            conn.commit()
            conn.close()
            msg = f"ОБРАТНЫЙ откат: промокод {target_id} снова удален"

        else:
            msg = f"ОБРАТНЫЙ откат действия: {action}"

        if success:
            # Помечаем как НЕоткатанную
            conn = sqlite3.connect(DB_PATH); c = conn.cursor()
            c.execute('UPDATE admin_logs SET is_rolled_back=0 WHERE id=?', (log_id,))
            conn.commit()
            conn.close()

    else:
        # ПЕРВЫЙ ОТКАТ
        if action == 'add_balance':
            # Откат добавления баланса
            try:
                amount = int(details.split()[0])
                add_coins(target_id, -amount)
                msg = f"Откат добавления {amount} монет пользователю {target_id}"
            except:
                success = False
                msg = "Ошибка при откате добавления баланса"

        elif action == 'sub_balance':
            # Откат вычитания баланса (возвращаем вычтенное)
            try:
                amount = int(details.split()[0])
                add_coins(target_id, amount)
                msg = f"Откат вычитания {amount} монет пользователю {target_id}"
            except:
                success = False
                msg = "Ошибка при откате вычитания баланса"

        elif action == 'set_balance':
            # Откат установки баланса - сложнее, нужно знать старое значение
            # В данном случае просто помечаем как откаченный
            msg = f"Откат установки баланса пользователю {target_id}"

        elif action == 'global_add':
            # Откат глобального добавления
            try:
                amount = int(details.split()[0])
                conn = sqlite3.connect(DB_PATH); c = conn.cursor()
                c.execute('UPDATE users SET coins=coins-? WHERE coins>=?', (amount, amount))
                affected = c.rowcount
                conn.commit()
                conn.close()
                msg = f"Откат глобального добавления {amount} монет ({affected} пользователей)"
            except:
                success = False
                msg = "Ошибка при откате глобального добавления"

        elif action == 'global_sub':
            # Откат глобального вычитания
            try:
                amount = int(details.split()[0])
                conn = sqlite3.connect(DB_PATH); c = conn.cursor()
                c.execute('UPDATE users SET coins=coins+? WHERE id!=?', (amount, admin_id))
                affected = c.rowcount
                conn.commit()
                conn.close()
                msg = f"Откат глобального вычитания {amount} монет ({affected} пользователей)"
            except:
                success = False
                msg = "Ошибка при откате глобального вычитания"

        elif action == 'global_set':
            # Откат глобальной установки - просто помечаем
            msg = f"Откат глобальной установки баланса"

        elif action == 'delete_promo':
            # Откат удаления промокода
            conn = sqlite3.connect(DB_PATH); c = conn.cursor()
            c.execute('UPDATE promocodes SET deleted=0 WHERE code=?', (str(target_id),))
            conn.commit()
            conn.close()
            msg = f"Откат удаления промокода {target_id}"

        elif action == 'delete_user':
            # Откат удаления пользователя - невозможно (пользователь уже удален)
            success = False
            msg = "Невозможно откатить удаление пользователя"

        elif action == 'block_user':
            # Откат блокировки пользователя
            set_field(target_id, 'is_blocked', 0)
            msg = f"Откат блокировки пользователя {target_id}"

        elif action == 'unblock_user':
            # Откат разблокировки пользователя
            set_field(target_id, 'is_blocked', 1)
            msg = f"Откат разблокировки пользователя {target_id}"

        else:
            # Другие действия просто помечаем как откаченные
            msg = f"Откат действия: {action}"

        if success:
            # Помечаем лог как откаченный
            conn = sqlite3.connect(DB_PATH); c = conn.cursor()
            c.execute('UPDATE admin_logs SET is_rolled_back=1 WHERE id=?', (log_id,))
            conn.commit()
            conn.close()

    return success, msg

def rollback_promo_usage(promo_usage_id):
    """Rollback a specific promocode usage"""
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute('SELECT * FROM promo_usage WHERE id=?', (promo_usage_id,))
    usage = c.fetchone()
    if not usage:
        conn.close()
        return False, "Использование промокода не найдено"

    # Таблица promo_usage имеет 6 столбцов: id, code, uid, used_at, created_at (после миграции)
    pu_id, code, uid, used_at = usage[0], usage[1], usage[2], usage[3]

    # Get promocode reward
    c.execute('SELECT reward FROM promocodes WHERE code=?', (code,))
    promo = c.fetchone()
    if not promo:
        conn.close()
        return False, "Промокод не найден"

    reward = promo[0]

    # Remove coins from user
    add_coins(uid, -reward)

    # Decrement promocode uses
    c.execute('UPDATE promocodes SET uses=uses-1 WHERE code=?', (code,))

    # Delete usage record
    c.execute('DELETE FROM promo_usage WHERE id=?', (pu_id,))
    conn.commit()
    conn.close()

    return True, f"Откат промокода {code}: -{reward} монет"

def rollback_user_completely(target_uid):
    """Completely rollback user: reset balance, delete all games, delete all promos, delete logs"""
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()

    # Get current balance
    c.execute('SELECT coins FROM users WHERE id=?', (target_uid,))
    result = c.fetchone()
    if not result:
        conn.close()
        return False, "Пользователь не найден"

    current_balance = result[0]

    # Delete all game history
    c.execute('DELETE FROM game_history WHERE uid=?', (target_uid,))
    games_deleted = c.rowcount

    # Delete all promo usage
    c.execute('SELECT code FROM promo_usage WHERE uid=?', (target_uid,))
    promos_used = c.fetchall()
    for (code,) in promos_used:
        c.execute('UPDATE promocodes SET uses=uses-1 WHERE code=?', (code,))
    c.execute('DELETE FROM promo_usage WHERE uid=?', (target_uid,))
    promos_deleted = len(promos_used)

    # Delete all admin logs related to this user
    c.execute('DELETE FROM admin_logs WHERE target_type="user" AND target_id=?', (target_uid,))
    logs_deleted = c.rowcount

    # Reset user balance to default
    c.execute('UPDATE users SET coins=500 WHERE id=?', (target_uid,))

    # Reset other user stats
    c.execute('UPDATE users SET total_refs=0, consecutive_wins=0, jetpack_best=0.0, jetpack_auto=0.0, last_hourly=NULL, last_wheel=NULL WHERE id=?', (target_uid,))

    conn.commit()
    conn.close()

    return True, f"Пользователь откачен! Игр удалено: {games_deleted}, Промокодов: {promos_deleted}, Логов: {logs_deleted}, Баланс сброшен на 500"

def get_action_description(action, target_type, target_id):
    """Get human-readable description of admin action"""
    action_map = {
        'add_balance': '💰 Добавил баланс',
        'sub_balance': '💸 Вычел баланс',
        'set_balance': '🔄 Установил баланс',
        'block': '🚫 Заблокировал',
        'unblock': '✅ Разблокировал',
        'give_admin': '👨‍💻 Выдал админку',
        'remove_admin': '❌ Снял админку',
        'delete_promo': '🗑️ Удалил промокод',
        'create_promo': '🎫 Создал промокод',
        'reset_refs': '👥 Обнулил рефералов',
        'block_refs': '🚫 Заблокировал рефералов',
        'send_message': '📢 Отправил сообщение',
        'create_broadcast': '📢 Создал рассылку',
        'create_broadcast_photo': '📢 Создал рассылку с фото',
        'add_admin': '👨‍💻 Добавил админа',
        'global_add': '💰 Добавил баланс',
        'global_sub': '💸 Вычел баланс',
        'global_set': '🔄 Установил баланс',
        'rollback_game': '↩️ Откатил игру',
        'rollback_admin': '↩️ Откатил действие',
        'rollback_user': '↩️ Полностью откатил',
        'rollback_promo': '↩️ Откатил промокод',
        'clear_all_promos': '🗑️ Очистил все промокоды',
    }

    action_desc = action_map.get(action, action)

    if target_type == 'user':
        target_desc = f"пользователю #{target_id}"
    elif target_type == 'admin':
        target_desc = f"админу #{target_id}"
    elif target_type == 'promocode':
        target_desc = f"промокод {target_id}"
    elif target_type == 'all':
        target_desc = "всем пользователям"
    elif target_type == 'game':
        target_desc = f"игру #{target_id}"
    elif target_type == 'log':
        target_desc = f"лог #{target_id}"
    elif target_type == 'promo_usage':
        target_desc = f"использование #{target_id}"
    else:
        target_desc = str(target_id) if target_id else ""

    # Для глобальных действий добавляем "всем пользователям"
    if action in ['global_add', 'global_sub', 'global_set', 'clear_all_promos']:
        return f"{action_desc} всем пользователям"

    return f"{action_desc} {target_desc}"

def get_admin_logs(limit=100, offset=0, rolled_back=None):
    """Get admin logs with pagination and optional filter by rolled_back status

    Args:
        limit: number of logs per page
        offset: pagination offset
        rolled_back: None (all), False (not rolled back), True (rolled back)
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    if rolled_back is None:
        c.execute('SELECT COUNT(*) FROM admin_logs')
        total = c.fetchone()[0]
        c.execute('''SELECT * FROM admin_logs ORDER BY id DESC LIMIT ? OFFSET ?''', (limit, offset))
    elif rolled_back:
        # Откатанные: is_rolled_back = 1
        c.execute('SELECT COUNT(*) FROM admin_logs WHERE is_rolled_back=1')
        total = c.fetchone()[0]
        c.execute('''SELECT * FROM admin_logs WHERE is_rolled_back=1 ORDER BY id DESC LIMIT ? OFFSET ?''',
                  (limit, offset))
    else:
        # Неоткатанные: is_rolled_back = 0 или NULL
        c.execute('SELECT COUNT(*) FROM admin_logs WHERE is_rolled_back=0 OR is_rolled_back IS NULL')
        total = c.fetchone()[0]
        c.execute('''SELECT * FROM admin_logs WHERE is_rolled_back=0 OR is_rolled_back IS NULL ORDER BY id DESC LIMIT ? OFFSET ?''',
                  (limit, offset))

    logs = c.fetchall()
    conn.close()
    return logs, total

# ─────────── ADMIN MANAGEMENT ───────────
def get_all_admins():
    """Get all admins"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''SELECT a.id, a.added_by, a.added_at, u.username FROM admins a
                 LEFT JOIN users u ON a.id = u.id ORDER BY a.id''')
    admins = c.fetchall()
    conn.close()
    return admins

def add_admin(admin_id, added_by):
    """Add new admin"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute('INSERT INTO admins (id, added_by) VALUES (?, ?)', (admin_id, added_by))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def remove_admin(admin_id):
    """Remove admin"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('DELETE FROM admins WHERE id=?', (admin_id,))
    conn.commit()
    conn.close()

# ─────────── USER MANAGEMENT EXTENDED ───────────
def search_users(query, page=0, page_size=10):
    """Search users by ID or username"""
    offset = page * page_size
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Try to parse as ID first
    try:
        uid = int(query)
        c.execute('SELECT id, username, coins, total_refs FROM users WHERE id=?', (uid,))
    except ValueError:
        # Search by username
        c.execute('SELECT id, username, coins, total_refs FROM users WHERE username LIKE ? LIMIT ? OFFSET ?',
                  (f'%{query}%', page_size, offset))

    users = c.fetchall()
    conn.close()
    return users

def sort_users(sort_by, page=0, page_size=10):
    """Sort users by parameter"""
    offset = page * page_size
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    valid_sorts = {
        'coins': 'coins DESC',
        'coins_asc': 'coins ASC',
        'refs': 'total_refs DESC',
        'refs_asc': 'total_refs ASC',
        'id': 'id DESC',
        'id_asc': 'id ASC',
        'reg': 'registration_time DESC',
        'reg_asc': 'registration_time ASC',
        'blocked': 'is_blocked DESC',
        'active': 'is_blocked ASC'
    }

    order = valid_sorts.get(sort_by, 'id DESC')

    # For blocked/active filter, we need to filter
    if sort_by == 'blocked':
        c.execute('SELECT id, username, coins, total_refs FROM users WHERE is_blocked=1 ORDER BY id DESC LIMIT ? OFFSET ?',
                  (page_size, offset))
    elif sort_by == 'active':
        c.execute('SELECT id, username, coins, total_refs FROM users WHERE is_blocked=0 ORDER BY id DESC LIMIT ? OFFSET ?',
                  (page_size, offset))
    elif sort_by == 'all':
        c.execute('SELECT id, username, coins, total_refs FROM users ORDER BY id DESC LIMIT ? OFFSET ?',
                  (page_size, offset))
    else:
        c.execute(f'SELECT id, username, coins, total_refs FROM users ORDER BY {order} LIMIT ? OFFSET ?',
                  (page_size, offset))
    users = c.fetchall()

    conn.close()
    return users

# ─────────── BROADCASTS ───────────
def create_broadcast(message_type, content, file_id=None, scheduled_at=None, created_by=None):
    """Create a broadcast (text or image)"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''INSERT INTO admin_broadcasts (message_type, content, file_id, scheduled_at, created_by)
                 VALUES (?, ?, ?, ?, ?)''', (message_type, content, file_id, scheduled_at, created_by))
    conn.commit()
    broadcast_id = c.lastrowid
    conn.close()
    return broadcast_id

def get_broadcasts(status=None):
    """Get broadcasts, optionally filtered by status"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if status:
        c.execute('SELECT * FROM admin_broadcasts WHERE status=? ORDER BY id DESC', (status,))
    else:
        c.execute('SELECT * FROM admin_broadcasts ORDER BY id DESC')
    broadcasts = c.fetchall()
    conn.close()
    return broadcasts

def delete_broadcast(broadcast_id):
    """Delete a broadcast"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('DELETE FROM admin_broadcasts WHERE id=?', (broadcast_id,))
    conn.commit()
    conn.close()

def mark_broadcast_sent(broadcast_id):
    """Mark broadcast as sent"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE admin_broadcasts SET status=?, sent_at=? WHERE id=?',
              ('sent', datetime.now().isoformat(), broadcast_id))
    conn.commit()
    conn.close()

# ─────────── BUTTON HANDLER ───────────

def _btn_handler(q, uid, d, context):
    # Update activity and check for pending referrals
    update_last_activity(uid)
    check_and_award_pending_referrals(uid)

    # ── ПРОВЕРКА ПОДПИСКИ НА КАНАЛ ──
    if d == 'channel_check':
        import threading
        import asyncio

        def check_subscription():
            # Create new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            async def async_check():
                is_subscribed = await check_channel_subscription(q.bot, uid)
                update_channel_subscription_status(uid, is_subscribed)

                if is_subscribed:
                    if not get_channel_reward_status(uid):
                        add_coins(uid, 200)
                        set_channel_reward_received(uid)
                        row = get_user(uid)
                        try:
                            q.edit_message_text(
                                f"✅ Вы подписаны на канал!\n\n"
                                f"🎁 +200 монет добавлено на баланс!\n"
                                f"💰 Ваш баланс: {row[2]} монет\n\n"
                                f"⚠️ Если вы от подпишетесь, 200 монет будут списаны!",
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Продолжить", callback_data='main_menu')]])
                            )
                        except Exception:
                            pass
                    else:
                        try:
                            q.edit_message_text(
                                f"✅ Вы подписаны на канал!\n\n"
                                f"Вы уже получали награду за подписку.",
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Продолжить", callback_data='main_menu')]])
                            )
                        except Exception:
                            pass
                else:
                    try:
                        q.edit_message_text(
                            f"❌ Вы не подписаны на канал!\n\n"
                            f"📢 Пожалуйста, подпишитесь на канал: @{CHANNEL_USERNAME}\n"
                            f"Затем нажмите \"Проверить\" снова.",
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton("✅ Проверить снова", callback_data='channel_check')],
                                [InlineKeyboardButton("⏭️ Пропустить", callback_data='channel_skip')]
                            ])
                        )
                    except Exception:
                        pass

            try:
                loop.run_until_complete(async_check())
            finally:
                loop.close()

        thread = threading.Thread(target=check_subscription, daemon=True)
        thread.start()

    elif d == 'channel_skip':
        # Просто закрываем всплывающее окно, возвращаемся в главное меню
        q.edit_message_text(
            "⏭️ Пропущено. Следующее предложение появится позже.",
            reply_markup=main_menu_kb(uid)
        )

    # ── АДМИН ПАНЕЛЬ ──
    elif d == 'admin_stats':
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return

        period = context.user_data.get('admin_stats_period', 'all')
        stats = get_stats_by_period(period)

        period_names = {
            'day': 'За день',
            'week': 'За неделю',
            'month': 'За месяц',
            'year': 'За год',
            'all': 'За все время'
        }

        period_name = period_names.get(period, 'За все время')

        winrate = stats['total_wins'] / stats['total_games'] * 100 if stats['total_games'] > 0 else 0
        profit = stats['total_won'] - stats['total_lost']

        q.edit_message_text(
            f"📊 Общая статистика ({period_name})\n\n"
            f"👥 Всего пользователей: {stats['total_users']}\n"
            f"✅ Активные (24ч): {stats['active_users']}\n"
            f"📅 Новых пользователей: {stats['new_users']}\n"
            f"💰 Монет в обороте: {stats['total_coins']:,}\n"
            f"🎮 Всего игр: {stats['total_games']}\n"
            f"✅ Побед: {stats['total_wins']}\n"
            f"❌ Поражений: {stats['total_losses']}\n"
            f"📈 Winrate: {winrate:.1f}%\n"
            f"💰 Всего выиграно: {stats['total_won']:,}\n"
            f"💸 Всего проиграно: {stats['total_lost']:,}\n"
            f"📊 Прибыль/Убыток: {profit:+,}\n"
            f"🎫 Промокодов использовано: {stats['promos_used']}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📊 За день", callback_data='admin_stats_period_day'),
                 InlineKeyboardButton("📊 За неделю", callback_data='admin_stats_period_week')],
                [InlineKeyboardButton("📊 За месяц", callback_data='admin_stats_period_month'),
                 InlineKeyboardButton("📊 За год", callback_data='admin_stats_period_year')],
                [InlineKeyboardButton("📊 За все время", callback_data='admin_stats_period_all')],
                [InlineKeyboardButton("🎮 Статистика по играм", callback_data='admin_stats_games')],
                [InlineKeyboardButton("🔙 Назад", callback_data='admin_menu')]
            ])
        )

    elif d.startswith('admin_stats_period_'):
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return
        period = d.replace('admin_stats_period_', '')
        context.user_data['admin_stats_period'] = period
        d = 'admin_stats'
        _btn_handler(q, uid, d, context)

    elif d == 'admin_stats_games':
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return

        period = context.user_data.get('admin_stats_period', 'all')
        period_names = {
            'day': 'За день',
            'week': 'За неделю',
            'month': 'За месяц',
            'year': 'За год',
            'all': 'За все время'
        }

        q.edit_message_text(
            f"📊 Статистика по играм ({period_names.get(period, 'За все время')})\n\nВыберите игру:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🪙 Монетка", callback_data='admin_stats_game_monetka')],
                [InlineKeyboardButton("⛏️ Минёр", callback_data='admin_stats_game_miner')],
                [InlineKeyboardButton("🚀 Джетпак", callback_data='admin_stats_game_jetpack')],
                [InlineKeyboardButton("🎰 Слоты", callback_data='admin_stats_game_slots')],
                [InlineKeyboardButton("🗼 Башня", callback_data='admin_stats_game_tower')],
                [InlineKeyboardButton("📊 Японские свечи", callback_data='admin_stats_game_candles')],
                [InlineKeyboardButton("🎡 Колесо фортуны", callback_data='admin_stats_game_wheel')],
                [InlineKeyboardButton("🔙 Назад", callback_data='admin_stats')]
            ])
        )

    elif d.startswith('admin_stats_game_'):
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return

        game_map = {
            'monetka': 'Монетка',
            'miner': 'Минёр',
            'jetpack': 'Джетпак',
            'slots': 'Слоты',
            'tower': 'Башня',
            'candles': 'Свечи',
            'wheel': 'Колесо фортуны'
        }
        game_key = d.replace('admin_stats_game_', '')
        game_name = game_map.get(game_key, d)

        period = context.user_data.get('admin_stats_period', 'all')
        period_names = {
            'day': 'За день',
            'week': 'За неделю',
            'month': 'За месяц',
            'year': 'За год',
            'all': 'За все время'
        }

        stats = get_game_stats_by_period(game_name, period)

        emoji = GAME_EMOJIS.get(game_name, '🎮')

        winrate = stats['wins'] / stats['total_games'] * 100 if stats['total_games'] > 0 else 0
        profit = stats['total_won'] - stats['total_lost']

        q.edit_message_text(
            f"{emoji} Статистика: {game_name} ({period_names.get(period, 'За все время')})\n\n"
            f"🎮 Всего игр: {stats['total_games']}\n"
            f"👊 Уникальных игроков: {stats['unique_players']}\n"
            f"✅ Побед: {stats['wins']}\n"
            f"❌ Поражений: {stats['losses']}\n"
            f"💰 Всего выиграно: {stats['total_won']:,}\n"
            f"💸 Всего проиграно: {stats['total_lost']:,}\n"
            f"📈 Winrate: {winrate:.1f}%\n"
            f"📊 Прибыль/Убыток: {profit:+,}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Обновить", callback_data=d)],
                [InlineKeyboardButton("🔙 Назад", callback_data='admin_stats_games')]
            ])
        )

    elif d == 'admin_menu':
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return
        q.edit_message_text(
            "🔧 Админ-панель\n\nВыберите действие:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📊 Статистика", callback_data='admin_stats')],
                [InlineKeyboardButton("👥 Пользователи", callback_data='admin_users')],
                [InlineKeyboardButton("📢 Рассылки", callback_data='admin_broadcasts')],
                [InlineKeyboardButton("🎫 Промокоды", callback_data='admin_promos')],
                [InlineKeyboardButton("👨‍💻 Админы", callback_data='admin_admins')],
                [InlineKeyboardButton("📜 Логи", callback_data='admin_logs')],
                [InlineKeyboardButton("💰 Глобальный баланс", callback_data='admin_global_balance')],
                [InlineKeyboardButton("🔙 Выход", callback_data='main_menu')]
            ])
        )

    elif d == 'admin_users':
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return

        # Show users list with pagination
        sort_by = context.user_data.get('admin_users_sort', 'id_desc')
        page = context.user_data.get('admin_users_page', 0)
        users = sort_users(sort_by, page=page, page_size=8)

        if not users:
            q.edit_message_text("👥 Пользователи не найдены",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='admin_menu')]]))
            return

        # Build keyboard with user buttons
        kb = []
        for u_id, uname, u_coins, u_refs in users:
            name = uname if uname else f"ID:{u_id}"
            kb.append([InlineKeyboardButton(f"👤 {name} | 💰{u_coins} | 👥{u_refs}", callback_data=f'user_info_{u_id}')])

        # Navigation buttons
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton("◀️", callback_data='admin_users_prev'))
        nav_row.append(InlineKeyboardButton(f"Стр {page+1}", callback_data='dummy'))
        # Check if there are more users
        total = len(sort_users(sort_by, page=0, page_size=1000))
        if (page + 1) * 8 < total:
            nav_row.append(InlineKeyboardButton("▶️", callback_data='admin_users_next'))
        if len(nav_row) > 1:
            kb.append(nav_row)

        # Bottom buttons
        kb.append([
            InlineKeyboardButton("🔍 Поиск", callback_data='admin_users_search'),
            InlineKeyboardButton("📊 Сорт.", callback_data='admin_users_sort')
        ])
        kb.append([InlineKeyboardButton("🔙 Назад", callback_data='admin_menu')])

        q.edit_message_text(f"👥 Пользователи (стр. {page+1})\n\nНажмите на пользователя для подробностей:",
            reply_markup=InlineKeyboardMarkup(kb))

    elif d == 'admin_users_prev':
        page = context.user_data.get('admin_users_page', 0)
        if page > 0:
            context.user_data['admin_users_page'] = page - 1
        q.edit_message_text("Загрузка...", reply_markup=None)
        # Re-show users
        d = 'admin_users'
        _btn_handler(q, uid, d, context)

    elif d == 'admin_users_next':
        page = context.user_data.get('admin_users_page', 0)
        context.user_data['admin_users_page'] = page + 1
        q.edit_message_text("Загрузка...", reply_markup=None)
        # Re-show users
        d = 'admin_users'
        _btn_handler(q, uid, d, context)

    elif d == 'admin_users_search':
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return
        q.edit_message_text(
            "🔍 Поиск пользователя\n\nВведите ID или username:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='admin_users')]]))
        context.user_data['state'] = 'admin_user_search'

    elif d == 'admin_users_sort':
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return
        q.edit_message_text(
            "📊 Сортировка пользователей\n\nВыберите критерий:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💰 Монеты (убыв)", callback_data='admin_sort_coins_desc'),
                 InlineKeyboardButton("💰 Монеты (возр)", callback_data='admin_sort_coins_asc')],
                [InlineKeyboardButton("👥 Рефы (убыв)", callback_data='admin_sort_refs_desc'),
                 InlineKeyboardButton("👥 Рефы (возр)", callback_data='admin_sort_refs_asc')],
                [InlineKeyboardButton("🆔 ID (новые)", callback_data='admin_sort_id_desc'),
                 InlineKeyboardButton("🆔 ID (старые)", callback_data='admin_sort_id_asc')],
                [InlineKeyboardButton("🚫 Заблокированные", callback_data='admin_sort_blocked'),
                 InlineKeyboardButton("✅ Активные", callback_data='admin_sort_active')],
                [InlineKeyboardButton("👥 Все", callback_data='admin_sort_all')],
                [InlineKeyboardButton("🔙 Назад", callback_data='admin_users')]
            ])
        )

    elif d.startswith('admin_sort_'):
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return
        sort_type = d.replace('admin_sort_', '')
        sort_map = {
            'coins_desc': 'coins', 'coins_asc': 'coins_asc',
            'refs_desc': 'refs', 'refs_asc': 'refs_asc',
            'id_desc': 'id', 'id_asc': 'id_asc',
            'blocked': 'blocked', 'active': 'active', 'all': 'all'
        }
        context.user_data['admin_users_sort'] = sort_map.get(sort_type, 'id_desc')
        context.user_data['admin_users_page'] = 0
        q.edit_message_text("Загрузка...", reply_markup=None)
        # Re-show users with new sort
        d = 'admin_users'
        _btn_handler(q, uid, d, context)

    elif d.startswith('user_info_'):
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return

        # Парсим target_uid и back_to
        d_suffix = d.replace('user_info_', '')

        # Проверяем разные варианты формата
        if '_back_logs' in d_suffix:
            target_uid = int(d_suffix.replace('_back_logs', ''))
            back_to = 'admin_logs_users'
        elif '_admin_users' in d_suffix:
            target_uid = int(d_suffix.replace('_admin_users', ''))
            back_to = 'admin_users'
        elif '_admin_logs_users' in d_suffix:
            target_uid = int(d_suffix.replace('_admin_logs_users', ''))
            back_to = 'admin_logs_users'
        else:
            # Если нет суффикса, используем значение по умолчанию
            try:
                target_uid = int(d_suffix)
                back_to = 'admin_users'
            except ValueError:
                # Если не удалось распарсить как число, попробуем разделить по подчеркиванию
                parts = d_suffix.split('_')
                target_uid = int(parts[0])
                back_to = '_'.join(parts[1:]) if len(parts) > 1 else 'admin_users'

        # Сохраняем back_to в контексте для использования в подменю
        context.user_data['user_info_back_to'] = back_to

        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute('SELECT * FROM users WHERE id=?', (target_uid,))
        user = c.fetchone()
        if not user:
            conn.close()
            q.answer("Пользователь не найден!", show_alert=True); return

        # Get referral count
        c.execute('SELECT COUNT(*) FROM users WHERE referrer_id=?', (target_uid,))
        ref_count = c.fetchone()[0]

        # Get position in leaderboard
        c.execute('SELECT COUNT(*) FROM users WHERE coins>?', (user[2],))
        position = c.fetchone()[0] + 1

        # Get total games played
        c.execute('SELECT COUNT(*) FROM game_history WHERE uid=?', (target_uid,))
        total_games = c.fetchone()[0]

        # Get total won/lost
        c.execute('SELECT SUM(CASE WHEN is_win=1 THEN amount ELSE 0 END), SUM(CASE WHEN is_win=0 THEN amount ELSE 0 END) FROM game_history WHERE uid=?', (target_uid,))
        won_lost = c.fetchone()
        total_won = won_lost[0] or 0
        total_lost = won_lost[1] or 0

        # Get promocodes used
        c.execute('SELECT code, COUNT(*) as cnt FROM promo_usage WHERE uid=? GROUP BY code', (target_uid,))
        promos_used = c.fetchall()

        # Check if user is admin
        c.execute('SELECT id FROM admins WHERE id=?', (target_uid,))
        is_admin_user = c.fetchone() is not None

        is_blocked = user[14] if len(user) > 14 else 0
        blocked_text = "🚫 ЗАБЛОКИРОВАН" if is_blocked else "✅ Активен"
        admin_text = "👨‍💻 АДМИН" if is_admin_user else "👤 Пользователь"

        reg_date = user[11] if len(user) > 11 else "Неизвестно"

        conn.close()

        text = (
            f"👤 {user[1] if user[1] else 'Без имени'}\n"
            f"🆔 ID: {user[0]}\n"
            f"💰 Баланс: {user[2]} монет\n"
            f"🏆 Место в топе: #{position}\n"
            f"👥 Рефералов: {ref_count}\n"
            f"📅 Регистрация: {reg_date[:10] if len(reg_date) > 10 else reg_date}\n"
            f"🎮 Игр сыграно: {total_games}\n"
            f"💸 Потрачено: {total_lost} монет\n"
            f"💰 Заработано: {total_won} монет\n"
            f"📊 Статус: {blocked_text}\n"
            f"{admin_text}\n"
            f"🎫 Промокодов активировано: {len(promos_used)}"
        )

        q.edit_message_text(text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💰 Баланс", callback_data=f'user_balance_menu_{target_uid}')],
                [InlineKeyboardButton("🎮 История игр", callback_data=f'user_game_history_{target_uid}')],
                [InlineKeyboardButton("🎫 Промокоды", callback_data=f'user_promos_{target_uid}')],
                [InlineKeyboardButton("👥 Рефералы", callback_data=f'user_refs_{target_uid}')],
                [InlineKeyboardButton("👨‍💻 Админка", callback_data=f'user_admin_{target_uid}')],
                [InlineKeyboardButton("🚫 Блок/Разблок", callback_data=f'user_toggle_block_{target_uid}')],
                [InlineKeyboardButton("📢 Личное сообщение", callback_data=f'user_message_{target_uid}')],
                [InlineKeyboardButton("⚠️ Откатить пользователя", callback_data=f'user_rollback_confirm_{target_uid}')],
                [InlineKeyboardButton("🔙 Назад", callback_data=back_to)]
            ])
        )

    elif d.startswith('user_edit_balance_'):
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return
        target_uid = int(d.replace('user_edit_balance_', ''))
        q.edit_message_text(
            f"💰 Изменение баланса пользователя {target_uid}\n\n"
            f"Выберите действие:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Добавить", callback_data=f'user_add_balance_{target_uid}')],
                [InlineKeyboardButton("➖ Вычесть", callback_data=f'user_sub_balance_{target_uid}')],
                [InlineKeyboardButton("🔄 Установить", callback_data=f'user_set_balance_{target_uid}')],
                [InlineKeyboardButton("🔙 Назад", callback_data=f'user_info_{target_uid}')]
            ])
        )

    elif d.startswith('user_add_balance_'):
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return
        target_uid = int(d.replace('user_add_balance_', ''))
        q.edit_message_text(
            f"💰 Добавить монет пользователю {target_uid}\n\nВведите сумму:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data=f'user_info_{target_uid}')]]))
        context.user_data['admin_target_uid'] = target_uid
        context.user_data['admin_balance_action'] = 'add'
        context.user_data['state'] = 'admin_balance_amount'

    elif d.startswith('user_sub_balance_'):
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return
        target_uid = int(d.replace('user_sub_balance_', ''))
        q.edit_message_text(
            f"💰 Вычесть монет у пользователя {target_uid}\n\nВведите сумму:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data=f'user_info_{target_uid}')]]))
        context.user_data['admin_target_uid'] = target_uid
        context.user_data['admin_balance_action'] = 'sub'
        context.user_data['state'] = 'admin_balance_amount'

    elif d.startswith('user_set_balance_'):
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return
        target_uid = int(d.replace('user_set_balance_', ''))
        q.edit_message_text(
            f"💰 Установить баланс пользователю {target_uid}\n\nВведите сумму:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data=f'user_info_{target_uid}')]]))
        context.user_data['admin_target_uid'] = target_uid
        context.user_data['admin_balance_action'] = 'set'
        context.user_data['state'] = 'admin_balance_amount'

    elif d.startswith('user_block_'):
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return
        target_uid = int(d.replace('user_block_', ''))
        block_user(target_uid)
        log_admin_action(uid, 'block', 'user', target_uid)
        q.answer("Пользователь заблокирован!", show_alert=True)

    elif d.startswith('user_unblock_'):
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return
        target_uid = int(d.replace('user_unblock_', ''))
        unblock_user(target_uid)
        log_admin_action(uid, 'unblock', 'user', target_uid)
        q.answer("Пользователь разблокирован!", show_alert=True)

    elif d.startswith('user_message_'):
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return
        target_uid = int(d.replace('user_message_', ''))
        q.edit_message_text(
            f"📢 Личное сообщение пользователю {target_uid}\n\nВведите текст сообщения:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data=f'user_info_{target_uid}')]]))
        context.user_data['admin_target_uid'] = target_uid
        context.user_data['state'] = 'admin_user_message'

    elif d.startswith('user_balance_menu_'):
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return
        target_uid = int(d.replace('user_balance_menu_', ''))
        row = get_user(target_uid)
        back_to = context.user_data.get('user_info_back_to', 'admin_users')
        q.edit_message_text(
            f"💰 Управление балансом пользователя {target_uid}\n\nТекущий баланс: {row[2]} монет",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Добавить", callback_data=f'user_add_balance_{target_uid}')],
                [InlineKeyboardButton("➖ Вычесть", callback_data=f'user_sub_balance_{target_uid}')],
                [InlineKeyboardButton("🔄 Установить", callback_data=f'user_set_balance_{target_uid}')],
                [InlineKeyboardButton("🔙 Назад", callback_data=f'user_info_{target_uid}_{back_to}')]
            ])
        )

    elif d.startswith('user_game_history_') or d.startswith('user_game_history_filter_'):
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return

        # Обработка фильтров
        if d.startswith('user_game_history_filter_'):
            filter_type = d.replace('user_game_history_filter_', '')
            if filter_type == 'all':
                context.user_data['user_game_history_rolled'] = None
            elif filter_type == 'active':
                context.user_data['user_game_history_rolled'] = False
            elif filter_type == 'rolled':
                context.user_data['user_game_history_rolled'] = True
            # Сбрасываем страницу при смене фильтра
            context.user_data['user_game_history_page'] = 0
            # Получаем target_uid из контекста
            target_uid = context.user_data.get('user_game_history_uid')
            if not target_uid:
                q.answer("Ошибка: пользователь не выбран", show_alert=True); return
            page = 0
        else:
            # Правильный парсинг: user_game_history_{uid}_{page}
            parts = d[len('user_game_history_'):].split('_')
            if len(parts) < 1:
                q.answer("Ошибка!", show_alert=True); return
            target_uid = int(parts[0])
            page = int(parts[1]) if len(parts) > 1 else 0
            # Сохраняем uid в контексте
            context.user_data['user_game_history_uid'] = target_uid

        # Получаем фильтр из контекста
        rolled_back = context.user_data.get('user_game_history_rolled', None)
        rolled_back_text = {
            None: "Все",
            False: "Неоткатанные",
            True: "Откатанные"
        }[rolled_back]

        rows, total = get_history_paged(target_uid, page, rolled_back=rolled_back)
        pages = (total + 4) // 5 or 1
        back_to = context.user_data.get('user_info_back_to', 'admin_users')
        
        if not rows:
            text = f"📜 История игр пользователя {target_uid} ({rolled_back_text}) пуста"
            kb = [
                [InlineKeyboardButton("🔄 Все", callback_data='user_game_history_filter_all'),
                 InlineKeyboardButton("✅ Неоткатанные", callback_data='user_game_history_filter_active'),
                 InlineKeyboardButton("↩️ Откатанные", callback_data='user_game_history_filter_rolled')],
                [InlineKeyboardButton("🔙 Назад", callback_data=f'user_info_{target_uid}_{back_to}')]
            ]
        else:
            text = f"📜 История игр пользователя {target_uid} ({rolled_back_text})\n━━━━━━━━━━━━━━━━\nСтраница {page+1} из {pages} | Всего: {total}\n\nНажмите на игру для деталей:"
            kb = []
            for gid, gname, amount, is_win, is_rolled_back, created_at in rows:
                g_emoji = GAME_EMOJIS.get(gname, '🎮')
                res_emoji = "✅" if is_win else "❌"
                sign = "+" if is_win else "-"
                rollback_marker = " ↩️" if is_game_rolled_back(is_rolled_back) else ""
                kb.append([InlineKeyboardButton(
                    f"{res_emoji} {g_emoji} {gname}: {sign}{amount}{rollback_marker}",
                    callback_data=f'admin_gameview_{gid}_{target_uid}_{page}'
                )])

            # Фильтры
            kb.append([
                InlineKeyboardButton("🔄 Все", callback_data='user_game_history_filter_all'),
                InlineKeyboardButton("✅ Неоткатанные", callback_data='user_game_history_filter_active'),
                InlineKeyboardButton("↩️ Откатанные", callback_data='user_game_history_filter_rolled')
            ])

            nav = []
            if page > 0:
                nav.append(InlineKeyboardButton("◀️", callback_data=f'user_game_history_{target_uid}_{page-1}'))
            nav.append(InlineKeyboardButton(f"{page+1}/{pages}", callback_data='dummy'))
            if (page + 1) * 5 < total:
                nav.append(InlineKeyboardButton("▶️", callback_data=f'user_game_history_{target_uid}_{page+1}'))
            if len(nav) > 1:
                kb.append(nav)

            kb.append([InlineKeyboardButton("🔙 Назад", callback_data=f'user_info_{target_uid}_{back_to}')])

        q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

    elif d.startswith('admin_gameview_'):
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return

        parts = d.split('_')
        gid = int(parts[2])
        target_uid = int(parts[3])
        back_page = int(parts[4])

        g = get_game_info(gid)
        if not g:
            q.answer("Игра не найдена", show_alert=True); return

        gname, details, amount, is_win, is_rolled_back, created_at = g
        msg = format_game_detail(gname, details, amount, is_win, created_at, is_rolled_back)
        
        # Кнопки в зависимости от статуса отката (is_rolled_back == 1 означает откатан)
        if is_game_rolled_back(is_rolled_back):
            kb = [
                [InlineKeyboardButton("↩️ Отменить откат", callback_data=f'user_rollback_game_{gid}_{target_uid}_{back_page}')],
                [InlineKeyboardButton("🔙 Назад к списку", callback_data=f'user_game_history_{target_uid}_{back_page}')]
            ]
        else:
            kb = [
                [InlineKeyboardButton("↩️ Откатить игру", callback_data=f'user_rollback_game_{gid}_{target_uid}_{back_page}')],
                [InlineKeyboardButton("🔙 Назад к списку", callback_data=f'user_game_history_{target_uid}_{back_page}')]
            ]

        q.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb))

    elif d.startswith('user_rollback_game_'):
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return

        parts = d.split('_')
        gid = int(parts[3])
        target_uid = int(parts[4])
        back_page = int(parts[5])

        success, message = rollback_game(gid)

        if success:
            log_admin_action(uid, 'rollback_game', 'game', gid, f'User: {target_uid}, {message}')
            
            # Заново получаем актуальный статус игры
            g = get_game_info(gid)
            if g:
                gname, details, amount, is_win, is_rolled_back, created_at = g
                is_rolled = is_game_rolled_back(is_rolled_back)
                
                msg = format_game_detail(gname, details, amount, is_win, created_at, is_rolled_back)
                
                # Кнопки в зависимости от актуального статуса
                if is_rolled:
                    kb = [
                        [InlineKeyboardButton("↩️ Отменить откат", callback_data=f'user_rollback_game_{gid}_{target_uid}_{back_page}')],
                        [InlineKeyboardButton("🔙 Назад к списку", callback_data=f'user_game_history_{target_uid}_{back_page}')]
                    ]
                else:
                    kb = [
                        [InlineKeyboardButton("↩️ Откатить игру", callback_data=f'user_rollback_game_{gid}_{target_uid}_{back_page}')],
                        [InlineKeyboardButton("🔙 Назад к списку", callback_data=f'user_game_history_{target_uid}_{back_page}')]
                    ]
                
                q.edit_message_text(f"✅ {message}\n\n{msg}", reply_markup=InlineKeyboardMarkup(kb))
            else:
                q.edit_message_text(
                    f"✅ {message}\n\nИгра успешно откачена!",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data=f'user_game_history_{target_uid}_{back_page}')]])
                )
        else:
            q.answer(message, show_alert=True)

    elif d.startswith('user_promos_'):
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return
        target_uid = int(d.replace('user_promos_', ''))
        back_to = context.user_data.get('user_info_back_to', 'admin_users')

        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute('SELECT id, code, used_at FROM promo_usage WHERE uid=? ORDER BY used_at DESC', (target_uid,))
        promos = c.fetchall()
        conn.close()

        if not promos:
            text = f"🎫 Промокоды пользователя {target_uid}\n\nПользователь не активировал ни одного промокода"
            kb = [[InlineKeyboardButton("🔙 Назад", callback_data=f'user_info_{target_uid}_{back_to}')]]
        else:
            text = f"🎫 Промокоды пользователя {target_uid}\n\nНажмите на промокод для отката:"
            kb = []
            for pu_id, code, used_at in promos:
                kb.append([InlineKeyboardButton(
                    f"🎫 {code} | {used_at[:16] if len(used_at) > 16 else used_at}",
                    callback_data=f'user_promo_rollback_{pu_id}_{target_uid}'
                )])
            kb.append([InlineKeyboardButton("🔙 Назад", callback_data=f'user_info_{target_uid}_{back_to}')])

        q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

    elif d.startswith('user_promo_rollback_'):
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return

        parts = d.split('_')
        pu_id = int(parts[3])
        target_uid = int(parts[4])

        success, message = rollback_promo_usage(pu_id)

        if success:
            log_admin_action(uid, 'rollback_promo', 'promo_usage', pu_id, f'User: {target_uid}')
            q.edit_message_text(
                f"✅ {message}\n\nПромокод успешно откачен!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data=f'user_promos_{target_uid}')]])
            )
        else:
            q.answer(message, show_alert=True)

    elif d.startswith('user_refs_'):
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return
        target_uid = int(d.replace('user_refs_', ''))
        back_to = context.user_data.get('user_info_back_to', 'admin_users')

        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute('SELECT id, username, coins FROM users WHERE referrer_id=? LIMIT 10', (target_uid,))
        refs = c.fetchall()
        conn.close()

        if not refs:
            text = f"👥 Рефералы пользователя {target_uid}\n\nНет рефералов"
        else:
            text = f"👥 Рефералы пользователя {target_uid} (первые 10)\n\n"
            for ref_id, ref_name, ref_coins in refs:
                name = ref_name if ref_name else f"ID:{ref_id}"
                text += f"👤 {name} | 💰{ref_coins}\n"

        q.edit_message_text(text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🗑️ Обнулить рефералов", callback_data=f'user_reset_refs_{target_uid}')],
                [InlineKeyboardButton("🚫 Обнулить и заблокировать всех", callback_data=f'user_block_refs_{target_uid}')],
                [InlineKeyboardButton("🔙 Назад", callback_data=f'user_info_{target_uid}_{back_to}')]
            ])
        )

    elif d.startswith('user_reset_refs_'):
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return
        target_uid = int(d.replace('user_reset_refs_', ''))

        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute('UPDATE users SET referrer_id=NULL WHERE referrer_id=?', (target_uid,))
        c.execute('UPDATE users SET total_refs=0 WHERE id=?', (target_uid,))
        conn.commit()
        conn.close()

        log_admin_action(uid, 'reset_refs', 'user', target_uid)
        q.answer("Рефералы обнулены!", show_alert=True)

    elif d.startswith('user_block_refs_'):
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return
        target_uid = int(d.replace('user_block_refs_', ''))

        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute('UPDATE users SET referrer_id=NULL, is_blocked=1 WHERE referrer_id=?', (target_uid,))
        c.execute('UPDATE users SET total_refs=0 WHERE id=?', (target_uid,))
        conn.commit()
        conn.close()

        log_admin_action(uid, 'block_refs', 'user', target_uid)
        q.answer("Рефералы обнулены и заблокированы!", show_alert=True)

    elif d.startswith('user_admin_'):
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return
        target_uid = int(d.replace('user_admin_', ''))
        back_to = context.user_data.get('user_info_back_to', 'admin_users')

        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute('SELECT id FROM admins WHERE id=?', (target_uid,))
        is_admin_user = c.fetchone() is not None
        conn.close()

        if is_admin_user:
            q.edit_message_text(
                f"👨‍💻 Управление админкой пользователя {target_uid}\n\nСтатус: 👨‍💻 АДМИН",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("❌ Снять админку", callback_data=f'user_remove_admin_{target_uid}')],
                    [InlineKeyboardButton("🔙 Назад", callback_data=f'user_info_{target_uid}_{back_to}')]
                ])
            )
        else:
            q.edit_message_text(
                f"👨‍💻 Управление админкой пользователя {target_uid}\n\nСтатус: 👤 Пользователь",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Дать админку", callback_data=f'user_give_admin_{target_uid}')],
                    [InlineKeyboardButton("🔙 Назад", callback_data=f'user_info_{target_uid}_{back_to}')]
                ])
            )

    elif d.startswith('user_give_admin_'):
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return
        target_uid = int(d.replace('user_give_admin_', ''))
        back_to = context.user_data.get('user_info_back_to', 'admin_users')

        if add_admin(target_uid, uid):
            log_admin_action(uid, 'give_admin', 'user', target_uid)
            q.answer("Админка выдана!", show_alert=True)
            # Refresh user info page
            d = f'user_info_{target_uid}_{back_to}'
            _btn_handler(q, uid, d, context)
        else:
            q.answer("Ошибка при выдаче админки!", show_alert=True)

    elif d.startswith('user_remove_admin_'):
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return
        target_uid = int(d.replace('user_remove_admin_', ''))
        back_to = context.user_data.get('user_info_back_to', 'admin_users')

        # Prevent removing yourself
        if target_uid == uid:
            q.answer("Вы не можете снять себе админку!", show_alert=True); return

        remove_admin(target_uid)
        log_admin_action(uid, 'remove_admin', 'user', target_uid)
        q.answer("Админка снята!", show_alert=True)
        # Refresh user info page
        d = f'user_info_{target_uid}_{back_to}'
        _btn_handler(q, uid, d, context)

    elif d.startswith('user_toggle_block_'):
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return
        target_uid = int(d.replace('user_toggle_block_', ''))
        back_to = context.user_data.get('user_info_back_to', 'admin_users')

        row = get_user(target_uid)
        is_blocked = row[14] if len(row) > 14 else 0

        if is_blocked:
            unblock_user(target_uid)
            log_admin_action(uid, 'unblock', 'user', target_uid)
            q.answer("Пользователь разблокирован!", show_alert=True)
        else:
            block_user(target_uid)
            log_admin_action(uid, 'block', 'user', target_uid)
            q.answer("Пользователь заблокирован!", show_alert=True)

        # Refresh user info page
        d = f'user_info_{target_uid}_{back_to}'
        _btn_handler(q, uid, d, context)

    elif d.startswith('user_rollback_confirm_'):
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return
        target_uid = int(d.replace('user_rollback_confirm_', ''))
        back_to = context.user_data.get('user_info_back_to', 'admin_users')

        # Prevent rolling back yourself
        if target_uid == uid:
            q.answer("Вы не можете откатить себя!", show_alert=True); return

        q.edit_message_text(
            f"⚠️ ПОДТВЕРЖДЕНИЕ ОТКАТА\n\n"
            f"Вы собираетесь полностью откатить пользователя {target_uid}!\n\n"
            f"Это действие:\n"
            f"• Удалит всю историю игр пользователя\n"
            f"• Удалит все активированные промокоды\n"
            f"• Удалит все логи действий админа с этим пользователем\n"
            f"• Сбросит баланс на 500 монет\n"
            f"• Сбросит статистику пользователя\n\n"
            f"⚠️ ЭТО ДЕЙСТВИЕ НЕОБРАТИМО!\n\n"
            f"Вы уверены?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Да, откатить", callback_data=f'user_rollback_do_{target_uid}')],
                [InlineKeyboardButton("❌ Отмена", callback_data=f'user_info_{target_uid}_{back_to}')]
            ])
        )

    elif d.startswith('user_rollback_do_'):
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return
        target_uid = int(d.replace('user_rollback_do_', ''))
        back_to = context.user_data.get('user_info_back_to', 'admin_users')

        # Prevent rolling back yourself
        if target_uid == uid:
            q.answer("Вы не можете откатить себя!", show_alert=True); return

        success, message = rollback_user_completely(target_uid)

        if success:
            log_admin_action(uid, 'rollback_user', 'user', target_uid, message)
            q.edit_message_text(
                f"✅ {message}\n\nПользователь откачен успешно!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data=f'user_info_{target_uid}_{back_to}')]])
            )
        else:
            q.answer(message, show_alert=True)

    elif d == 'admin_broadcasts':
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return
        q.edit_message_text(
            "📢 Рассылки\n\nВыберите действие:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📝 Текстовая рассылка", callback_data='admin_broadcast_text')],
                [InlineKeyboardButton("🖼️ Рассылка с фото", callback_data='admin_broadcast_photo')],
                [InlineKeyboardButton("📋 История рассылок", callback_data='admin_broadcast_history')],
                [InlineKeyboardButton("🔙 Назад", callback_data='admin_menu')]
            ])
        )

    elif d == 'admin_broadcast_text':
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return
        q.edit_message_text(
            "📝 Текстовая рассылка\n\nВведите текст сообщения:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='admin_broadcasts')]]))
        context.user_data['state'] = 'admin_broadcast_text'

    elif d == 'admin_broadcast_photo':
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return
        q.edit_message_text(
            "🖼️ Рассылка с фото\n\nОтправьте фото с подписью (или просто текст подписи):",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='admin_broadcasts')]]))
        context.user_data['state'] = 'admin_broadcast_photo'

    elif d == 'admin_broadcast_history':
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return
        broadcasts = get_broadcasts()

        if not broadcasts:
            q.edit_message_text("📋 История рассылок пуста",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='admin_broadcasts')]]))
            return

        text = "📋 История рассылок\n\n"
        for i, b in enumerate(broadcasts[:5]):
            b_id, msg_type, content, file_id, scheduled, status, sent_at, created_by = b
            status_emoji = "✅" if status == 'sent' else "⏳"
            text += f"{status_emoji} #{b_id}: {msg_type}\n"
            if scheduled:
                text += f"   Запланировано: {scheduled}\n"
            elif sent_at:
                text += f"   Отправлено: {sent_at}\n"

        q.edit_message_text(text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='admin_broadcasts')]]))

    elif d == 'admin_promos':
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return
        q.edit_message_text(
            "🎫 Управление промокодами\n\nВыберите действие:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Активные", callback_data='admin_promos_active')],
                [InlineKeyboardButton("📅 Истекшие", callback_data='admin_promos_expired')],
                [InlineKeyboardButton("➕ Создать промокод", callback_data='admin_promo_create')],
                [InlineKeyboardButton("🗑️ Очистить все промокоды", callback_data='admin_promos_clear_confirm')],
                [InlineKeyboardButton("🔙 Назад", callback_data='admin_menu')]
            ])
        )

    elif d == 'admin_promos_clear_confirm':
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return
        q.edit_message_text(
            "⚠️ ПОДТВЕРЖДЕНИЕ ОЧИСТКИ\n\n"
            "Вы собираетесь удалить ВСЕ промокоды и их историю использования!\n\n"
            "⚠️ ЭТО ДЕЙСТВИЕ НЕОБРАТИМО!\n\n"
            "Вы уверены?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Да, удалить все", callback_data='admin_promos_clear_do')],
                [InlineKeyboardButton("❌ Отмена", callback_data='admin_promos')]
            ])
        )

    elif d == 'admin_promos_clear_do':
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return
        clear_all_promocodes()
        log_admin_action(uid, 'clear_all_promos', 'all', 0, 'All promocodes deleted')
        q.edit_message_text(
            "✅ Все промокоды удалены!\n\nВключая историю использования.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='admin_promos')]])
        )

    elif d == 'admin_promos_active':
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return

        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        # Активные промокоды: не удалены И (нет лимита ИЛИ лимит еще не достигнут)
        c.execute('''SELECT * FROM promocodes 
                     WHERE deleted=0 AND (max_uses IS NULL OR uses < max_uses) 
                     ORDER BY created_at DESC''')
        promos = c.fetchall()
        conn.close()

        if not promos:
            q.edit_message_text("🎫 Активных промокодов нет",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ Создать промокод", callback_data='admin_promo_create')],
                    [InlineKeyboardButton("🔙 Назад", callback_data='admin_promos')]
                ]))
            return

        text = "🎫 Активные промокоды\n\n"
        kb = []
        for p in promos:
            p_id, code, reward, max_uses, uses, max_per_user, created_by, deleted = p
            uses_info = f"{uses}/{max_uses}" if max_uses else f"{uses}/∞"
            kb.append([InlineKeyboardButton(f"✅ {code}: +{reward} ({uses_info})", callback_data=f'admin_promo_detail_{code}')])

        kb.append([InlineKeyboardButton("🔙 Назад", callback_data='admin_promos')])

        q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

    elif d == 'admin_promos_expired':
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return

        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        # Истекшие промокоды: удалены ИЛИ лимит достигнут
        c.execute('''SELECT * FROM promocodes 
                     WHERE deleted=1 OR (max_uses IS NOT NULL AND uses >= max_uses) 
                     ORDER BY created_at DESC''')
        promos = c.fetchall()
        conn.close()

        if not promos:
            q.edit_message_text("🎫 Истекших промокодов нет",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='admin_promos')]]))
            return

        text = "🎫 Истекшие промокоды\n\n"
        kb = []
        for p in promos:
            p_id, code, reward, max_uses, uses, max_per_user, created_by, deleted = p
            uses_info = f"{uses}/{max_uses}" if max_uses else f"{uses}/∞"
            expired_reason = "Удален" if deleted else "Лимит исчерпан"
            kb.append([InlineKeyboardButton(f"❌ {code}: +{reward} ({uses_info}) [{expired_reason}]", callback_data=f'admin_promo_detail_{code}')])

        kb.append([InlineKeyboardButton("🔙 Назад", callback_data='admin_promos')])

        q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

    elif d.startswith('admin_promo_detail_'):
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return
        code = d.replace('admin_promo_detail_', '')

        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute('SELECT * FROM promocodes WHERE code=?', (code,))
        promo = c.fetchone()
        if not promo:
            conn.close()
            q.answer("Промокод не найден!", show_alert=True); return

        p_id, p_code, reward, max_uses, uses, max_per_user, created_by, deleted = promo

        # Get usage statistics
        c.execute('SELECT pu.uid, u.username, COUNT(*) as cnt FROM promo_usage pu LEFT JOIN users u ON pu.uid=u.id WHERE pu.code=? GROUP BY pu.uid ORDER BY cnt DESC LIMIT 10', (code,))
        usage = c.fetchall()
        conn.close()

        uses_info = f"{uses}/{max_uses}" if max_uses else f"{uses}/∞"
        status = "🚫 Истек/Удален" if deleted else "✅ Активен"

        text = (
            f"🎫 Промокод: {code}\n"
            f"💰 Награда: {reward} монет\n"
            f"📊 Использований: {uses_info}\n"
            f"👤 На пользователя: {max_per_user} раз\n"
            f"📅 Статус: {status}\n"
        )

        if usage:
            text += f"\n📊 Топ-10 использований:\n"
            for u_id, username, cnt in usage:
                name = username if username else f"ID:{u_id}"
                text += f"• {name}: {cnt} раз\n"

        # Delete button for both active and expired promos
        q.edit_message_text(text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🗑️ Удалить промокод", callback_data=f'admin_promo_delete_{code}')],
                [InlineKeyboardButton("🔙 Назад", callback_data='admin_promos')]
            ])
        )

    elif d.startswith('admin_promo_delete_'):
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return
        code = d.replace('admin_promo_delete_', '')

        # Delete promocode completely
        delete_promocode(code)
        log_admin_action(uid, 'delete_promo', 'promocode', code)

        # Return to promos menu
        q.edit_message_text(
            "🎫 Управление промокодами\n\nВыберите действие:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Активные", callback_data='admin_promos_active')],
                [InlineKeyboardButton("📅 Истекшие", callback_data='admin_promos_expired')],
                [InlineKeyboardButton("➕ Создать промокод", callback_data='admin_promo_create')],
                [InlineKeyboardButton("🔙 Назад", callback_data='admin_menu')]
            ])
        )

    elif d == 'admin_promo_create':
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return
        q.edit_message_text(
            "🎫 Создание промокода\n\nФормат: КОД НАГРАДА [МАКС_ИСПОЛЬЗОВАНИЙ] [МАКС_НА_ПОЛЬЗОВАТЕЛЯ]\n\n"
            "Пример: BONUS2025 500 100 1\n"
            "Это создаст промокод BONUS2025 на 500 монет, максимум 100 использований, 1 на пользователя.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='admin_promos')]]))
        context.user_data['state'] = 'admin_promo_create'

    elif d == 'admin_admins':
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute('''SELECT a.id, a.added_by, a.added_at, u.username FROM admins a
                     LEFT JOIN users u ON a.id = u.id ORDER BY a.id''')
        admins = c.fetchall()
        conn.close()

        text = "👨‍💻 Админы бота\n\n"

        if not admins:
            text += "Админов нет"
            kb = [[InlineKeyboardButton("➕ Добавить админа", callback_data='admin_add_admin')]]
        else:
            kb = []
            for a_id, added_by, added_at, a_uname in admins:
                name = a_uname if a_uname else f"ID:{a_id}"
                kb.append([InlineKeyboardButton(f"👤 {name} (ID: {a_id})", callback_data=f'user_info_{a_id}')])
            kb.append([InlineKeyboardButton("➕ Добавить админа", callback_data='admin_add_admin')])

        kb.append([InlineKeyboardButton("🔙 Назад", callback_data='admin_menu')])

        q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

    elif d == 'admin_add_admin':
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return
        q.edit_message_text(
            "➕ Добавление админа\n\nВведите ID или username пользователя:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='admin_admins')]]))
        context.user_data['state'] = 'admin_add_admin'

    elif d == 'admin_logs':
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return
        q.edit_message_text(
            "📜 Логи действий\n\nВыберите тип логов:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👤 Пользовательские", callback_data='admin_logs_users')],
                [InlineKeyboardButton("👨‍💻 Админские", callback_data='admin_logs_admin')],
                [InlineKeyboardButton("🔙 Назад", callback_data='admin_menu')]
            ])
        )

    elif d == 'admin_logs_users' or d == 'admin_logs_users_show_all' or d == 'admin_logs_users_paged':
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return

        # Determine filter: None (all), False (not rolled back), True (rolled back)
        rolled_back = context.user_data.get('admin_logs_users_filter', None)
        rolled_back_text = {
            None: "Все",
            False: "Неоткатанные",
            True: "Откатанные"
        }[rolled_back]

        # Режим показа: постраничный или всё
        show_all = context.user_data.get('admin_logs_users_show_all', False)
        
        # Обрабатываем переключение режима
        if d == 'admin_logs_users_show_all':
            show_all = True
            context.user_data['admin_logs_users_show_all'] = True
        elif d == 'admin_logs_users_paged':
            show_all = False
            context.user_data['admin_logs_users_show_all'] = False
            context.user_data['admin_logs_users_page'] = 0
        
        page = context.user_data.get('admin_logs_users_page', 0)
        
        # Лимит: 50 для "показать всё", 10 для постраничного
        if show_all:
            page_size = 50
            offset = 0
        else:
            page_size = 10
            offset = page * page_size

        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        if rolled_back is None:
            c.execute('SELECT COUNT(*) FROM game_history')
            total = c.fetchone()[0]
            c.execute('SELECT * FROM game_history ORDER BY id DESC LIMIT ? OFFSET ?', (page_size, offset))
        elif rolled_back:
            # Откатанные: is_rolled_back = 1
            c.execute('SELECT COUNT(*) FROM game_history WHERE is_rolled_back=1')
            total = c.fetchone()[0]
            c.execute('SELECT * FROM game_history WHERE is_rolled_back=1 ORDER BY id DESC LIMIT ? OFFSET ?',
                      (page_size, offset))
        else:
            # Неоткатанные: is_rolled_back = 0 или NULL
            c.execute('SELECT COUNT(*) FROM game_history WHERE is_rolled_back=0 OR is_rolled_back IS NULL')
            total = c.fetchone()[0]
            c.execute('SELECT * FROM game_history WHERE is_rolled_back=0 OR is_rolled_back IS NULL ORDER BY id DESC LIMIT ? OFFSET ?',
                      (page_size, offset))
        logs = c.fetchall()

        # Get usernames for all users in logs
        user_ids = list(set([log[1] for log in logs]))
        usernames = {}
        for user_id in user_ids:
            c.execute('SELECT username FROM users WHERE id=?', (user_id,))
            row = c.fetchone()
            usernames[user_id] = row[0] if row and row[0] else f"ID:{user_id}"

        conn.close()

        if not logs:
            q.edit_message_text(f"📜 Пользовательские логи ({rolled_back_text}) пусты",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Все", callback_data='admin_logs_users_filter_all'),
                     InlineKeyboardButton("✅ Неоткатанные", callback_data='admin_logs_users_filter_active'),
                     InlineKeyboardButton("↩️ Откатанные", callback_data='admin_logs_users_filter_rolled')],
                    [InlineKeyboardButton("🔙 Назад", callback_data='admin_logs')]
                ]))
            return

        pages = (total + 9) // 10 or 1
        
        if show_all:
            text = f"📜 Пользовательские логи ({rolled_back_text}) — ВСЁ\n━━━━━━━━━━━━━━━━\nПоказано: {len(logs)} из {total}\n\n"
            for log in logs:
                gid, g_uid, gname, details, amount, is_win, is_rolled_back, created_at = log
                g_emoji = GAME_EMOJIS.get(gname, '🎮')
                res_emoji = "✅" if is_win else "❌"
                rolled_emoji = "↩️" if is_game_rolled_back(is_rolled_back) else ""
                sign = "+" if is_win else "-"
                uname = usernames.get(g_uid, f"ID:{g_uid}")
                text += f"{res_emoji} {rolled_emoji} {g_emoji} {uname} {gname}: {sign}{amount}\n"
            
            kb = []
            # Кнопки фильтров
            kb.append([
                InlineKeyboardButton("🔄 Все", callback_data='admin_logs_users_filter_all'),
                InlineKeyboardButton("✅ Неоткатанные", callback_data='admin_logs_users_filter_active'),
                InlineKeyboardButton("↩️ Откатанные", callback_data='admin_logs_users_filter_rolled')
            ])
            kb.append([InlineKeyboardButton("📄 Постраничный вид", callback_data='admin_logs_users_paged')])
            kb.append([InlineKeyboardButton("🔙 Назад", callback_data='admin_logs')])
        else:
            text = f"📜 Пользовательские логи ({rolled_back_text})\n━━━━━━━━━━━━━━━━\nСтраница {page+1} из {pages} | Всего: {total}\n\n"

            kb = []
            for log in logs:
                gid, g_uid, gname, details, amount, is_win, is_rolled_back, created_at = log
                g_emoji = GAME_EMOJIS.get(gname, '🎮')
                res_emoji = "✅" if is_win else "❌"
                # Проверяем is_rolled_back: 1 = откатан, 0 или None = не откатан
                rolled_emoji = "↩️" if is_game_rolled_back(is_rolled_back) else ""
                sign = "+" if is_win else "-"
                uname = usernames.get(g_uid, f"ID:{g_uid}")
                kb.append([InlineKeyboardButton(
                    f"{res_emoji} {rolled_emoji} {g_emoji} {uname} {gname}: {sign}{amount}",
                    callback_data=f'admin_log_detail_game_{gid}'
                )])

            # Filter buttons
            kb.append([
                InlineKeyboardButton("🔄 Все", callback_data='admin_logs_users_filter_all'),
                InlineKeyboardButton("✅ Неоткатанные", callback_data='admin_logs_users_filter_active'),
                InlineKeyboardButton("↩️ Откатанные", callback_data='admin_logs_users_filter_rolled')
            ])

            # Pagination buttons
            nav_row = []
            if page > 0:
                nav_row.append(InlineKeyboardButton("◀️", callback_data='admin_logs_users_prev'))
            nav_row.append(InlineKeyboardButton(f"{page+1}/{pages}", callback_data='admin_logs_users_goto_menu'))
            if (page + 1) * 10 < total:
                nav_row.append(InlineKeyboardButton("▶️", callback_data='admin_logs_users_next'))
            if len(nav_row) > 1:
                kb.append(nav_row)
            
            kb.append([InlineKeyboardButton("📄 Показать всё", callback_data='admin_logs_users_show_all')])
            kb.append([InlineKeyboardButton("☑️ Массовый откат", callback_data='admin_logs_users_multi_mode')])
            kb.append([InlineKeyboardButton("🔙 Назад", callback_data='admin_logs')])

        q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

    elif d == 'admin_logs_users_multi_mode' or d.startswith('admin_logs_users_multi_') or d == 'admin_logs_users_multi_select_all' or d == 'admin_logs_users_multi_deselect_all' or d == 'admin_logs_users_multi_confirm' or d == 'admin_logs_users_multi_execute':
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return

        # Инициализация режима мульти-выбора
        if d == 'admin_logs_users_multi_mode':
            context.user_data['admin_logs_users_multi'] = []
            context.user_data['admin_logs_users_multi_page'] = 0
        
        # Получаем текущий фильтр
        rolled_back = context.user_data.get('admin_logs_users_filter', None)
        rolled_back_text = {
            None: "Все",
            False: "Неоткатанные",
            True: "Откатанные"
        }[rolled_back]

        # Выбранные игры
        selected = context.user_data.get('admin_logs_users_multi', [])
        
        # Обработка выбора/отмены выбора игры
        if d.startswith('admin_logs_users_multi_select_'):
            gid = int(d.replace('admin_logs_users_multi_select_', ''))
            if gid not in selected:
                selected.append(gid)
                context.user_data['admin_logs_users_multi'] = selected
            # Перерисовываем текущую страницу
            d = 'admin_logs_users_multi_mode'
            _btn_handler(q, uid, d, context)
            return

        if d.startswith('admin_logs_users_multi_deselect_'):
            gid = int(d.replace('admin_logs_users_multi_deselect_', ''))
            if gid in selected:
                selected.remove(gid)
                context.user_data['admin_logs_users_multi'] = selected
            # Перерисовываем текущую страницу
            d = 'admin_logs_users_multi_mode'
            _btn_handler(q, uid, d, context)
            return

        # Выбрать все на странице
        if d == 'admin_logs_users_multi_select_all':
            page = context.user_data.get('admin_logs_users_multi_page', 0)
            page_size = 10
            offset = page * page_size
            
            conn = sqlite3.connect(DB_PATH); c = conn.cursor()
            if rolled_back is None:
                c.execute('SELECT id FROM game_history ORDER BY id DESC LIMIT ? OFFSET ?', (page_size, offset))
            elif rolled_back:
                c.execute('SELECT id FROM game_history WHERE is_rolled_back=1 ORDER BY id DESC LIMIT ? OFFSET ?', (page_size, offset))
            else:
                c.execute('SELECT id FROM game_history WHERE is_rolled_back=0 OR is_rolled_back IS NULL ORDER BY id DESC LIMIT ? OFFSET ?', (page_size, offset))
            game_ids = [r[0] for r in c.fetchall()]
            conn.close()
            
            for gid in game_ids:
                if gid not in selected:
                    selected.append(gid)
            context.user_data['admin_logs_users_multi'] = selected
            d = 'admin_logs_users_multi_mode'
            _btn_handler(q, uid, d, context)
            return
        
        # Снять выделение со всех
        if d == 'admin_logs_users_multi_deselect_all':
            context.user_data['admin_logs_users_multi'] = []
            selected = []
            d = 'admin_logs_users_multi_mode'
            _btn_handler(q, uid, d, context)
            return
        
        # Подтверждение массового отката
        if d == 'admin_logs_users_multi_confirm':
            if not selected:
                q.answer("Нет выбранных игр!", show_alert=True)
                return

            # Получаем информацию о выбранных играх
            conn = sqlite3.connect(DB_PATH); c = conn.cursor()
            placeholders = ','.join('?' * len(selected))
            c.execute(f'SELECT id, uid, game_name, amount, is_win, is_rolled_back FROM game_history WHERE id IN ({placeholders})', selected)
            games = c.fetchall()
            conn.close()

            total_amount = 0
            wins = 0
            losses = 0
            for gid, g_uid, gname, amount, is_win, is_rolled in games:
                # Если игра не откатана, считаем сумму
                if not is_game_rolled_back(is_rolled):
                    if is_win:
                        total_amount += amount
                        wins += 1
                    else:
                        total_amount -= amount
                        losses += 1
            
            text = (
                f"⚠️ ПОДТВЕРЖДЕНИЕ МАССОВОГО ОТКАТА\n\n"
                f"Выбрано игр: {len(selected)}\n"
                f"Выигрышей: {wins}\n"
                f"Проигрышей: {losses}\n"
                f"Общая сумма: {'+' if total_amount >= 0 else ''}{total_amount} монет\n\n"
                f"⚠️ Это действие откатит все выбранные игры!\n\n"
                f"Продолжить?"
            )
            
            kb = [
                [InlineKeyboardButton("✅ Да, откатить", callback_data='admin_logs_users_multi_execute')],
                [InlineKeyboardButton("❌ Отмена", callback_data='admin_logs_users_multi_mode')]
            ]
            
            q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))
            return
        
        # Выполнение массового отката
        if d == 'admin_logs_users_multi_execute':
            if not selected:
                q.answer("Нет выбранных игр!", show_alert=True)
                return

            success_count = 0
            error_count = 0
            
            for gid in selected:
                success, msg = rollback_game(gid)
                if success:
                    success_count += 1
                else:
                    error_count += 1
            
            # Очищаем выбор
            context.user_data['admin_logs_users_multi'] = []
            
            result_text = (
                f"✅ Массовый откат завершён!\n\n"
                f"Успешно: {success_count}\n"
                f"Ошибок: {error_count}"
            )
            
            q.edit_message_text(result_text,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 К логам", callback_data='admin_logs_users')]
                ]))
            return
        
        # Отображение списка игр с чекбоксами
        page = context.user_data.get('admin_logs_users_multi_page', 0)
        page_size = 10
        offset = page * page_size
        
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        if rolled_back is None:
            c.execute('SELECT COUNT(*) FROM game_history')
            total = c.fetchone()[0]
            c.execute('SELECT * FROM game_history ORDER BY id DESC LIMIT ? OFFSET ?', (page_size, offset))
        elif rolled_back:
            c.execute('SELECT COUNT(*) FROM game_history WHERE is_rolled_back=1')
            total = c.fetchone()[0]
            c.execute('SELECT * FROM game_history WHERE is_rolled_back=1 ORDER BY id DESC LIMIT ? OFFSET ?', (page_size, offset))
        else:
            c.execute('SELECT COUNT(*) FROM game_history WHERE is_rolled_back=0 OR is_rolled_back IS NULL')
            total = c.fetchone()[0]
            c.execute('SELECT * FROM game_history WHERE is_rolled_back=0 OR is_rolled_back IS NULL ORDER BY id DESC LIMIT ? OFFSET ?', (page_size, offset))
        logs = c.fetchall()
        
        # Получаем usernames
        user_ids = list(set([log[1] for log in logs]))
        usernames = {}
        for user_id in user_ids:
            c.execute('SELECT username FROM users WHERE id=?', (user_id,))
            row = c.fetchone()
            usernames[user_id] = row[0] if row and row[0] else f"ID:{user_id}"
        conn.close()
        
        pages = (total + 9) // 10 or 1
        
        text = f"☑️ Массовый откат ({rolled_back_text})\n━━━━━━━━━━━━━━━━\nВыбрано: {len(selected)} | Страница {page+1}/{pages}\n\nНажмите на игру для выбора/отмены:"
        
        kb = []
        for log in logs:
            gid, g_uid, gname, details, amount, is_win, is_rolled_back, created_at = log
            g_emoji = GAME_EMOJIS.get(gname, '🎮')
            res_emoji = "✅" if is_win else "❌"
            rolled_emoji = "↩️" if is_game_rolled_back(is_rolled_back) else ""
            sign = "+" if is_win else "-"
            uname = usernames.get(g_uid, f"ID:{g_uid}")
            
            # Определяем, выбрана ли игра
            is_selected = gid in selected
            check = "☑️ " if is_selected else "⬜ "
            
            # Если игра уже откатана, показываем это
            if is_game_rolled_back(is_rolled_back):
                check = "↩️ "
            
            kb.append([InlineKeyboardButton(
                f"{check}{res_emoji} {g_emoji} {uname} {gname}: {sign}{amount}",
                callback_data=f'admin_logs_users_multi_deselect_{gid}' if is_selected else f'admin_logs_users_multi_select_{gid}'
            )])
        
        # Кнопки управления
        kb.append([
            InlineKeyboardButton("☑️ Выбрать все", callback_data='admin_logs_users_multi_select_all'),
            InlineKeyboardButton("⬜ Снять все", callback_data='admin_logs_users_multi_deselect_all')
        ])
        
        # Навигация
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton("◀️", callback_data='admin_logs_users_multi_prev'))
        nav_row.append(InlineKeyboardButton(f"{page+1}/{pages}", callback_data='dummy'))
        if (page + 1) * 10 < total:
            nav_row.append(InlineKeyboardButton("▶️", callback_data='admin_logs_users_multi_next'))
        if len(nav_row) > 1:
            kb.append(nav_row)
        
        # Кнопка подтверждения (если есть выбранные)
        if selected:
            kb.append([InlineKeyboardButton(f"✅ Откатить {len(selected)} игр", callback_data='admin_logs_users_multi_confirm')])
        
        kb.append([InlineKeyboardButton("❌ Отмена", callback_data='admin_logs_users')])
        
        q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))
    
    elif d == 'admin_logs_users_multi_prev':
        page = context.user_data.get('admin_logs_users_multi_page', 0)
        if page > 0:
            context.user_data['admin_logs_users_multi_page'] = page - 1
        d = 'admin_logs_users_multi_mode'
        _btn_handler(q, uid, d, context)
    
    elif d == 'admin_logs_users_multi_next':
        page = context.user_data.get('admin_logs_users_multi_page', 0)
        page_size = 10
        rolled_back = context.user_data.get('admin_logs_users_filter', None)
        
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        if rolled_back is None:
            c.execute('SELECT COUNT(*) FROM game_history')
        elif rolled_back:
            c.execute('SELECT COUNT(*) FROM game_history WHERE is_rolled_back=1')
        else:
            c.execute('SELECT COUNT(*) FROM game_history WHERE is_rolled_back=0 OR is_rolled_back IS NULL')
        total = c.fetchone()[0]
        conn.close()
        
        pages = (total + 9) // 10 or 1
        if page + 1 < pages:
            context.user_data['admin_logs_users_multi_page'] = page + 1
        d = 'admin_logs_users_multi_mode'
        _btn_handler(q, uid, d, context)

    elif d == 'admin_logs_users_goto_menu':
        # Меню перехода на конкретную страницу
        rolled_back = context.user_data.get('admin_logs_users_filter', None)
        current_page = context.user_data.get('admin_logs_users_page', 0)
        
        # Получаем общее количество
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        if rolled_back is None:
            c.execute('SELECT COUNT(*) FROM game_history')
        elif rolled_back:
            c.execute('SELECT COUNT(*) FROM game_history WHERE is_rolled_back=1')
        else:
            c.execute('SELECT COUNT(*) FROM game_history WHERE is_rolled_back=0 OR is_rolled_back IS NULL')
        total = c.fetchone()[0]
        conn.close()

        pages = (total + 9) // 10 or 1
        
        # Показываем все страницы в виде сетки (по 5 в ряд)
        kb = []
        row = []
        for i in range(pages):
            if i == current_page:
                row.append(InlineKeyboardButton(f"▶ {i+1}", callback_data='dummy'))
            else:
                row.append(InlineKeyboardButton(f"{i+1}", callback_data=f'admin_logs_users_page_{i}'))
            if len(row) == 5:
                kb.append(row)
                row = []
        if row:
            kb.append(row)
        
        kb.append([InlineKeyboardButton("🔙 Назад", callback_data='admin_logs_users')])
        
        q.edit_message_text(
            f"📄 Выбор страницы (всего {pages} страниц):",
            reply_markup=InlineKeyboardMarkup(kb)
        )

    elif d == 'admin_logs_users_filter_all':
        context.user_data['admin_logs_users_filter'] = None
        context.user_data['admin_logs_users_page'] = 0
        d = 'admin_logs_users'
        _btn_handler(q, uid, d, context)

    elif d == 'admin_logs_users_filter_active':
        context.user_data['admin_logs_users_filter'] = False
        context.user_data['admin_logs_users_page'] = 0
        d = 'admin_logs_users'
        _btn_handler(q, uid, d, context)

    elif d == 'admin_logs_users_filter_rolled':
        context.user_data['admin_logs_users_filter'] = True
        context.user_data['admin_logs_users_page'] = 0
        d = 'admin_logs_users'
        _btn_handler(q, uid, d, context)

    elif d == 'admin_logs_users_prev':
        page = context.user_data.get('admin_logs_users_page', 0)
        if page > 0:
            context.user_data['admin_logs_users_page'] = page - 1
        else:
            # Валидация: не выходим за пределы
            context.user_data['admin_logs_users_page'] = 0
        d = 'admin_logs_users'
        _btn_handler(q, uid, d, context)

    elif d == 'admin_logs_users_next':
        page = context.user_data.get('admin_logs_users_page', 0)
        page_size = 10
        rolled_back = context.user_data.get('admin_logs_users_filter', None)
        
        # Получаем общее количество для валидации
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        if rolled_back is None:
            c.execute('SELECT COUNT(*) FROM game_history')
        elif rolled_back:
            c.execute('SELECT COUNT(*) FROM game_history WHERE is_rolled_back=1')
        else:
            c.execute('SELECT COUNT(*) FROM game_history WHERE is_rolled_back=0 OR is_rolled_back IS NULL')
        total = c.fetchone()[0]
        conn.close()

        pages = (total + page_size - 1) // page_size if total > 0 else 1
        if page + 1 < pages:
            context.user_data['admin_logs_users_page'] = page + 1
        d = 'admin_logs_users'
        _btn_handler(q, uid, d, context)

    elif d.startswith('admin_logs_users_page_'):
        page_num = int(d.replace('admin_logs_users_page_', ''))
        page_size = 10
        rolled_back = context.user_data.get('admin_logs_users_filter', None)
        
        # Валидация страницы
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        if rolled_back is None:
            c.execute('SELECT COUNT(*) FROM game_history')
        elif rolled_back:
            c.execute('SELECT COUNT(*) FROM game_history WHERE is_rolled_back=1')
        else:
            c.execute('SELECT COUNT(*) FROM game_history WHERE is_rolled_back=0 OR is_rolled_back IS NULL')
        total = c.fetchone()[0]
        conn.close()

        pages = (total + page_size - 1) // page_size if total > 0 else 1
        if page_num >= pages:
            page_num = pages - 1
        if page_num < 0:
            page_num = 0
            
        context.user_data['admin_logs_users_page'] = page_num
        d = 'admin_logs_users'
        _btn_handler(q, uid, d, context)

    elif d == 'admin_logs_admin' or d == 'admin_logs_admin_show_all' or d == 'admin_logs_admin_paged':
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return

        # Determine filter: None (all), False (not rolled back), True (rolled back)
        rolled_back = context.user_data.get('admin_logs_admin_filter', None)
        rolled_back_text = {
            None: "Все",
            False: "Неоткатанные",
            True: "Откатанные"
        }[rolled_back]

        # Режим показа: постраничный или всё
        show_all = context.user_data.get('admin_logs_admin_show_all', False)
        
        # Обрабатываем переключение режима
        if d == 'admin_logs_admin_show_all':
            show_all = True
            context.user_data['admin_logs_admin_show_all'] = True
        elif d == 'admin_logs_admin_paged':
            show_all = False
            context.user_data['admin_logs_admin_show_all'] = False
            context.user_data['admin_logs_admin_page'] = 0
        
        page = context.user_data.get('admin_logs_admin_page', 0)
        
        # Лимит: 50 для "показать всё", 10 для постраничного
        if show_all:
            page_size = 50
            offset = 0
        else:
            page_size = 10
            offset = page * page_size

        logs, total = get_admin_logs(limit=page_size, offset=offset, rolled_back=rolled_back)

        if not logs:
            q.edit_message_text(f"📜 Админские логи ({rolled_back_text}) пусты",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Все", callback_data='admin_logs_admin_filter_all'),
                     InlineKeyboardButton("✅ Неоткатанные", callback_data='admin_logs_admin_filter_active'),
                     InlineKeyboardButton("↩️ Откатанные", callback_data='admin_logs_admin_filter_rolled')],
                    [InlineKeyboardButton("🔙 Назад", callback_data='admin_logs')]
                ]))
            return

        # Get admin usernames
        admin_ids = list(set([log[1] for log in logs]))
        admin_names = {}
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        for aid in admin_ids:
            c.execute('SELECT username FROM users WHERE id=?', (aid,))
            row = c.fetchone()
            admin_names[aid] = row[0] if row and row[0] else f"ID:{aid}"
        conn.close()

        pages = (total + 9) // 10 or 1
        
        if show_all:
            text = f"📜 Админские логи ({rolled_back_text}) — ВСЁ\n━━━━━━━━━━━━━━━━\nПоказано: {len(logs)} из {total}\n\n"
            for log in logs:
                l_id, admin_id, action, target_type, target_id, details, is_rolled_back, created_at = log
                action_desc = get_action_description(action, target_type, target_id)
                rolled_emoji = "↩️" if is_game_rolled_back(is_rolled_back) else ""
                admin_name = admin_names.get(admin_id, f"ID:{admin_id}")
                text += f"{rolled_emoji} {admin_name}: {action_desc}\n"
            
            kb = []
            # Кнопки фильтров
            kb.append([
                InlineKeyboardButton("🔄 Все", callback_data='admin_logs_admin_filter_all'),
                InlineKeyboardButton("✅ Неоткатанные", callback_data='admin_logs_admin_filter_active'),
                InlineKeyboardButton("↩️ Откатанные", callback_data='admin_logs_admin_filter_rolled')
            ])
            kb.append([InlineKeyboardButton("📄 Постраничный вид", callback_data='admin_logs_admin_paged')])
            kb.append([InlineKeyboardButton("🔙 Назад", callback_data='admin_logs')])
        else:
            text = f"📜 Админские логи ({rolled_back_text})\n━━━━━━━━━━━━━━━━\nСтраница {page+1} из {pages} | Всего: {total}\n\n"

            kb = []
            for log in logs:
                l_id, admin_id, action, target_type, target_id, details, is_rolled_back, created_at = log
                action_desc = get_action_description(action, target_type, target_id)
                # Проверяем is_rolled_back: 1 = откатан, 0 или None = не откатан
                rolled_emoji = "↩️" if is_game_rolled_back(is_rolled_back) else ""
                admin_name = admin_names.get(admin_id, f"ID:{admin_id}")
                kb.append([InlineKeyboardButton(
                    f"{rolled_emoji} {admin_name}: {action_desc}",
                    callback_data=f'admin_log_detail_admin_{l_id}'
                )])

            # Filter buttons
            kb.append([
                InlineKeyboardButton("🔄 Все", callback_data='admin_logs_admin_filter_all'),
                InlineKeyboardButton("✅ Неоткатанные", callback_data='admin_logs_admin_filter_active'),
                InlineKeyboardButton("↩️ Откатанные", callback_data='admin_logs_admin_filter_rolled')
            ])

            # Pagination buttons
            nav_row = []
            if page > 0:
                nav_row.append(InlineKeyboardButton("◀️", callback_data='admin_logs_admin_prev'))
            nav_row.append(InlineKeyboardButton(f"{page+1}/{pages}", callback_data='admin_logs_admin_goto_menu'))
            if (page + 1) * 10 < total:
                nav_row.append(InlineKeyboardButton("▶️", callback_data='admin_logs_admin_next'))
            if len(nav_row) > 1:
                kb.append(nav_row)
            
            kb.append([InlineKeyboardButton("📄 Показать всё", callback_data='admin_logs_admin_show_all')])
            kb.append([InlineKeyboardButton("🔙 Назад", callback_data='admin_logs')])

        q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

    elif d == 'admin_logs_admin_goto_menu':
        # Меню перехода на конкретную страницу
        rolled_back = context.user_data.get('admin_logs_admin_filter', None)
        current_page = context.user_data.get('admin_logs_admin_page', 0)
        
        # Получаем общее количество
        logs, total = get_admin_logs(limit=1, offset=0, rolled_back=rolled_back)
        
        pages = (total + 9) // 10 or 1
        
        # Показываем все страницы в виде сетки (по 5 в ряд)
        kb = []
        row = []
        for i in range(pages):
            if i == current_page:
                row.append(InlineKeyboardButton(f"▶ {i+1}", callback_data='dummy'))
            else:
                row.append(InlineKeyboardButton(f"{i+1}", callback_data=f'admin_logs_admin_page_{i}'))
            if len(row) == 5:
                kb.append(row)
                row = []
        if row:
            kb.append(row)
        
        kb.append([InlineKeyboardButton("🔙 Назад", callback_data='admin_logs_admin')])
        
        q.edit_message_text(
            f"📄 Выбор страницы (всего {pages} страниц):",
            reply_markup=InlineKeyboardMarkup(kb)
        )

    elif d == 'admin_logs_admin_filter_all':
        context.user_data['admin_logs_admin_filter'] = None
        context.user_data['admin_logs_admin_page'] = 0
        d = 'admin_logs_admin'
        _btn_handler(q, uid, d, context)

    elif d == 'admin_logs_admin_filter_active':
        context.user_data['admin_logs_admin_filter'] = False
        context.user_data['admin_logs_admin_page'] = 0
        d = 'admin_logs_admin'
        _btn_handler(q, uid, d, context)

    elif d == 'admin_logs_admin_filter_rolled':
        context.user_data['admin_logs_admin_filter'] = True
        context.user_data['admin_logs_admin_page'] = 0
        d = 'admin_logs_admin'
        _btn_handler(q, uid, d, context)

    elif d == 'admin_logs_admin_prev':
        page = context.user_data.get('admin_logs_admin_page', 0)
        if page > 0:
            context.user_data['admin_logs_admin_page'] = page - 1
        else:
            context.user_data['admin_logs_admin_page'] = 0
        d = 'admin_logs_admin'
        _btn_handler(q, uid, d, context)

    elif d == 'admin_logs_admin_next':
        page = context.user_data.get('admin_logs_admin_page', 0)
        page_size = 10
        rolled_back = context.user_data.get('admin_logs_admin_filter', None)
        
        # Получаем общее количество для валидации
        logs, total = get_admin_logs(limit=page_size, offset=0, rolled_back=rolled_back)
        
        pages = (total + page_size - 1) // page_size if total > 0 else 1
        if page + 1 < pages:
            context.user_data['admin_logs_admin_page'] = page + 1
        d = 'admin_logs_admin'
        _btn_handler(q, uid, d, context)

    elif d.startswith('admin_logs_admin_page_'):
        page_num = int(d.replace('admin_logs_admin_page_', ''))
        page_size = 10
        rolled_back = context.user_data.get('admin_logs_admin_filter', None)
        
        # Валидация страницы
        logs, total = get_admin_logs(limit=page_size, offset=0, rolled_back=rolled_back)
        
        pages = (total + page_size - 1) // page_size if total > 0 else 1
        if page_num >= pages:
            page_num = pages - 1
        if page_num < 0:
            page_num = 0
            
        context.user_data['admin_logs_admin_page'] = page_num
        d = 'admin_logs_admin'
        _btn_handler(q, uid, d, context)

    elif d.startswith('admin_log_detail_game_'):
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return

        gid = int(d.replace('admin_log_detail_game_', ''))

        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute('SELECT * FROM game_history WHERE id=?', (gid,))
        game = c.fetchone()
        conn.close()

        if not game:
            q.answer("Игра не найдена", show_alert=True); return

        game_id, game_uid, gname, details, amount, is_win, is_rolled_back, created_at = game

        # Get username
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute('SELECT username FROM users WHERE id=?', (game_uid,))
        user_row = c.fetchone()
        username = user_row[0] if user_row else f"ID:{game_uid}"
        conn.close()

        # Используем правильный формат с is_rolled_back
        msg = format_game_detail(gname, details, amount, is_win, created_at, is_rolled_back)

        # Кнопка возврата с учетом текущего фильтра
        current_filter = context.user_data.get('admin_logs_users_filter', None)
        back_callback = 'admin_logs_users'
        
        # Добавляем кнопку отката или отмены отката
        if is_game_rolled_back(is_rolled_back):
            kb = [
                [InlineKeyboardButton("👤 Пользователь", callback_data=f'user_info_{game_uid}_admin_logs_users')],
                [InlineKeyboardButton("↩️ Отменить откат", callback_data=f'admin_log_rollback_game_{gid}')],
                [InlineKeyboardButton("🔙 Назад", callback_data=back_callback)]
            ]
        else:
            kb = [
                [InlineKeyboardButton("👤 Пользователь", callback_data=f'user_info_{game_uid}_admin_logs_users')],
                [InlineKeyboardButton("↩️ Откатить игру", callback_data=f'admin_log_rollback_game_{gid}')],
                [InlineKeyboardButton("🔙 Назад", callback_data=back_callback)]
            ]

        q.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb))

    elif d.startswith('admin_log_detail_admin_'):
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return

        log_id = int(d.replace('admin_log_detail_admin_', ''))

        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute('SELECT * FROM admin_logs WHERE id=?', (log_id,))
        log = c.fetchone()
        conn.close()

        if not log:
            q.answer("Лог не найден", show_alert=True); return

        l_id, admin_id, action, target_type, target_id, details, is_rolled_back, created_at = log

        # Get admin username if available
        conn2 = sqlite3.connect(DB_PATH)
        c = conn2.cursor()
        c.execute('SELECT username FROM users WHERE id=?', (admin_id,))
        admin_row = c.fetchone()
        admin_name = admin_row[0] if admin_row else f"ID:{admin_id}"

        # Get target username if it's a user
        target_name = None
        if target_type == 'user':
            c.execute('SELECT username FROM users WHERE id=?', (target_id,))
            target_row = c.fetchone()
            target_name = target_row[0] if target_row else None

        conn2.close()

        action_desc = get_action_description(action, target_type, target_id)

        text = (
            f"📜 Детали лога #{l_id}\n\n"
            f"📅 Дата: {created_at}\n"
            f"👤 Админ: {admin_name} (ID: {admin_id})\n"
            f"⚡ Действие: {action_desc}\n"
        )
        if target_name:
            text += f"🎯 Цель: {target_name} (ID: {target_id})\n"
        else:
            text += f"🆔 ID цели: {target_id}\n"
        if details:
            text += f"ℹ️ Детали: {details}\n"
        # Проверяем is_rolled_back: 1 = откатан, 0 или None = не откатан
        if is_game_rolled_back(is_rolled_back):
            text += f"\n↩️ Это действие было откачено"

        # Кнопка возврата с учетом текущего фильтра
        current_filter = context.user_data.get('admin_logs_admin_filter', None)
        back_callback = 'admin_logs_admin'
        
        # Собираем кнопки
        row1 = []
        
        # Кнопка просмотра пользователя, если это действие над пользователем
        if target_type == 'user' and target_id:
            row1.append(InlineKeyboardButton("👤 Пользователь", callback_data=f'user_info_{target_id}_admin_logs_admin'))
        
        # Кнопка отката или снятия отката
        if is_game_rolled_back(is_rolled_back):
            row1.append(InlineKeyboardButton("↩️ Снять откат", callback_data=f'admin_log_rollback_admin_{log_id}'))
        else:
            row1.append(InlineKeyboardButton("↩️ Откатить действие", callback_data=f'admin_log_rollback_admin_{log_id}'))
        
        kb = [row1, [InlineKeyboardButton("🔙 Назад", callback_data=back_callback)]]

        q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

    elif d.startswith('admin_log_rollback_game_'):
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return

        gid = int(d.replace('admin_log_rollback_game_', ''))

        success, msg = rollback_game(gid)

        if success:
            # НЕ логируем откат игры в админ-логах - это засоряет логи
            # Но обновляем сообщение
            q.answer(msg, show_alert=True)
        else:
            q.answer(msg, show_alert=True)
            return

        # Возвращаемся к списку логов (не к деталям)
        d = 'admin_logs_users'
        _btn_handler(q, uid, d, context)

    elif d.startswith('admin_log_rollback_admin_'):
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return

        log_id = int(d.replace('admin_log_rollback_admin_', ''))

        success, msg = rollback_admin_log(log_id, uid)

        if success:
            log_admin_action(uid, 'rollback_admin', 'log', log_id, msg)
            q.answer(msg, show_alert=True)
        else:
            q.answer(msg, show_alert=True)
            return

        # Возвращаемся к списку логов (не к деталям)
        d = 'admin_logs_admin'
        _btn_handler(q, uid, d, context)

    elif d == 'admin_global_balance':
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return
        q.edit_message_text(
            "💰 Глобальный баланс\n\nВыберите действие:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Добавить всем", callback_data='admin_global_add')],
                [InlineKeyboardButton("➖ Вычесть у всех", callback_data='admin_global_sub')],
                [InlineKeyboardButton("🔄 Установить всем", callback_data='admin_global_set')],
                [InlineKeyboardButton("🔙 Назад", callback_data='admin_menu')]
            ])
        )

    elif d == 'admin_global_add':
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return
        q.edit_message_text(
            "💰 Добавить монет всем\n\nВведите сумму:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='admin_global_balance')]]))
        context.user_data['state'] = 'admin_global_add'

    elif d == 'admin_global_sub':
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return
        q.edit_message_text(
            "💰 Вычесть монет у всех\n\nВведите сумму:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='admin_global_balance')]]))
        context.user_data['state'] = 'admin_global_sub'

    elif d == 'admin_global_set':
        if not is_admin(uid):
            q.answer("Нет доступа!", show_alert=True); return
        q.edit_message_text(
            "💰 Установить баланс всем\n\nВведите сумму:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='admin_global_balance')]]))
        context.user_data['state'] = 'admin_global_set'

    # ── ГЛАВНОЕ МЕНЮ ──
    elif d == 'main_menu':
        row = get_user(uid)
        
        # Проверяем, нужно ли показать окошко подписки на канал
        # Показываем с вероятностью 30%, если пользователь ещё не получил награду
        channel_reward_received = row[16] if len(row) > 16 else 0
        
        # Сохраняем текущее меню для возврата
        context.user_data['return_to_menu'] = 'main_menu'
        
        if not channel_reward_received and random.random() < 0.3:
            # Показываем окошко подписки
            q.edit_message_text(
                f"📢 Подпишитесь на наш канал!\n\n"
                f"🔔 @{CHANNEL_USERNAME}\n\n"
                f"🎁 Подписка = +200 монет!\n"
                f"⚠️ Если отпишитесь - монеты будут списаны!",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Проверить подписку", callback_data='channel_check_popup')],
                    [InlineKeyboardButton("⏭️ Пропустить", callback_data='channel_skip_popup')]
                ])
            )
            return

        # Build keyboard with admin button if user is admin
        kb = [
            [InlineKeyboardButton("🎮 Игры", callback_data='games_menu'),
             InlineKeyboardButton("👤 Профиль", callback_data='profile')],
            [InlineKeyboardButton("🏆 Топ игроков", callback_data='leaderboard'),
             InlineKeyboardButton("🎁 Бонус", callback_data='hourly_bonus')],
            [InlineKeyboardButton("🎡 Колесо фортуны", callback_data='wheel_menu')],
            [InlineKeyboardButton("🎫 Промокод", callback_data='promo_enter'),
             InlineKeyboardButton("👥 Реферал", callback_data='referral')]
        ]
        # Add admin button at the bottom for admins
        if is_admin(uid):
            kb.append([InlineKeyboardButton("🔧 Админ-панель", callback_data='admin_menu')])

        q.edit_message_text(
            f"🏠 Главное меню\n💰 Баланс: {row[2]} монет",
            reply_markup=InlineKeyboardMarkup(kb)
        )

    elif d == 'channel_check_popup':
        # Используем синхронную проверку для python-telegram-bot 13.x
        try:
            is_subscribed = check_channel_subscription_sync(q.bot, uid)
            update_channel_subscription_status(uid, is_subscribed)

            if is_subscribed:
                if not get_channel_reward_status(uid):
                    add_coins(uid, 200)
                    set_channel_reward_received(uid)
                    row = get_user(uid)
                    
                    q.edit_message_text(
                        f"✅ Вы подписаны на канал!\n\n"
                        f"🎁 +200 монет добавлено на баланс!\n"
                        f"💰 Ваш баланс: {row[2]} монет\n\n"
                        f"⚠️ Если вы отпишетесь, 200 монет будут списаны!",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔙 Продолжить", callback_data='main_menu')]
                        ])
                    )
                else:
                    q.edit_message_text(
                        f"✅ Вы подписаны на канал!\n\n"
                        f"Вы уже получали награду за подписку.",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔙 Продолжить", callback_data='main_menu')]
                        ])
                    )
            else:
                q.edit_message_text(
                    f"❌ Вы не подписаны на канал!\n\n"
                    f"📢 Пожалуйста, подпишитесь на канал: @{CHANNEL_USERNAME}\n"
                    f"Затем нажмите \"Проверить\" снова.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("✅ Проверить", callback_data='channel_check_popup')],
                        [InlineKeyboardButton("⏭️ Пропустить", callback_data='channel_skip_popup')]
                    ])
                )
        except Exception as e:
            print(f"Error in channel_check_popup: {e}")
            q.edit_message_text(
                f"⚠️ Ошибка проверки подписки.\n\n"
                f"Попробуйте позже или обратитесь к администратору.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Главное меню", callback_data='main_menu')]
                ])
            )

    elif d == 'channel_skip_popup':
        # Возвращаемся в главное меню
        row = get_user(uid)
        kb = [
            [InlineKeyboardButton("🎮 Игры", callback_data='games_menu'),
             InlineKeyboardButton("👤 Профиль", callback_data='profile')],
            [InlineKeyboardButton("🏆 Топ игроков", callback_data='leaderboard'),
             InlineKeyboardButton("🎁 Бонус", callback_data='hourly_bonus')],
            [InlineKeyboardButton("🎡 Колесо фортуны", callback_data='wheel_menu')],
            [InlineKeyboardButton("🎫 Промокод", callback_data='promo_enter'),
             InlineKeyboardButton("👥 Реферал", callback_data='referral')]
        ]
        if is_admin(uid):
            kb.append([InlineKeyboardButton("🔧 Админ-панель", callback_data='admin_menu')])
        
        q.edit_message_text(
            f"🏠 Главное меню\n💰 Баланс: {row[2]} монет",
            reply_markup=InlineKeyboardMarkup(kb)
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

    elif d == 'history' or d.startswith('history_page_') or d.startswith('history_sort_') or d.startswith('history_game_') or d.startswith('history_win_') or d == 'history_all' or d == 'history_paged' or (d.startswith('history_goto_') and d != 'history_goto_menu'):
        # Обработка истории игр с расширенной сортировкой
        page = 0
        
        # Парсим параметры из callback_data
        if d.startswith('history_page_'):
            parts = d.replace('history_page_', '').split('_')
            page = int(parts[0]) if parts else 0
        elif d.startswith('history_goto_') and d != 'history_goto_menu':
            # Переход на конкретную страницу
            page = int(d.replace('history_goto_', ''))
        
        # Получаем параметры сортировки из context.user_data
        sort_games = context.user_data.get('history_sort_games', [])  # Список выбранных игр
        sort_win = context.user_data.get('history_sort_win', None)  # None = все, True = выигрыши, False = проигрыши
        show_all = context.user_data.get('history_show_all', False)  # Показать всё без страниц
        
        # Обрабатываем изменение сортировки
        if d.startswith('history_sort_'):
            sort_type = d.replace('history_sort_', '')
            if sort_type == 'newest':
                context.user_data['history_sort_games'] = []
                context.user_data['history_sort_win'] = None
            elif sort_type == 'wins':
                context.user_data['history_sort_win'] = True
            elif sort_type == 'losses':
                context.user_data['history_sort_win'] = False
            elif sort_type == 'all':
                context.user_data['history_sort_win'] = None
            page = 0
            sort_games = context.user_data.get('history_sort_games', [])
            sort_win = context.user_data.get('history_sort_win', None)

        elif d == 'history_all':
            context.user_data['history_show_all'] = True
            show_all = True
        elif d == 'history_paged':
            context.user_data['history_show_all'] = False
            show_all = False
            page = 0
        
        # Получаем историю с фильтрами
        # Если выбрано несколько игр, фильтруем по первой (или можно изменить функцию для поддержки списка)
        # Для простоты: если выбрана одна игра - фильтруем по ней, если несколько - показываем все выбранные
        page_size = -1 if show_all else 5  # -1 = все
        
        # Получаем все игры и фильтруем на стороне Python если нужно
        if len(sort_games) == 1:
            # Одна игра - используем оптимизированный запрос
            rows, total = get_history_paged(uid, page, page_size=page_size, rolled_back=False, game_name=sort_games[0], is_win=sort_win)
        elif len(sort_games) > 1:
            # Несколько игр - получаем все и фильтруем
            all_rows, total = get_history_paged(uid, 0, page_size=-1, rolled_back=False, game_name=None, is_win=sort_win)
            # Фильтруем по выбранным играм
            filtered_rows = [r for r in all_rows if r[1] in sort_games]
            total = len(filtered_rows)
            # Пагинация
            if page_size > 0:
                start = page * page_size
                rows = filtered_rows[start:start + page_size]
            else:
                rows = filtered_rows
        else:
            # Нет выбранных игр - показываем все
            rows, total = get_history_paged(uid, page, page_size=page_size, rolled_back=False, game_name=None, is_win=sort_win)
        
        # Валидация страницы (только для постраничного режима)
        if not show_all:
            pages = (total + 4) // 5 or 1
            if page >= pages:
                page = max(0, pages - 1)
            if page < 0:
                page = 0
            # Повторный запрос с валидной страницей
            if page != 0 and rows == [] and total > 0:
                if len(sort_games) == 1:
                    rows, total = get_history_paged(uid, page, page_size=5, rolled_back=False, game_name=sort_games[0], is_win=sort_win)
                elif len(sort_games) > 1:
                    all_rows, total = get_history_paged(uid, 0, page_size=-1, rolled_back=False, game_name=None, is_win=sort_win)
                    filtered_rows = [r for r in all_rows if r[1] in sort_games]
                    total = len(filtered_rows)
                    start = page * 5
                    rows = filtered_rows[start:start + 5]
                else:
                    rows, total = get_history_paged(uid, page, page_size=5, rolled_back=False, game_name=None, is_win=sort_win)
        else:
            pages = 1
        
        # Формируем текст фильтров
        filter_text = []
        if sort_games:
            if len(sort_games) == 1:
                filter_text.append(f"🎮 {sort_games[0]}")
            else:
                filter_text.append(f"🎮 {len(sort_games)} игр")
        if sort_win is True:
            filter_text.append("✅ Выигрыши")
        elif sort_win is False:
            filter_text.append("❌ Проигрыши")
        
        filter_str = " | ".join(filter_text) if filter_text else "Все"
        
        if not rows:
            text = f"📜 История игр пуста\n\nФильтр: {filter_str}"
            kb = [
                [InlineKeyboardButton("📊 Сортировка", callback_data='history_menu')],
                [InlineKeyboardButton("🔙 К профилю", callback_data='profile')]
            ]
        else:
            if show_all:
                text = f"📜 История игр (всё)\nФильтр: {filter_str}\nВсего: {total}\n\n"
                for gid, gname, amount, is_win, is_rolled_back, created_at in rows:
                    g_emoji = GAME_EMOJIS.get(gname, '🎮')
                    res_emoji = "✅" if is_win else "❌"
                    sign = "+" if is_win else "-"
                    date_str = created_at[:10] if created_at else "?"
                    text += f"{res_emoji} {g_emoji} {gname}: {sign}{amount} 💰 ({date_str})\n"
                kb = [
                    [InlineKeyboardButton("📄 Постраничный вид", callback_data='history_paged')],
                    [InlineKeyboardButton("📊 Сортировка", callback_data='history_menu')],
                    [InlineKeyboardButton("🔙 К профилю", callback_data='profile')]
                ]
            else:
                text = f"📜 История игр\nФильтр: {filter_str}\n━━━━━━━━━━━━━━━━\nСтраница {page+1} из {pages} | Всего: {total}\n\nНажмите на игру для деталей:"
                kb = []
                for gid, gname, amount, is_win, is_rolled_back, created_at in rows:
                    g_emoji = GAME_EMOJIS.get(gname, '🎮')
                    res_emoji = "✅" if is_win else "❌"
                    sign = "+" if is_win else "-"
                    kb.append([InlineKeyboardButton(
                        f"{res_emoji} {g_emoji} {gname}: {sign}{amount} 💰",
                        callback_data=f'gameview_{gid}_{page}'
                    )])
                
                # Навигация
                nav = []
                if page > 0:
                    nav.append(InlineKeyboardButton("◀️", callback_data=f'history_page_{page-1}'))
                nav.append(InlineKeyboardButton(f"{page+1}/{pages}", callback_data='history_goto_menu'))
                if (page + 1) * 5 < total:
                    nav.append(InlineKeyboardButton("▶️", callback_data=f'history_page_{page+1}'))
                if len(nav) > 1:
                    kb.append(nav)
                
                kb.append([InlineKeyboardButton("📄 Показать всё", callback_data='history_all')])
                kb.append([InlineKeyboardButton("📊 Сортировка", callback_data='history_menu')])
                kb.append([InlineKeyboardButton("🔙 К профилю", callback_data='profile')])

        q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

    elif d == 'history_menu':
        # Меню сортировки истории
        sort_games = context.user_data.get('history_sort_games', [])  # Список выбранных игр
        sort_win = context.user_data.get('history_sort_win', None)  # None = все, True = выигрыши, False = проигрыши
        
        # Формируем кнопки фильтра по играм (чекбоксы) - используем предопределённый список
        game_buttons = []
        for game in ALL_GAMES:
            emoji = GAME_EMOJIS.get(game, '🎮')
            is_selected = game in sort_games
            check = "☑️ " if is_selected else "⬜ "
            game_buttons.append([InlineKeyboardButton(
                f"{check}{emoji} {game}",
                callback_data=f'history_game_toggle_{game}'
            )])
        
        # Кнопка "Все игры" / "Снять все"
        if len(sort_games) == 0:
            all_btn = [InlineKeyboardButton("☑️ Выбрать все", callback_data='history_game_select_all')]
        else:
            all_btn = [InlineKeyboardButton("⬜ Снять выбор", callback_data='history_game_clear')]
        
        # Кнопки фильтра по выигрышу/проигрышу
        win_buttons = [
            InlineKeyboardButton(f"{'✅ ' if sort_win is None else ''}📊 Все", callback_data='history_win_all'),
            InlineKeyboardButton(f"{'✅ ' if sort_win is True else ''}✅ Выигрыши", callback_data='history_win_wins'),
            InlineKeyboardButton(f"{'✅ ' if sort_win is False else ''}❌ Проигрыши", callback_data='history_win_losses')
        ]
        
        # Текст выбранных фильтров
        selected_text = ""
        if sort_games:
            selected_text += f"🎮 Игры: {', '.join(sort_games)}\n"
        if sort_win is True:
            selected_text += "✅ Только выигрыши\n"
        elif sort_win is False:
            selected_text += "❌ Только проигрыши\n"
        
        if not selected_text:
            selected_text = "Фильтры не выбраны (показать всё)"
        
        q.edit_message_text(
            f"📊 Сортировка истории игр\n\nВыбранные фильтры:\n{selected_text}",
            reply_markup=InlineKeyboardMarkup([
                *game_buttons,
                all_btn,
                win_buttons,
                [InlineKeyboardButton("🔄 Сбросить все фильтры", callback_data='history_sort_reset')],
                [InlineKeyboardButton("✅ Применить и закрыть", callback_data='history')]
            ])
        )

    elif d.startswith('history_game_toggle_'):
        # Переключение выбора игры
        game_name = d.replace('history_game_toggle_', '')
        sort_games = context.user_data.get('history_sort_games', [])
        
        if game_name in sort_games:
            sort_games.remove(game_name)
        else:
            sort_games.append(game_name)
        
        context.user_data['history_sort_games'] = sort_games
        # Остаемся в меню
        d = 'history_menu'
        _btn_handler(q, uid, d, context)

    elif d == 'history_game_select_all':
        # Выбрать все игры
        context.user_data['history_sort_games'] = ALL_GAMES.copy()
        d = 'history_menu'
        _btn_handler(q, uid, d, context)

    elif d == 'history_game_clear':
        # Снять выбор со всех игр
        context.user_data['history_sort_games'] = []
        d = 'history_menu'
        _btn_handler(q, uid, d, context)

    elif d.startswith('history_win_'):
        # Фильтр по выигрышу/проигрышу - остаемся в меню
        win_filter = d.replace('history_win_', '')
        if win_filter == 'all':
            context.user_data['history_sort_win'] = None
        elif win_filter == 'wins':
            context.user_data['history_sort_win'] = True
        elif win_filter == 'losses':
            context.user_data['history_sort_win'] = False
        d = 'history_menu'
        _btn_handler(q, uid, d, context)

    elif d == 'history_sort_reset':
        # Сброс всех фильтров
        context.user_data['history_sort_games'] = []
        context.user_data['history_sort_win'] = None
        d = 'history_menu'
        _btn_handler(q, uid, d, context)

    elif d == 'history_goto_menu':
        # Меню перехода на конкретную страницу
        sort_games = context.user_data.get('history_sort_games', [])
        sort_win = context.user_data.get('history_sort_win', None)
        
        # Получаем общее количество
        if len(sort_games) == 1:
            _, total = get_history_paged(uid, 0, page_size=5, rolled_back=False, game_name=sort_games[0], is_win=sort_win)
        elif len(sort_games) > 1:
            all_rows, _ = get_history_paged(uid, 0, page_size=-1, rolled_back=False, game_name=None, is_win=sort_win)
            filtered_rows = [r for r in all_rows if r[1] in sort_games]
            total = len(filtered_rows)
        else:
            _, total = get_history_paged(uid, 0, page_size=5, rolled_back=False, game_name=None, is_win=sort_win)
        pages = (total + 4) // 5 or 1
        
        if pages <= 7:
            # Если страниц мало, показываем все
            kb = [[InlineKeyboardButton(f"Стр. {i+1}", callback_data=f'history_goto_{i}') for i in range(pages)]]
        else:
            # Показываем первые 3, ... , последние 3
            kb = [
                [InlineKeyboardButton(f"{i+1}", callback_data=f'history_goto_{i}') for i in range(3)],
                [InlineKeyboardButton("...", callback_data='dummy')],
                [InlineKeyboardButton(f"{i+1}", callback_data=f'history_goto_{i}') for i in range(pages-3, pages)]
            ]
        
        kb.append([InlineKeyboardButton("🔙 Назад", callback_data='history')])
        
        q.edit_message_text(
            f"📄 Выбор страницы (всего {pages} страниц):",
            reply_markup=InlineKeyboardMarkup(kb)
        )

    elif d.startswith('gameview_'):
        parts = d.split('_')
        gid = int(parts[1])
        back_page = int(parts[2])
        g = get_game_info(gid)
        if not g:
            q.answer("Игра не найдена", show_alert=True); return
        gname, details, amount, is_win, is_rolled_back, created_at = g
        msg = format_game_detail(gname, details, amount, is_win, created_at, is_rolled_back)
        q.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Назад к списку", callback_data=f'history_page_{back_page}')]
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
    # ── ЯПОНСКИЕ СВЕЧИ ──
    # ════════════════════════════
    elif d == 'candles_menu':
        bet = context.user_data.get('candles_bet', 0)
        row = get_user(uid)
        can_start = bet > 0
        q.edit_message_text(
            f"📊 Японские свечи\n💰 Баланс: {row[2]} монет\nСтавка: {bet} монет\n\n"
            f"Угадайте направление следующей свечи: 📈 Вверх или 📉 Вниз!\n"
            f"Правильный прогноз = x1.9",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("▶️ Начать игру", callback_data='candles_start') if can_start
                 else InlineKeyboardButton("▶️ Начать (сделайте ставку)", callback_data='candles_need_bet')],
                [InlineKeyboardButton(f"💰 Сделать ставку ({bet} монет)", callback_data='candles_set_bet')],
                [InlineKeyboardButton("🔙 Назад", callback_data='games_menu')]
            ])
        )

    elif d == 'candles_need_bet':
        q.answer("Сначала сделайте ставку!", show_alert=True)

    elif d == 'candles_set_bet':
        q.edit_message_text(
            "💰 Введите сумму ставки для Свечей:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='candles_menu')]]))
        context.user_data['state'] = 'candles_bet'

    elif d == 'candles_start':
        bet = context.user_data.get('candles_bet', 0)
        row = get_user(uid)
        if bet <= 0:
            q.answer("Сначала сделайте ставку!", show_alert=True); return
        if bet > row[2]:
            # Если баланса недостаточно, предложим изменить ставку
            q.answer(f"Недостаточно монет! У вас {row[2]}, а ставка {bet}. Измените ставку.", show_alert=True)
            return
        add_coins(uid, -bet)

        # Initialize infinite mode
        context.user_data['candles_active'] = True
        context.user_data['candles_coeff'] = 1.0
        context.user_data['candles_moves'] = []  # track successful predictions
        context.user_data['candles_base_price'] = 100
        context.user_data['candles'] = []

        # Generate initial 5 candles for display
        candles = []
        base_price = 100
        for i in range(5):
            # Генерируем изменение, исключая 0
            while True:
                change = random.randint(-15, 15)
                if change != 0:
                    break
            candles.append(change)

        context.user_data['candles'] = candles

        # Generate next candle direction
        actual_direction = random.choice(['up', 'down'])
        if actual_direction == 'up':
            change = random.randint(1, 16)
        else:
            change = random.randint(-15, -1)
        context.user_data['candles_actual'] = actual_direction
        context.user_data['candles_next_change'] = change

        # Build chart display
        chart_lines = []
        current_price = base_price
        for i, change in enumerate(candles):
            prev_price = current_price
            current_price += change
            emoji = "📈" if change > 0 else "📉" if change < 0 else "➡️"
            chart_lines.append(f"{emoji} Свеча {i+1}: {prev_price} → {current_price} ({change:+d})")

        chart_text = "\n".join(chart_lines)

        q.edit_message_text(
            f"📊 Японские свечи | Ставка: {bet} монет\n\n"
            f"График последних 5 свечей:\n{chart_text}\n\n"
            f"Куда пойдёт следующая свеча?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📈 Вверх", callback_data='candles_up'),
                 InlineKeyboardButton("📉 Вниз", callback_data='candles_down')]
            ])
        )

    elif d in ('candles_up', 'candles_down'):
        if not context.user_data.get('candles_active', False):
            q.answer("Игра не активна! Начните новую игру.", show_alert=True); return

        bet = context.user_data.get('candles_bet', 0)
        coeff = context.user_data.get('candles_coeff', 1.0)
        candles = context.user_data.get('candles', [])
        actual = context.user_data.get('candles_actual', '')
        next_change = context.user_data.get('candles_next_change', 0)
        base_price = context.user_data.get('candles_base_price', 100)

        prediction = 'up' if d == 'candles_up' else 'down'
        won = (prediction == actual)

        # Add the result candle to chart
        candles.append(next_change)

        if won:
            # Correct prediction - increase coefficient and continue
            new_coeff = coeff * 1.9
            context.user_data['candles_coeff'] = new_coeff
            context.user_data.setdefault('candles_moves', []).append(f"✅{'📈' if actual == 'up' else '📉'}")
            potential = int(bet * new_coeff)

            # Generate next candle direction
            next_actual_direction = random.choice(['up', 'down'])
            if next_actual_direction == 'up':
                next_change = random.randint(1, 16)
            else:
                next_change = random.randint(-15, -1)
            context.user_data['candles_actual'] = next_actual_direction
            context.user_data['candles_next_change'] = next_change

            # Build chart display (show last 5 candles + 1 more for context)
            chart_lines = []
            current_price = base_price
            display_candles = candles[-6:] if len(candles) > 6 else candles
            for i, change in enumerate(display_candles):
                prev_price = current_price
                current_price += change
                emoji = "📈" if change > 0 else "📉" if change < 0 else "➡️"
                candle_num = len(candles) - len(display_candles) + i + 1
                chart_lines.append(f"{emoji} Свеча {candle_num}: {prev_price} → {current_price} ({change:+d})")

            chart_text = "\n".join(chart_lines)

            q.edit_message_text(
                f"🎉 Правильно! Свеча пошла {'📈 Вверх' if actual == 'up' else '📉 Вниз'}!\n\n"
                f"График:\n{chart_text}\n\n"
                f"🔥 Коэффициент: {new_coeff:.1f}x\n"
                f"💰 Возможный выигрыш: {potential} монет\n\n"
                f"Продолжить или забрать?",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📈 Вверх", callback_data='candles_up'),
                     InlineKeyboardButton("📉 Вниз", callback_data='candles_down')],
                    [InlineKeyboardButton(f"💳 Забрать {potential} монет", callback_data='candles_cashout')]
                ])
            )
        else:
            # Wrong prediction - game over
            context.user_data['candles_active'] = False
            context.user_data['candles_coeff'] = 1.0
            moves = context.user_data.get('candles_moves', [])
            moves.append(f"❌{'📈' if actual == 'up' else '📉'}")

            log_game(uid, "Свечи", json.dumps({'bet': bet, 'moves': moves, 'coeff': round(coeff, 1), 'result': 'loss'}), bet, False)

            # Build full chart with result
            chart_lines = []
            current_price = base_price
            display_candles = candles[-6:] if len(candles) > 6 else candles
            for i, change in enumerate(display_candles):
                prev_price = current_price
                current_price += change
                emoji = "📈" if change > 0 else "📉" if change < 0 else "➡️"
                candle_num = len(candles) - len(display_candles) + i + 1
                chart_lines.append(f"{emoji} Свеча {candle_num}: {prev_price} → {current_price} ({change:+d})")

            chart_text = "\n".join(chart_lines)

            row = get_user(uid)
            q.edit_message_text(
                f"😞 Не угадали! Свеча пошла {'📈 Вверх' if actual == 'up' else '📉 Вниз'}!\n\n"
                f"График:\n{chart_text}\n\n"
                f"💸 Потеряли {bet} монет\n"
                f"💰 Баланс: {row[2]} монет",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Играть снова", callback_data='candles_menu')],
                    [InlineKeyboardButton("🔙 Главное меню", callback_data='main_menu')]
                ])
            )

    elif d == 'candles_cashout':
        if not context.user_data.get('candles_active', False):
            q.answer("Нет активной игры!", show_alert=True); return

        bet = context.user_data.get('candles_bet', 0)
        coeff = context.user_data.get('candles_coeff', 1.0)
        winnings = int(bet * coeff)
        add_coins(uid, winnings)

        moves = context.user_data.get('candles_moves', [])
        log_game(uid, "Свечи", json.dumps({'bet': bet, 'moves': moves, 'coeff': round(coeff, 1), 'result': 'cashout'}), winnings, True)

        context.user_data['candles_active'] = False
        context.user_data['candles_coeff'] = 1.0
        context.user_data['candles_moves'] = []

        row = get_user(uid)
        profit = winnings - bet

        q.edit_message_text(
            f"✅ Выигрыш забран!\n💰 +{winnings} монет (x{coeff:.1f}) | Прибыль: +{profit}\n💰 Баланс: {row[2]} монет",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Играть снова", callback_data='candles_menu')],
                [InlineKeyboardButton("🔙 Главное меню", callback_data='main_menu')]
            ])
        )

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
        traps = context.user_data.get('tower_traps_count', 1)  # 1 или 2 бомбы
        row = get_user(uid)
        
        # Выбираем коэффициенты в зависимости от режима
        coeffs = TOWER_COEFFS_2BOMBS if traps == 2 else TOWER_COEFFS_1BOMB
        coeffs_txt = " → ".join([f"{c:.1f}x" for c in coeffs[:6]]) + " → ..."
        
        traps_text = f"{traps} бомб{'а' if traps == 1 else 'ы'}"
        mode_text = "🔥 Хардкор" if traps == 2 else "🎯 Стандарт"
        
        q.edit_message_text(
            f"🗼 Башня\n💰 Баланс: {row[2]} монет\nСтавка: {bet} монет | {traps_text}/этаж\n\n"
            f"Режим: {mode_text}\n"
            f"{TOWER_FLOORS} этажей. На каждом 3 ячейки — {traps_text}.\n"
            f"Коэффициенты: {coeffs_txt}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("▶️ Начать", callback_data='tower_start') if bet > 0
                 else InlineKeyboardButton("▶️ Начать (сделайте ставку)", callback_data='tower_need_bet')],
                [InlineKeyboardButton(f"💰 Ставка ({bet})", callback_data='tower_set_bet')],
                [InlineKeyboardButton(f"💣 Мины: {traps}", callback_data='tower_set_traps')],
                [InlineKeyboardButton("🔙 Назад", callback_data='games_menu')]
            ])
        )

    elif d == 'tower_need_bet':
        q.answer("Сначала сделайте ставку!", show_alert=True)

    elif d == 'tower_set_bet':
        q.edit_message_text("💰 Введите сумму ставки для Башни:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='tower_menu')]]))
        context.user_data['state'] = 'tower_bet'

    elif d == 'tower_set_traps':
        traps = context.user_data.get('tower_traps_count', 1)
        q.edit_message_text(
            f"💣 Выберите количество мин на этаж:\n\n"
            f"1 бомба — Стандартный режим (шанс пройти этаж: 66.7%)\n"
            f"2 бомбы — Хардкорный режим (шанс пройти этаж: 33.3%)\n\n"
            f"⚠️ Чем больше бомб, тем выше коэффициенты!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"{'✅ ' if traps == 1 else ''}1 бомба (стандарт)", callback_data='tower_traps_1')],
                [InlineKeyboardButton(f"{'✅ ' if traps == 2 else ''}2 бомбы (хардкор)", callback_data='tower_traps_2')],
                [InlineKeyboardButton("🔙 Назад", callback_data='tower_menu')]
            ])
        )

    elif d.startswith('tower_traps_'):
        traps = int(d.replace('tower_traps_', ''))
        context.user_data['tower_traps_count'] = traps
        # Возвращаемся в меню
        d = 'tower_menu'
        _btn_handler(q, uid, d, context)

    elif d == 'tower_start':
        bet = context.user_data.get('tower_bet', 0)
        traps_count = context.user_data.get('tower_traps_count', 1)
        row = get_user(uid)
        if bet <= 0:
            q.answer("Сначала сделайте ставку!", show_alert=True); return
        if bet > row[2]:
            q.answer("Недостаточно монет!", show_alert=True); return
        add_coins(uid, -bet)
        # Generate trap positions for each floor
        # Для 1 бомбы: 1 позиция, для 2 бомб: 2 позиции
        traps = []
        for _ in range(TOWER_FLOORS):
            if traps_count == 1:
                traps.append([random.randint(0, 2)])
            else:
                # 2 бомбы: выбираем 2 разных позиции из 3
                positions = random.sample(range(3), 2)
                traps.append(positions)
        
        context.user_data['tower_traps'] = traps
        context.user_data['tower_floor'] = 0
        context.user_data['tower_active'] = True
        context.user_data['tower_traps_count'] = traps_count
        row2 = get_user(uid)
        
        # Выбираем коэффициенты
        coeffs = TOWER_COEFFS_2BOMBS if traps_count == 2 else TOWER_COEFFS_1BOMB
        coeff = coeffs[0]
        
        q.edit_message_text(
            f"🗼 Башня | Ставка: {bet} | {traps_count} бомб{'ы' if traps_count == 2 else 'а'}\n"
            f"💰 Баланс: {row2[2]}\n"
            f"Этаж 1/{TOWER_FLOORS} | Коэффициент: {coeff:.1f}x\n"
            f"Возможный выигрыш: {int(bet*coeff)} монет",
            reply_markup=tower_keyboard(0, traps_count)
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
        traps_count = context.user_data.get('tower_traps_count', 1)
        
        # Получаем позиции бомб на текущем этаже
        floor_traps = traps[floor] if floor < len(traps) else []
        
        # Проверяем, попал ли игрок на бомбу
        is_boom = cell in floor_traps

        if is_boom:
            # Boom!
            context.user_data['tower_active'] = False
            log_game(uid, "Башня", json.dumps({'bet': bet, 'traps': traps, 'floor_reached': floor, 'traps_count': traps_count, 'result': 'boom'}), bet, False)
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
            
            # Выбираем коэффициенты
            coeffs = TOWER_COEFFS_2BOMBS if traps_count == 2 else TOWER_COEFFS_1BOMB
            coeff = coeffs[floor]  # coeff for PASSING this floor
            winnings = int(bet * coeff)

            if next_floor >= TOWER_FLOORS:
                # Top of tower!
                add_coins(uid, winnings)
                context.user_data['tower_active'] = False
                log_game(uid, "Башня", json.dumps({'bet': bet, 'traps': traps, 'floor_reached': TOWER_FLOORS, 'traps_count': traps_count, 'coeff': coeff, 'result': 'top'}), winnings, True)
                row = get_user(uid)
                q.edit_message_text(
                    f"🏆 Вы добрались до вершины!\n💰 +{winnings} монет (x{coeff:.1f})\n💰 Баланс: {row[2]} монет",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 Играть снова", callback_data='tower_menu')],
                        [InlineKeyboardButton("🔙 Главное меню", callback_data='main_menu')]
                    ])
                )
            else:
                next_coeff = coeffs[next_floor]
                row = get_user(uid)
                q.edit_message_text(
                    f"🗼 Башня | Этаж {next_floor+1}/{TOWER_FLOORS} | {traps_count} бомб{'ы' if traps_count == 2 else 'а'}\n"
                    f"Текущий выигрыш: {winnings} монет (x{coeff:.1f})\n"
                    f"Следующий: {int(bet*next_coeff)} монет (x{next_coeff:.1f})\n"
                    f"💰 Баланс: {row[2]} монет",
                    reply_markup=tower_keyboard(next_floor, traps_count)
                )

    elif d == 'tower_cashout':
        if not context.user_data.get('tower_active', False):
            q.answer("Нет активной игры!", show_alert=True); return
        floor = context.user_data.get('tower_floor', 0)
        bet = context.user_data.get('tower_bet', 0)
        traps_count = context.user_data.get('tower_traps_count', 1)
        if floor == 0:
            q.answer("Сначала пройдите хотя бы один этаж!", show_alert=True); return
        
        # Выбираем коэффициенты
        coeffs = TOWER_COEFFS_2BOMBS if traps_count == 2 else TOWER_COEFFS_1BOMB
        coeff = coeffs[floor - 1]
        
        winnings = int(bet * coeff)
        add_coins(uid, winnings)
        context.user_data['tower_active'] = False
        log_game(uid, "Башня", json.dumps({'bet': bet, 'traps': context.user_data.get('tower_traps', []), 'floor_reached': floor, 'traps_count': traps_count, 'coeff': coeff, 'result': 'cashout'}), winnings, True)
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
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Обновить", callback_data='leaderboard')],
                [InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]
            ]))

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

    # ════════════════════════════
    # ── ПОДТВЕРЖДЕНИЕ ЧЕЛОВЕКА (БОТ ЗАЩИТА) ──
    # ════════════════════════════
    elif d == 'confirm_human_yes':
        if 'pending_referrer' in context.user_data:
            referrer_id = context.user_data['pending_referrer']
            uid = q.from_user.id

            # Set referrer in database
            set_field(uid, 'referrer_id', referrer_id)

            # Add coins to referrer
            add_coins(referrer_id, 200)

            # Update total refs count for referrer
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute('UPDATE users SET total_refs=total_refs+1 WHERE id=?', (referrer_id,))
            conn.commit()
            conn.close()

            # Get referrer info for message
            referrer_row = get_user(referrer_id)
            referrer_name = referrer_row[1] if referrer_row[1] else f"ID:{referrer_id}"

            # Notify referrer
            try:
                q.bot.send_message(referrer_id, f"👥 Вы привели нового реферала!\n+200 монет на баланс! 🎉")
            except Exception:
                pass

            # Show welcome message to new user
            row = get_user(uid)
            uname = referrer_row[1] if referrer_row[1] else f"ID:{uid}"
            q.edit_message_text(
                f"🎉 Спасибо за подтверждение!\n👥 Вы были приглашены: {referrer_name}\n💰 Баланс: {row[2]} монет\n\nВыберите действие:",
                reply_markup=main_menu_kb(uid)
            )

            # Clear pending referrer
            if 'pending_referrer' in context.user_data:
                del context.user_data['pending_referrer']

    elif d == 'confirm_human_no':
        if 'pending_referrer' in context.user_data:
            del context.user_data['pending_referrer']
        q.edit_message_text(
            "❌ Регистрация по реферальной ссылке отменена.\nНапишите /start для начала.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Начать заново", callback_data='start_cancelled')]])
        )

    elif d == 'start_cancelled':
        q.edit_message_text(
            "Напишите /start для начала.",
            reply_markup=None
        )

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

def handle_photo(update: Update, context: CallbackContext):
    """Handle photo messages for admin broadcasts"""
    uid = update.effective_user.id
    state = context.user_data.get('state', '')

    if state == 'admin_broadcast_photo' and is_admin(uid):
        # Get largest photo
        photo = update.message.photo[-1]
        file_id = photo.file_id
        caption = update.message.caption or ""

        # Create broadcast record
        broadcast_id = create_broadcast('photo', caption, file_id, None, uid)
        log_admin_action(uid, 'create_broadcast_photo', 'all', 0, f'ID: {broadcast_id}')

        # Send to all users
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute('SELECT id FROM users')
        users = c.fetchall()
        conn.close()

        sent_count = 0
        failed_count = 0

        for (user_id,) in users:
            try:
                update.message.bot.send_photo(user_id, file_id, caption=caption)
                sent_count += 1
            except Exception:
                failed_count += 1

        mark_broadcast_sent(broadcast_id)

        update.message.reply_text(
            f"✅ Рассылка с фото завершена!\n"
            f"📊 Отправлено: {sent_count}\n"
            f"❌ Ошибок: {failed_count}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='admin_broadcasts')]])
        )

        context.user_data['state'] = ''

def handle_text(update: Update, context: CallbackContext):
    uid = update.effective_user.id
    text = update.message.text.strip()
    state = context.user_data.get('state', '')

    # Check if user is blocked (except for admin states)
    if not state.startswith('admin_') and not is_admin(uid):
        row = get_user(uid)
        is_blocked = row[14] if len(row) > 14 else 0
        if is_blocked:
            update.message.reply_text(
                "🚫 Вы заблокированы!\n\nОбратитесь к администратору."
            )
            return

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
        c.execute('SELECT reward, max_uses, uses, max_per_user, deleted FROM promocodes WHERE code=?', (text,))
        promo = c.fetchone()
        if promo and not promo[4]:  # promo exists and not deleted
            reward, max_uses, uses, max_per_user, _ = promo

            # Check if user already used this promocode
            user_uses = check_promocode_usage_count(uid, text)
            if user_uses >= max_per_user:
                conn.close()
                update.message.reply_text(f"❌ Вы уже активировали этот промокод {user_uses} раз(а). Максимум: {max_per_user}", reply_markup=back_kb)
                return

            # Check global uses
            if max_uses is not None and uses >= max_uses:
                conn.close()
                update.message.reply_text("❌ Промокод уже исчерпан.", reply_markup=back_kb)
                return

            # Activate promocode
            add_coins(uid, reward)
            c.execute('UPDATE promocodes SET uses=uses+1 WHERE code=?', (text,))
            c.execute('INSERT INTO promo_usage (code, uid) VALUES (?, ?)', (text, uid))
            conn.commit()
            row = get_user(uid)
            conn.close()
            update.message.reply_text(f"🎉 Промокод активирован! +{reward} монет!\n💰 Баланс: {row[2]} монет", reply_markup=back_kb)
        else:
            conn.close()
            update.message.reply_text("❌ Промокод не найден или удален.", reply_markup=back_kb)

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
            # Показываем меню игры (как при нажатии cf_menu)
            update.message.reply_text(
                f"🪙 Монетка\n💰 Баланс: {row[2]} монет\nСтавка: {amount} монет\n\nУгадайте: 🪙 Орёл или 🦃 Решка?\nПравильный прогноз = x1.9",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("▶️ Начать игру", callback_data='cf_start')],
                    [InlineKeyboardButton(f"💰 Сделать ставку ({amount} монет)", callback_data='cf_set_bet')],
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
                f"⛏️ Минёр\n💰 Баланс: {row[2]} монет\nСтавка: {amount} монет | Мин: {mines}\n\n5x5 поле. {mines} мин. Открывайте безопасные ячейки!\nКомиссия: {8 + (mines - 3) * 0.3:.1f}%",
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
                f"🚀 Джетпак\n💰 Баланс: {row[2]} монет\nСтавка: {amount} монет | Авто-сбор: {auto_txt}\n\nМножитель растёт! Соберите до краша.\nКраш может случиться в любой момент (x1.00+).",
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
                f"🎰 Слоты\n💰 Баланс: {row[2]} монет\nСтавка: {amount} монет\n\nКомбинации:\n🍒x3 = 3x | 🍋x3 = 5x | 🔔x3 = 10x\n⭐x3 = 15x | 💎x3 = 25x | 7️⃣x3 = 50x\nДва одинаковых = возврат ставки",
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
            traps = context.user_data.get('tower_traps_count', 1)
            coeffs = TOWER_COEFFS_2BOMBS if traps == 2 else TOWER_COEFFS_1BOMB
            coeffs_txt = " → ".join([f"{c:.1f}x" for c in coeffs[:6]]) + " → ..."
            update.message.reply_text(
                f"🗼 Башня\n💰 Баланс: {row[2]} монет\nСтавка: {amount} монет | {traps} бомб{'а' if traps == 1 else 'ы'}/этаж\n\n"
                f"{TOWER_FLOORS} этажей. На каждом 3 ячейки — {traps} бомб{'а' if traps == 1 else 'ы'}.\n"
                f"Коэффициенты: {coeffs_txt}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("▶️ Начать", callback_data='tower_start')],
                    [InlineKeyboardButton(f"💰 Изменить ставку ({amount})", callback_data='tower_set_bet')],
                    [InlineKeyboardButton(f"💣 Мины: {traps}", callback_data='tower_set_traps')],
                    [InlineKeyboardButton("🔙 Назад", callback_data='games_menu')]
                ])
            )
        except ValueError:
            update.message.reply_text("❌ Введите корректное целое число!")

    elif state == 'candles_bet':
        try:
            amount = int(text)
            row = get_user(uid)
            if amount <= 0:
                update.message.reply_text("❌ Ставка должна быть больше 0! Введите снова:",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='candles_menu')]]))
                return
            if amount > row[2]:
                update.message.reply_text(f"❌ Недостаточно монет! У вас {row[2]}. Введите меньшую сумму:",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='candles_menu')]]))
                return
            context.user_data['state'] = ''
            context.user_data['candles_bet'] = amount
            # Показываем меню игры
            update.message.reply_text(
                f"📊 Японские свечи\n💰 Баланс: {row[2]} монет\nСтавка: {amount} монет\n\n"
                f"Режим: Бесконечная игра. Множители накапливаются!\n"
                f"Угадайте направление следующей свечи: 📈 Вверх или 📉 Вниз!\n"
                f"Правильный прогноз = x1.9 | Ошибка = потеря ставки",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("▶️ Начать игру", callback_data='candles_start')],
                    [InlineKeyboardButton(f"💰 Сделать ставку ({amount} монет)", callback_data='candles_set_bet')],
                    [InlineKeyboardButton("🔙 Назад", callback_data='games_menu')]
                ])
            )
        except ValueError:
            update.message.reply_text("❌ Введите корректное целое число!")

    # ── АДМИН ПАНЕЛЬ (ТЕКСТОВЫЕ ВВОДЫ) ──
    elif state == 'admin_user_search':
        users = search_users(text, page=0)

        if not users:
            update.message.reply_text("🔍 Пользователь не найден\n\nПопробуйте ввести другой ID или username:",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='admin_users')]]))
            # Не сбрасываем state, чтобы можно было повторно ввести
            return

        result_text = "🔍 Результаты поиска:\n\n"
        for u_id, uname, u_coins, u_refs in users:
            name = uname if uname else f"ID:{u_id}"
            result_text += f"{name} | 💰{u_coins} | 👥{u_refs}\n"

        # Show first user's details button
        first_user = users[0]
        result_text += f"\nНажмите для деталей:"

        context.user_data['state'] = ''  # Сбрасываем state только при успехе
        update.message.reply_text(result_text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"👤 {first_user[1] if first_user[1] else f'ID:{first_user[0]}'}", callback_data=f'user_info_{first_user[0]}')],
                [InlineKeyboardButton("🔙 Назад", callback_data='admin_users')]
            ])
        )

    elif state == 'admin_balance_amount':
        try:
            amount = int(text)
            if amount < 0:
                update.message.reply_text("❌ Сумма должна быть положительной!")
                return

            target_uid = context.user_data.get('admin_target_uid')
            action = context.user_data.get('admin_balance_action')

            if not target_uid or not action:
                update.message.reply_text("❌ Ошибка! Попробуйте снова.")
                context.user_data['state'] = ''
                return

            conn = sqlite3.connect(DB_PATH); c = conn.cursor()
            c.execute('SELECT coins FROM users WHERE id=?', (target_uid,))
            result = c.fetchone()
            conn.close()

            if not result:
                update.message.reply_text("❌ Пользователь не найден!")
                context.user_data['state'] = ''
                return

            current_balance = result[0]

            if action == 'add':
                add_coins(target_uid, amount)
                new_balance = current_balance + amount
                log_admin_action(uid, 'add_balance', 'user', target_uid, f'{amount} coins')
                msg = f"✅ Добавлено {amount} монет пользователю {target_uid}\nБаланс: {current_balance} → {new_balance}"
            elif action == 'sub':
                if amount > current_balance:
                    amount = current_balance
                add_coins(target_uid, -amount)
                new_balance = current_balance - amount
                log_admin_action(uid, 'sub_balance', 'user', target_uid, f'{amount} coins')
                msg = f"✅ Вычтено {amount} монет у пользователя {target_uid}\nБаланс: {current_balance} → {new_balance}"
            elif action == 'set':
                # Для set используем set_field напрямую
                set_field(target_uid, 'coins', amount)
                new_balance = amount
                log_admin_action(uid, 'set_balance', 'user', target_uid, f'{amount} coins')
                msg = f"✅ Установлено {amount} монет пользователю {target_uid}\nБаланс: {current_balance} → {new_balance}"
            else:
                msg = "❌ Неизвестное действие"

            context.user_data['state'] = ''
            update.message.reply_text(msg,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data=f'user_info_{target_uid}')]]))
        except ValueError:
            update.message.reply_text("❌ Введите корректное число!")

    elif state == 'admin_user_message':
        target_uid = context.user_data.get('admin_target_uid')
        if not target_uid:
            update.message.reply_text("❌ Ошибка! Попробуйте снова.")
            context.user_data['state'] = ''
            return

        try:
            update.message.bot.send_message(target_uid, text)
            log_admin_action(uid, 'send_message', 'user', target_uid, text)
            update.message.reply_text(f"✅ Сообщение отправлено пользователю {target_uid}")
        except Exception as e:
            update.message.reply_text(f"❌ Не удалось отправить сообщение: {e}")

        context.user_data['state'] = ''

    elif state == 'admin_broadcast_text':
        context.user_data['state'] = ''

        # Create broadcast record
        broadcast_id = create_broadcast('text', text, None, None, uid)
        log_admin_action(uid, 'create_broadcast', 'all', 0, f'ID: {broadcast_id}')

        # Send to all users
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute('SELECT id FROM users')
        users = c.fetchall()
        conn.close()

        sent_count = 0
        failed_count = 0

        for (user_id,) in users:
            try:
                update.message.bot.send_message(user_id, text, parse_mode='HTML')
                sent_count += 1
            except Exception:
                failed_count += 1

        mark_broadcast_sent(broadcast_id)

        update.message.reply_text(
            f"✅ Рассылка завершена!\n"
            f"📊 Отправлено: {sent_count}\n"
            f"❌ Ошибок: {failed_count}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='admin_broadcasts')]])
        )

    elif state == 'admin_broadcast_photo':
        # This state is set when expecting photo - photo is handled via MessageHandler with photo
        update.message.reply_text("❌ Пожалуйста, отправьте фото с подписью или просто текст для текстовой рассылки.")
        context.user_data['state'] = ''

    elif state == 'admin_promo_create':
        parts = text.split()
        if len(parts) < 2:
            update.message.reply_text("❌ Неверный формат! Пример: BONUS2025 500 100 1")
            return

        code = parts[0]
        try:
            reward = int(parts[1])
            max_uses = int(parts[2]) if len(parts) > 2 else None
            max_per_user = int(parts[3]) if len(parts) > 3 else 1
        except ValueError:
            update.message.reply_text("❌ Неверные числа! Пример: BONUS2025 500 100 1")
            return

        if create_promocode(code, reward, max_uses, max_per_user, uid):
            log_admin_action(uid, 'create_promo', 'promocode', code, f'reward: {reward}')
            uses_info = f"{max_uses}" if max_uses else "∞"
            update.message.reply_text(
                f"✅ Промокод создан!\n"
                f"🎫 Код: {code}\n"
                f"💰 Награда: {reward} монет\n"
                f"📊 Использований: {uses_info}\n"
                f"👤 На пользователя: {max_per_user}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='admin_promos')]])
            )
        else:
            update.message.reply_text("❌ Промокод с таким кодом уже существует!")

        context.user_data['state'] = ''

    elif state == 'admin_add_admin':
        # Try to parse as ID first, then search by username
        admin_id = None
        try:
            admin_id = int(text)
        except ValueError:
            # Search by username
            conn = sqlite3.connect(DB_PATH); c = conn.cursor()
            c.execute('SELECT id FROM users WHERE username=?', (text,))
            result = c.fetchone()
            conn.close()
            if result:
                admin_id = result[0]
            else:
                update.message.reply_text("❌ Пользователь не найден! Введите корректный ID или username.")
                context.user_data['state'] = ''
                return

        if admin_id:
            if add_admin(admin_id, uid):
                log_admin_action(uid, 'add_admin', 'admin', admin_id)
                update.message.reply_text(f"✅ Админ {admin_id} добавлен!",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='admin_admins')]]))
            else:
                update.message.reply_text("❌ Этот пользователь уже является админом!",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='admin_admins')]]))
        context.user_data['state'] = ''

    elif state == 'admin_global_add':
        try:
            amount = int(text)
            if amount < 0:
                update.message.reply_text("❌ Сумма должна быть положительной!")
                return

            conn = sqlite3.connect(DB_PATH); c = conn.cursor()
            c.execute('UPDATE users SET coins=coins+? WHERE is_blocked=0', (amount,))
            affected = c.rowcount
            conn.commit()
            conn.close()

            log_admin_action(uid, 'global_add', 'all', 0, f'{amount} coins to {affected} users')
            update.message.reply_text(
                f"✅ Добавлено {amount} монет всем активным пользователям!\n"
                f"👊 Затронуто: {affected} пользователей",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='admin_global_balance')]])
            )
        except ValueError:
            update.message.reply_text("❌ Введите корректное число!")
        context.user_data['state'] = ''

    elif state == 'admin_global_sub':
        try:
            amount = int(text)
            if amount < 0:
                update.message.reply_text("❌ Сумма должна быть положительной!")
                return

            conn = sqlite3.connect(DB_PATH); c = conn.cursor()
            c.execute('UPDATE users SET coins=MAX(0, coins-?) WHERE is_blocked=0', (amount,))
            affected = c.rowcount
            conn.commit()
            conn.close()

            log_admin_action(uid, 'global_sub', 'all', 0, f'{amount} coins from {affected} users')
            update.message.reply_text(
                f"✅ Вычтено {amount} монет у всех активных пользователей!\n"
                f"👊 Затронуто: {affected} пользователей",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='admin_global_balance')]])
            )
        except ValueError:
            update.message.reply_text("❌ Введите корректное число!")
        context.user_data['state'] = ''

    elif state == 'admin_global_set':
        try:
            amount = int(text)
            if amount < 0:
                update.message.reply_text("❌ Сумма должна быть положительной!")
                return

            conn = sqlite3.connect(DB_PATH); c = conn.cursor()
            c.execute('UPDATE users SET coins=? WHERE is_blocked=0', (amount,))
            affected = c.rowcount
            conn.commit()
            conn.close()

            log_admin_action(uid, 'global_set', 'all', 0, f'{amount} coins to {affected} users')
            update.message.reply_text(
                f"✅ Установлено {amount} монет всем активным пользователям!\n"
                f"👊 Затронуто: {affected} пользователей",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='admin_global_balance')]])
            )
        except ValueError:
            update.message.reply_text("❌ Введите корректное число!")
        context.user_data['state'] = ''

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
    dp.add_handler(CommandHandler("admin", admin_command))
    dp.add_handler(CallbackQueryHandler(btn))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_text))
    dp.add_handler(MessageHandler(Filters.photo, handle_photo))
    print("Bot started!")
    # clean=True to skip old updates that could cause lag spikes on restart
    updater.start_polling(drop_pending_updates=True, timeout=30)
    updater.idle()

if __name__ == '__main__':
    main()
