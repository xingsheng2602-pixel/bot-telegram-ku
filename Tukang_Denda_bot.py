import asyncio
import sqlite3
import logging
import random
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, ContextTypes

# ========== KONFIGURASI ==========
TOKEN = "8716960621:AAG7cFdVeb0Tio7lBBMoUSfiH32VpCqjfL8"
# DAFTAR ADMIN (ID Telegram) - Ganti sesuai kebutuhan
ADMIN_IDS = [7938242756, 8226764474, 6071806272]  # 3 admin

JAM_KERJA_MULAI = "10:00"

# Istirahat siang
ISTIRAHAT_1_MULAI = "11:00"
ISTIRAHAT_1_SELESAI = "12:00"
# Istirahat sore
ISTIRAHAT_2_MULAI = "17:00"
ISTIRAHAT_2_SELESAI = "18:00"

JAM_PULANG = "22:00"
UCAPAN_PULANG_DEFAULT = "Lelah hari ini, bayaran masa depan. Time to go home!"

# Daftar kata-kata pulang (random)
UCAPAN_PULANG_LIST = [
    "Kerja keras hari ini cukup, besok kita kerja keras lagi (kalau ingat).",
    "Pamit dulu, beban kerja sudah terlalu berat untuk punggung jompo ini.",
    "Hati lega, kerjaan beres, waktunya menghilang dari peradaban kantor.",
    "Jalan-jalan ke Semanggi, mampir warung beli mentega.",
    "Saat melihat jam pulang, hatiku langsung lega.",
    "Naik delman pulang dari desa, pulang-pulang mampir beli rotan.",
    "Terima kasih atas semua jasa, sampai bertemu lagi di lain kesempatan.",
    "Buah nangka buah manggis, niat kerja malah pengen nangis. Untung sekarang sudah boleh pulang.",
    "Capek boleh, nyerah jangan. Tapi kalau disuruh lembur tanpa uang makan, kabur duluan.",
    "Kerja keraslah sampai tetanggamu mengira kamu pelihara tuyul, padahal cuma pelihara kantung mata.",
    "Pulang kerja bukan mau istirahat, tapi mau simulasi jadi orang kaya yang nggak usah kerja.",
    "Mata sudah sayup, gaji belum naik. Yuk pulang!",
    "Boss bilang produktif, hatiku bilang pulang.",
    "Ketika jam pulang tiba, semua masalah terasa lebih ringan.",
    "Pulang adalah waktu terbaik untuk memikirkan alasan izin besok.",
]

# Daftar kata-kata untuk user yang telat absen pagi (random)
UCAPAN_TELAT_PAGI = [
    "🌅 Matahari sudah tinggi, tapi semangatmu masih di kasur? Besok lebih pagi ya!",
    "⏰ Telat lagi? Jam dinding di kantor ini nggak pernah bohong lho.",
    "🚦 Macet? Atau alarmnya yang macet? Coba alarm disetel lebih keras!",
    "🍳 Sarapan dulu ya? Lain kali sarapan sambil jalan aja, biar nggak telat.",
    "📉 Produktivitas menurun saat kamu telat. Besok semangat lagi!",
    "🐢 Katakan tidak pada telat! Kamu lebih keren dari ini.",
    "🎯 Target jam 10:00, tapi kamu datang jam {jam}. Masih bisa diperbaiki kok.",
    "💪 Besok coba bangun 30 menit lebih awal. Badan sehat, absen tepat!",
    "🕙 Waktu adalah uang. Sayang banget kalau terbuang cuma karena kesiangan.",
    "📢 Paging: Karyawan yang telat, harap segera berkumpul di sini. Denda ditanggung sendirian 😄",
]

DEFAULT_DURASI_IZIN_MENIT = 10
TOLERANSI_ISTIRAHAT = 0   # 0 menit toleransi (harus tepat waktu)

DB_PATH = "absen_bot.db"
logging.basicConfig(level=logging.INFO)

