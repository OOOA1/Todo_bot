import time
import telebot
from telebot.apihelper import ApiTelegramException
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import db

TOKEN = '8081090023:AAHizaGHTAshsYhPi7dOePK_slGyPnxQDxU'
bot = telebot.TeleBot(TOKEN, parse_mode='Markdown')
db.create_tables()
user_states = {}

# ——————————————————————————————————————————————————————————————
# Клавиатуры
# ——————————————————————————————————————————————————————————————

def action_kb():
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("Принято", callback_data="accepted"))
    return kb

def status_kb():
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("Не выполнено",  callback_data="status_ne"))
    kb.add(InlineKeyboardButton("Принято",        callback_data="status_accepted"))
    return kb

# ——————————————————————————————————————————————————————————————
# Хендлеры команд
# ——————————————————————————————————————————————————————————————

@bot.message_handler(commands=['start'])
def cmd_start(m):
    bot.send_message(
        m.chat.id,
        "Привет! Доступные команды:\n"
        "/newtask — создать задачу\n"
        "/task    — показать все задачи\n"
        "/filter  — отфильтровать задачи"
    )

@bot.message_handler(commands=['newtask'])
def cmd_newtask(m):
    user_states[m.from_user.id] = 'await_text'
    bot.send_message(m.chat.id, "Введите текст задачи:")

@bot.message_handler(
    func=lambda m: user_states.get(m.from_user.id) == 'await_text',
    content_types=['text']
)
def handle_newtask_text(m):
    text   = m.text
    author = m.from_user.first_name or 'Пользователь'
    cid    = m.chat.id

    msg = bot.send_message(
        cid,
        f"*Задача:*\n{text}\n*Поставил:* {author}\n*Статус:* ❗ Не выполнено",
        reply_markup=action_kb()
    )
    db.add_task(cid, msg.message_id, author, text, 'не выполнено')
    user_states.pop(m.from_user.id, None)

@bot.message_handler(commands=['task'])
def cmd_task(m):
    cid = m.chat.id
    mids = db.get_all_tasks(cid)
    if not mids:
        bot.send_message(cid, "Нет задач в этом чате.")
        return

    for mid in mids:
        txt, status = db.get_task_by_id(cid, mid)
        bot.send_message(
            cid,
            f"{txt}\n\nСтатус: {status}",
            reply_to_message_id=mid,
            parse_mode='Markdown'
        )

@bot.message_handler(commands=['filter'])
def cmd_filter(m):
    bot.send_message(
        m.chat.id,
        "Выберите статус:",
        reply_markup=status_kb()
    )

# ——————————————————————————————————————————————————————————————
# Обработчики inline-кнопок
# ——————————————————————————————————————————————————————————————

# 1) Принять задачу
@bot.callback_query_handler(func=lambda cb: cb.data == 'accepted')
def handle_accepted(cb):
    cid = cb.message.chat.id
    mid = cb.message.message_id

    new = cb.message.text.replace('❗ Не выполнено', '✅ Принято')
    bot.edit_message_text(new, cid, mid, parse_mode='Markdown')
    db.update_task_status(cid, mid, 'принято')
    bot.answer_callback_query(cb.id)

# 2) Фильтрация по статусу
@bot.callback_query_handler(func=lambda cb: cb.data in ('status_ne','status_accepted'))
def handle_status_filter(cb):
    cid  = cb.message.chat.id
    data = cb.data
    st   = {'status_ne':'не выполнено','status_accepted':'принято'}[data]

    mids = db.get_tasks_by_status(cid, st)
    if not mids:
        bot.edit_message_text(
            f"❌ Нет задач со статусом «{st}».",
            cid,
            cb.message.message_id,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀ Назад", callback_data="back_filter")
            ]])
        )
    else:
        kb = InlineKeyboardMarkup()
        for mid in mids:
            txt, _ = db.get_task_by_id(cid, mid)
            label = txt if len(txt) < 25 else txt[:25] + '…'
            kb.add(InlineKeyboardButton(label, callback_data=f"task_{mid}_{data}"))
        kb.add(InlineKeyboardButton("📨 Прислать все", callback_data=f"send_all_{data}"))
        kb.add(InlineKeyboardButton("◀ Назад",         callback_data="back_filter"))

        bot.edit_message_text(
            f"📋 Задачи со статусом «{st}»:",
            cid,
            cb.message.message_id,
            reply_markup=kb
        )
    bot.answer_callback_query(cb.id)

# 3) Прислать все задачи выбранного статуса
@bot.callback_query_handler(func=lambda cb: cb.data.startswith('send_all_'))
def handle_send_all(cb):
    cid       = cb.message.chat.id
    status_cd = cb.data[len('send_all_'):]
    st        = {'status_ne':'не выполнено','status_accepted':'принято'}[status_cd]
    mids      = db.get_tasks_by_status(cid, st)

    if not mids:
        bot.answer_callback_query(cb.id, text="Нет задач для отправки.")
        return

    try:
        for mid in mids:
            txt, _ = db.get_task_by_id(cid, mid)
            bot.send_message(
                cid,
                f"{txt}\n\nСтатус: {st}",
                reply_to_message_id=mid,
                parse_mode='Markdown'
            )
    except ApiTelegramException as e:
        if hasattr(e, 'result_json') and e.result_json.get('error_code') == 429:
            retry = e.result_json.get('parameters', {}).get('retry_after', 'несколько')
            bot.answer_callback_query(cb.id, text=f"Слишком часто — подожди {retry} сек.")
            return
        else:
            raise

    # Убираем кнопку «Прислать все»
    kb = InlineKeyboardMarkup()
    for mid in mids:
        txt, _ = db.get_task_by_id(cid, mid)
        label = txt if len(txt) < 25 else txt[:25] + '…'
        kb.add(InlineKeyboardButton(label, callback_data=f"task_{mid}_{status_cd}"))
    kb.add(InlineKeyboardButton("◀ Назад", callback_data="back_filter"))

    bot.edit_message_reply_markup(
        chat_id=cid,
        message_id=cb.message.message_id,
        reply_markup=kb
    )

    bot.answer_callback_query(cb.id, text=f"Отправлено {len(mids)} задач.")

# 4) Выбор конкретной задачи
@bot.callback_query_handler(func=lambda cb: cb.data.startswith('task_'))
def handle_task_select(cb):
    cid = cb.message.chat.id
    _, mid_s, status_cd = cb.data.split('_', 2)
    mid = int(mid_s)
    human = {'status_ne':'не выполнено','status_accepted':'принято'}[status_cd]

    rec = db.get_task_by_id(cid, mid)
    if rec:
        txt, _ = rec
        bot.send_message(
            cid,
            f"🔍 Задача:\n\n{txt}\n\nСтатус: {human}",
            reply_to_message_id=mid,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀ Назад", callback_data="back_filter")
            ]]),
            parse_mode='Markdown'
        )
    else:
        bot.send_message(cid, "❌ Задача не найдена.")
    bot.answer_callback_query(cb.id)

# 5) Назад в меню фильтра
@bot.callback_query_handler(func=lambda cb: cb.data == 'back_filter')
def handle_back_filter(cb):
    bot.edit_message_text(
        "Выберите статус:",
        cb.message.chat.id,
        cb.message.message_id,
        reply_markup=status_kb()
    )
    bot.answer_callback_query(cb.id)

# ——————————————————————————————————————————————————————————————
# Запуск polling
# ——————————————————————————————————————————————————————————————

if __name__ == '__main__':
    bot.remove_webhook()
    time.sleep(1)
    bot.polling(none_stop=True, skip_pending=False)