# ========== FUNGSI JAM ISTIRAHAT ==========
def parse_time(time_str: str) -> datetime.time:
    return datetime.strptime(time_str, "%H:%M").time()

def get_break_intervals() -> List[Tuple[datetime.time, datetime.time]]:
    intervals = []
    if ISTIRAHAT_1_MULAI and ISTIRAHAT_1_SELESAI:
        intervals.append((parse_time(ISTIRAHAT_1_MULAI), parse_time(ISTIRAHAT_1_SELESAI)))
    if ISTIRAHAT_2_MULAI and ISTIRAHAT_2_SELESAI:
        intervals.append((parse_time(ISTIRAHAT_2_MULAI), parse_time(ISTIRAHAT_2_SELESAI)))
    return intervals

def is_time_in_break(t: datetime.time) -> bool:
    for start, end in get_break_intervals():
        if start <= t < end:
            return True
    return False

def calculate_end_time_with_breaks(start: datetime, duration_minutes: int) -> datetime:
    current = start
    remaining = duration_minutes
    while remaining > 0:
        next_min = current + timedelta(minutes=1)
        if is_time_in_break(next_min.time()):
            current = next_min
        else:
            current = next_min
            remaining -= 1
    return current

# ========== DATABASE ==========
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER UNIQUE,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS absensi (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    tanggal TEXT,
                    shift TEXT,
                    waktu_masuk TEXT,
                    status TEXT
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS izin_toilet (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    start_time TEXT,
                    durasi_menit INTEGER,
                    expected_end_time TEXT,
                    actual_end_time TEXT,
                    status TEXT,
                    chat_id INTEGER
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS chats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER UNIQUE,
                    chat_type TEXT
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS pulang_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER,
                    tanggal TEXT,
                    UNIQUE(chat_id, tanggal)
                )''')
    conn.commit()
    conn.close()

def get_or_create_user(telegram_user) -> int:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE telegram_id = ?", (telegram_user.id,))
    row = c.fetchone()
    if row:
        user_id = row[0]
    else:
        c.execute("INSERT INTO users (telegram_id, username, first_name, last_name) VALUES (?, ?, ?, ?)",
                  (telegram_user.id, telegram_user.username, telegram_user.first_name, telegram_user.last_name))
        user_id = c.lastrowid
        conn.commit()
    conn.close()
    return user_id

def sudah_absen(user_id_db: int, tanggal: str, shift: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id FROM absensi WHERE user_id = ? AND tanggal = ? AND shift = ?", (user_id_db, tanggal, shift))
    ok = c.fetchone() is not None
    conn.close()
    return ok

def catat_absen(user_id_db: int, tanggal: str, shift: str, waktu_str: str, status: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO absensi (user_id, tanggal, shift, waktu_masuk, status) VALUES (?, ?, ?, ?, ?)",
              (user_id_db, tanggal, shift, waktu_str, status))
    conn.commit()
    conn.close()

def register_chat(chat_id: int, chat_type: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO chats (chat_id, chat_type) VALUES (?, ?)", (chat_id, chat_type))
    conn.commit()
    conn.close()

def sudah_kirim_pulang_today(chat_id: int, tanggal: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id FROM pulang_log WHERE chat_id = ? AND tanggal = ?", (chat_id, tanggal))
    ok = c.fetchone() is not None
    conn.close()
    return ok

def catat_kirim_pulang(chat_id: int, tanggal: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO pulang_log (chat_id, tanggal) VALUES (?, ?)", (chat_id, tanggal))
    conn.commit()
    conn.close()

def get_all_chats() -> List[int]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT chat_id FROM chats")
    rows = c.fetchall()
    conn.close()
    return [row[0] for row in rows]

def get_active_izin(user_telegram_id: int):
    """Mengembalikan (izin_id, user_id_db, expected_end_time, durasi, chat_id) untuk izin aktif user."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''SELECT izin.id, izin.user_id, izin.expected_end_time, izin.durasi_menit, izin.chat_id
                 FROM izin_toilet izin
                 JOIN users ON izin.user_id = users.id
                 WHERE users.telegram_id = ? AND izin.actual_end_time IS NULL
                 ORDER BY izin.start_time DESC LIMIT 1''', (user_telegram_id,))
    row = c.fetchone()
    conn.close()
    return row

def cancel_izin_by_id(izin_id: int):
    """Set actual_end_time = sekarang dan status = dibatalkan."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE izin_toilet SET actual_end_time = ?, status = ? WHERE id = ?",
              (datetime.now().isoformat(), "dibatalkan", izin_id))
    conn.commit()
    conn.close()

# ========== TIMER & TASK ==========
active_timers: Dict[int, asyncio.Task] = {}

async def schedule_reminder(app, chat_id, user_id, username, durasi, izin_id, delay_seconds):
    async def reminder():
        await asyncio.sleep(delay_seconds)
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT actual_end_time FROM izin_toilet WHERE id = ?", (izin_id,))
        row = c.fetchone()
        conn.close()
        if row and row[0] is None:
            mention = f"@{username}" if username else f"User {user_id}"
            await app.bot.send_message(
                chat_id=chat_id,
                text=f"{mention}, waktu izin toilet/merokok {durasi} menit telah berakhir. Segera selesaikan dengan /selesai_toilet."
            )
    task = asyncio.create_task(reminder())
    active_timers[user_id] = task

async def restore_timers(app):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''SELECT izin.id, izin.user_id, izin.expected_end_time, izin.durasi_menit, izin.chat_id, users.telegram_id, users.username
                 FROM izin_toilet izin
                 JOIN users ON izin.user_id = users.id
                 WHERE izin.actual_end_time IS NULL''')
    rows = c.fetchall()
    for izin_id, user_id, expected_end_str, durasi, chat_id, telegram_id, username in rows:
        expected_end = datetime.fromisoformat(expected_end_str)
        now = datetime.now()
        if expected_end > now:
            sisa = (expected_end - now).total_seconds()
            await schedule_reminder(app, chat_id, telegram_id, username, durasi, izin_id, sisa)
    conn.close()

async def daily_pulang_checker(app: Application):
    """Task berjalan setiap menit, mengirim pesan pulang jam 22:00."""
    while True:
        now = datetime.now()
        jam_pulang = parse_time(JAM_PULANG)
        if now.hour == jam_pulang.hour and now.minute == jam_pulang.minute:
            tanggal = now.strftime("%Y-%m-%d")
            chats = get_all_chats()
            for chat_id in chats:
                if not sudah_kirim_pulang_today(chat_id, tanggal):
                    pesan = random.choice(UCAPAN_PULANG_LIST)
                    final_pesan = f"🎉 *Pulang Kerja!* 🎉\n\n{pesan}\n\n{UCAPAN_PULANG_DEFAULT}"
                    await app.bot.send_message(chat_id=chat_id, text=final_pesan, parse_mode="Markdown")
                    catat_kirim_pulang(chat_id, tanggal)
        await asyncio.sleep(60)

# ========== HANDLER ==========
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat:
        register_chat(chat.id, chat.type)
    await update.message.reply_text(
        "👋 Selamat datang di Bot Absen & Denda!\n\n"
        "Perintah:\n"
        "/absen_masuk - Absen pagi (jam 10:00)\n"
        "/istirahat_siang_mulai - Mulai istirahat siang (jam 11:00)\n"
        "/absen_istirahat_siang - Kembali dari istirahat siang (jam 12:00)\n"
        "/istirahat_sore_mulai - Mulai istirahat sore (jam 17:00)\n"
        "/absen_istirahat_sore - Kembali dari istirahat sore (jam 18:00)\n"
        "/izin_toilet [durasi] - Izin toilet/merokok (default 10 menit)\n"
        "/selesai_toilet - Selesai dari toilet\n"
        "/pulang - Ucapan pulang manual\n"
        "/laporan_bulanan [tahun bulan] - Laporan admin\n"
        "/cancel_izin @username - (ADMIN) Batalkan izin toilet user karena kondisi darurat\n\n"
        "Bot akan otomatis mengucapkan selamat pulang setiap jam 22:00."
    )

async def cmd_absen_masuk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    now = datetime.now()
    user_id_db = get_or_create_user(user)
    tanggal = now.strftime("%Y-%m-%d")
    jam_kerja = parse_time(JAM_KERJA_MULAI)
    jam_sekarang = now.time()
    status = "telat" if jam_sekarang > jam_kerja else "tepat"

    if sudah_absen(user_id_db, tanggal, "pagi"):
        await update.message.reply_text("⚠️ Anda sudah absen pagi hari ini.")
        return

    catat_absen(user_id_db, tanggal, "pagi", now.strftime("%Y-%m-%d %H:%M:%S"), status)
    pesan = f"✅ Absen pagi: {now.strftime('%H:%M:%S')} - Status: {status.upper()}"
    if status == "telat":
        telat_menit = int((now - datetime.combine(now.date(), jam_kerja)).total_seconds() // 60)
        kata = random.choice(UCAPAN_TELAT_PAGI).replace("{jam}", now.strftime("%H:%M"))
        pesan += f"\n\n⚠️ *Kamu telat {telat_menit} menit!*\n{kata}"
    await update.message.reply_text(pesan, parse_mode="Markdown")

async def cmd_mulai_istirahat(update: Update, context: ContextTypes.DEFAULT_TYPE, shift: str, jam_mulai_str: str, nama_shift: str):
    user = update.effective_user
    now = datetime.now()
    tanggal = now.strftime("%Y-%m-%d")
    jam_mulai = parse_time(jam_mulai_str)
    jam_sekarang = now.time()

    if jam_sekarang < jam_mulai:
        await update.message.reply_text(f"❌ Belum waktunya mulai {nama_shift}. Mulai jam {jam_mulai_str}.")
        return
    if jam_sekarang > jam_mulai:
        status = "telat"
        telat_menit = int((now - datetime.combine(now.date(), jam_mulai)).total_seconds() // 60)
        await update.message.reply_text(f"⚠️ Anda telat mulai {nama_shift} {telat_menit} menit. Pelanggaran tercatat.")
    else:
        status = "tepat"

    if sudah_absen(get_or_create_user(user), tanggal, shift):
        await update.message.reply_text(f"⚠️ Anda sudah absen {nama_shift} hari ini.")
        return

    catat_absen(get_or_create_user(user), tanggal, shift, now.strftime("%Y-%m-%d %H:%M:%S"), status)
    await update.message.reply_text(f"✅ {nama_shift.capitalize()} mulai: {now.strftime('%H:%M:%S')} - Status: {status.upper()}")

async def cmd_istirahat_siang_mulai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_mulai_istirahat(update, context, "siang_mulai", ISTIRAHAT_1_MULAI, "istirahat siang")

async def cmd_istirahat_sore_mulai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_mulai_istirahat(update, context, "sore_mulai", ISTIRAHAT_2_MULAI, "istirahat sore")

async def cmd_absen_istirahat(update: Update, context: ContextTypes.DEFAULT_TYPE, shift: str, jam_selesai_str: str, nama_shift: str):
    user = update.effective_user
    now = datetime.now()
    tanggal = now.strftime("%Y-%m-%d")
    jam_selesai = parse_time(jam_selesai_str)
    jam_sekarang = now.time()

    batas_akhir = (datetime.combine(now.date(), jam_selesai) + timedelta(minutes=TOLERANSI_ISTIRAHAT)).time()

    if jam_sekarang < jam_selesai:
        await update.message.reply_text(f"❌ Belum waktunya absen {nama_shift}. Silakan absen mulai jam {jam_selesai_str}.")
        return

    if jam_sekarang > batas_akhir:
        status = "telat"
        telat_menit = int((datetime.combine(now.date(), jam_sekarang) - datetime.combine(now.date(), batas_akhir)).total_seconds() // 60)
        await update.message.reply_text(f"⚠️ Anda telat absen {nama_shift} {telat_menit} menit. Pelanggaran tercatat.")
    else:
        status = "tepat"

    if sudah_absen(get_or_create_user(user), tanggal, shift):
        await update.message.reply_text(f"⚠️ Anda sudah absen {nama_shift} hari ini.")
        return

    catat_absen(get_or_create_user(user), tanggal, shift, now.strftime("%Y-%m-%d %H:%M:%S"), status)
    await update.message.reply_text(f"✅ Absen {nama_shift}: {now.strftime('%H:%M:%S')} - Status: {status.upper()}")

async def cmd_absen_siang(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_absen_istirahat(update, context, "siang", ISTIRAHAT_1_SELESAI, "setelah istirahat siang")

async def cmd_absen_sore(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_absen_istirahat(update, context, "sore", ISTIRAHAT_2_SELESAI, "setelah istirahat sore")

async def cmd_izin_toilet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    if not user or not chat:
        return
    user_id_db = get_or_create_user(user)
    args = context.args
    durasi = DEFAULT_DURASI_IZIN_MENIT
    if args and args[0].isdigit():
        durasi = int(args[0])
        if durasi <= 0:
            await update.message.reply_text("Durasi harus positif.")
            return

    start_time = datetime.now()
    expected_end = calculate_end_time_with_breaks(start_time, durasi)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''INSERT INTO izin_toilet (user_id, start_time, durasi_menit, expected_end_time, chat_id)
                 VALUES (?, ?, ?, ?, ?)''',
              (user_id_db, start_time.isoformat(), durasi, expected_end.isoformat(), chat.id))
    izin_id = c.lastrowid
    conn.commit()
    conn.close()

    mention = f"@{user.username}" if user.username else user.first_name
    total_menit = int((expected_end - start_time).total_seconds() // 60)
    await update.message.reply_text(
        f"{mention}, izin toilet/merokok {durasi} menit mulai {start_time.strftime('%H:%M')}.\n"
        f"Karena jam istirahat, waktu selesai: {expected_end.strftime('%H:%M')} (total {total_menit} menit).\n"
        "Selesai? /selesai_toilet"
    )

    if user.id in active_timers:
        old = active_timers[user.id]
        if not old.done():
            old.cancel()
        del active_timers[user.id]

    delay = total_menit * 60
    await schedule_reminder(context.application, chat.id, user.id, user.username, durasi, izin_id, delay)

async def cmd_selesai_toilet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id_db = get_or_create_user(user)
    now = datetime.now()

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''SELECT id, expected_end_time, durasi_menit FROM izin_toilet 
                 WHERE user_id = ? AND actual_end_time IS NULL ORDER BY start_time DESC LIMIT 1''', (user_id_db,))
    row = c.fetchone()
    if not row:
        await update.message.reply_text("Tidak ada izin aktif.")
        conn.close()
        return

    izin_id, expected_end_str, _ = row
    expected_end = datetime.fromisoformat(expected_end_str)
    if now > expected_end:
        status = "melebihi"
        selisih = int((now - expected_end).total_seconds() // 60)
        await update.message.reply_text(f"⚠️ Anda melebihi batas waktu {selisih} menit. Pelanggaran tercatat.")
    else:
        status = "tepat"
        await update.message.reply_text("✅ Izin selesai tepat waktu.")

    c.execute("UPDATE izin_toilet SET actual_end_time = ?, status = ? WHERE id = ?",
              (now.isoformat(), status, izin_id))
    conn.commit()
    conn.close()

    if user.id in active_timers:
        old = active_timers[user.id]
        if not old.done():
            old.cancel()
        del active_timers[user.id]

# ---------- CANCEL IZIN OLEH ADMIN ----------
async def cmd_cancel_izin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Hanya admin: membatalkan izin toilet user yang sedang aktif. Format: /cancel_izin @username"""
    user = update.effective_user
    if not user or user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Hanya admin yang dapat membatalkan izin.")
        return

    if not context.args:
        await update.message.reply_text("Format: /cancel_izin @username\nContoh: /cancel_izin @bambang")
        return

    target_username = context.args[0].lstrip('@')
    # Cari user berdasarkan username (case-insensitive)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT telegram_id, id FROM users WHERE username = ?", (target_username,))
    row = c.fetchone()
    conn.close()
    if not row:
        await update.message.reply_text(f"User @{target_username} tidak ditemukan dalam database.")
        return

    target_telegram_id, target_user_id_db = row
    izin_data = get_active_izin(target_telegram_id)
    if not izin_data:
        await update.message.reply_text(f"User @{target_username} tidak memiliki izin toilet aktif.")
        return

    izin_id, _, expected_end_str, durasi, chat_id = izin_data
    # Batalkan izin
    cancel_izin_by_id(izin_id)
    # Hentikan timer jika ada
    if target_telegram_id in active_timers:
        old = active_timers[target_telegram_id]
        if not old.done():
            old.cancel()
        del active_timers[target_telegram_id]

    await update.message.reply_text(f"✅ Izin toilet @{target_username} (durasi {durasi} menit) telah dibatalkan oleh admin karena kondisi darurat.")
    # Kirim notifikasi ke user yang bersangkutan (jika bot bisa DM)
    try:
        await context.bot.send_message(chat_id=target_telegram_id, text=f"Admin membatalkan izin toilet Anda karena kondisi darurat. Silakan lanjutkan aktivitas.")
    except:
        pass

async def cmd_pulang(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now()
    jam_pulang = parse_time(JAM_PULANG)
    if now.time() >= jam_pulang:
        pesan = random.choice(UCAPAN_PULANG_LIST)
        await update.message.reply_text(f"🎉 *Pulang Kerja!* 🎉\n\n{pesan}\n\n{UCAPAN_PULANG_DEFAULT}", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"Belum waktunya pulang. Pulang jam {JAM_PULANG}.")

async def cmd_laporan_bulanan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Hanya admin yang bisa melihat laporan.")
        return

    args = context.args
    if len(args) >= 2:
        tahun = int(args[0])
        bulan = int(args[1])
    else:
        now = datetime.now()
        tahun = now.year
        bulan = now.month

    start_date = f"{tahun}-{bulan:02d}-01"
    if bulan == 12:
        end_date = f"{tahun+1}-01-01"
    else:
        end_date = f"{tahun}-{bulan+1:02d}-01"

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, telegram_id, username, first_name FROM users")
    users = c.fetchall()

    laporan = f"📊 Laporan Bulanan {tahun}-{bulan:02d}\n\n"
    for uid, _, username, first_name in users:
        nama = username or first_name
        # Telat pagi
        c.execute("SELECT COUNT(*) FROM absensi WHERE user_id = ? AND tanggal >= ? AND tanggal < ? AND shift='pagi' AND status='telat'",
                  (uid, start_date, end_date))
        telat_pagi = c.fetchone()[0]
        # Telat mulai siang
        c.execute("SELECT COUNT(*) FROM absensi WHERE user_id = ? AND tanggal >= ? AND tanggal < ? AND shift='siang_mulai' AND status='telat'",
                  (uid, start_date, end_date))
        telat_mulai_siang = c.fetchone()[0]
        # Telat kembali siang
        c.execute("SELECT COUNT(*) FROM absensi WHERE user_id = ? AND tanggal >= ? AND tanggal < ? AND shift='siang' AND status='telat'",
                  (uid, start_date, end_date))
        telat_siang = c.fetchone()[0]
        # Telat mulai sore
        c.execute("SELECT COUNT(*) FROM absensi WHERE user_id = ? AND tanggal >= ? AND tanggal < ? AND shift='sore_mulai' AND status='telat'",
                  (uid, start_date, end_date))
        telat_mulai_sore = c.fetchone()[0]
        # Telat kembali sore
        c.execute("SELECT COUNT(*) FROM absensi WHERE user_id = ? AND tanggal >= ? AND tanggal < ? AND shift='sore' AND status='telat'",
                  (uid, start_date, end_date))
        telat_sore = c.fetchone()[0]
        # Pelanggaran toilet (melebihi batas, tidak termasuk yang dibatalkan)
        c.execute("SELECT COUNT(*) FROM izin_toilet WHERE user_id = ? AND actual_end_time IS NOT NULL AND status='melebihi' AND actual_end_time >= ? AND actual_end_time < ?",
                  (uid, start_date, end_date))
        pelanggaran_toilet = c.fetchone()[0]

        laporan += (f"👤 {nama}\n"
                    f"   Telat pagi: {telat_pagi}\n"
                    f"   Telat mulai siang: {telat_mulai_siang}\n"
                    f"   Telat kembali siang: {telat_siang}\n"
                    f"   Telat mulai sore: {telat_mulai_sore}\n"
                    f"   Telat kembali sore: {telat_sore}\n"
                    f"   Pelanggaran WC: {pelanggaran_toilet}\n\n")
    conn.close()
    await update.message.reply_text(laporan)

# ========== SET PERINTAH ==========
async def set_commands(app: Application):
    commands = [
        BotCommand("start", "Mulai dan lihat daftar perintah"),
        BotCommand("absen_masuk", "Absen pagi (jam 10:00)"),
        BotCommand("istirahat_siang_mulai", "Mulai istirahat siang (jam 11:00)"),
        BotCommand("absen_istirahat_siang", "Kembali dari istirahat siang (jam 12:00)"),
        BotCommand("istirahat_sore_mulai", "Mulai istirahat sore (jam 17:00)"),
        BotCommand("absen_istirahat_sore", "Kembali dari istirahat sore (jam 18:00)"),
        BotCommand("izin_toilet", "Izin toilet/merokok (default 10 menit)"),
        BotCommand("selesai_toilet", "Selesaikan izin toilet"),
        BotCommand("cancel_izin", "(ADMIN) Batalkan izin user @username"),
        BotCommand("pulang", "Ucapan pulang manual"),
        BotCommand("laporan_bulanan", "Laporan bulanan (hanya admin)"),
    ]
    await app.bot.set_my_commands(commands)

# ========== MAIN ==========
def main():
    init_db()
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("absen_masuk", cmd_absen_masuk))
    app.add_handler(CommandHandler("istirahat_siang_mulai", cmd_istirahat_siang_mulai))
    app.add_handler(CommandHandler("absen_istirahat_siang", cmd_absen_siang))
    app.add_handler(CommandHandler("istirahat_sore_mulai", cmd_istirahat_sore_mulai))
    app.add_handler(CommandHandler("absen_istirahat_sore", cmd_absen_sore))
    app.add_handler(CommandHandler("izin_toilet", cmd_izin_toilet))
    app.add_handler(CommandHandler("selesai_toilet", cmd_selesai_toilet))
    app.add_handler(CommandHandler("cancel_izin", cmd_cancel_izin))
    app.add_handler(CommandHandler("pulang", cmd_pulang))
    app.add_handler(CommandHandler("laporan_bulanan", cmd_laporan_bulanan))

    async def post_init(app: Application):
        await restore_timers(app)
        await set_commands(app)
        asyncio.create_task(daily_pulang_checker(app))

    app.post_init = post_init

    print("Bot sedang berjalan...")
    print(f"Admin IDs: {ADMIN_IDS}")
    print("Fitur: absen pagi/istirahat, izin toilet, cancel izin oleh admin, pulang otomatis jam 22:00.")
    app.run_polling()

if __name__ == "__main__":
    main()