import sqlite3
import logging
import time
from db import get_db

logger = logging.getLogger(__name__)

# Настройки автоматического повтора при блокировке базы
RETRY_COUNT = 3     # сколько раз пробовать снова
RETRY_DELAY = 0.2   # пауза между попытками в секундах

def _with_retry(func):
    """
    Декоратор для автоматического повторения функции, если база занята (database is locked).
    Возвращает строку-код ошибки или результат функции.
    """
    def wrapper(*args, **kwargs):
        for attempt in range(RETRY_COUNT):
            try:
                return func(*args, **kwargs)
            except sqlite3.OperationalError as e:
                # Если база занята другим процессом — ждем и пробуем снова
                if 'database is locked' in str(e):
                    logger.warning(f"[{func.__name__}] database is locked, попытка {attempt+1}/{RETRY_COUNT}")
                    time.sleep(RETRY_DELAY)
                else:
                    # Другие ошибки OperationalError сразу логируем и не повторяем
                    logger.error(f"[{func.__name__}] sqlite3.OperationalError: {e}")
                    break
            except sqlite3.IntegrityError as e:
                # Нарушение ограничений (дубликат ключа, NOT NULL, и др.)
                logger.warning(f"[{func.__name__}] Нарушение ограничений: {e}")
                return "integrity"
            except sqlite3.DatabaseError as e:
                # Другие ошибки SQLite
                logger.error(f"[{func.__name__}] DatabaseError: {e}", exc_info=True)
                return "db_error"
            except Exception as e:
                # Любые другие ошибки
                logger.exception(f"[{func.__name__}] Неизвестная ошибка: {e}")
                return "unknown"
        # Если ни одна попытка не удалась из-за блокировки
        logger.error(f"[{func.__name__}] Не удалось выполнить после {RETRY_COUNT} попыток из-за 'database is locked'")
        return "locked"
    return wrapper

@_with_retry
def create_tables():
    """
    Создаёт таблицу tasks, если её нет.
    Возвращает True при успехе, иначе строку-код ошибки.
    """
    db = get_db()
    db.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id      INTEGER NOT NULL,
            thread_id    INTEGER,
            message_id   INTEGER NOT NULL,
            author       TEXT    NOT NULL,
            text         TEXT    NOT NULL,
            status       TEXT    NOT NULL,
            accepted_by  TEXT
        )
    ''')
    db.commit()
    return True

@_with_retry
def add_task(chat_id, thread_id, message_id, author, text, status, accepted_by):
    """
    Добавляет задачу в таблицу.
    Возвращает True при успехе, иначе строку-код ошибки.
    """
    db = get_db()
    db.execute('''
        INSERT INTO tasks
            (chat_id, thread_id, message_id, author, text, status, accepted_by)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (chat_id, thread_id, message_id, author, text, status, accepted_by))
    db.commit()
    return True

@_with_retry
def update_task_status(chat_id, thread_id, message_id, status, accepted_by):
    """
    Обновляет статус и принявшего исполнителя для задачи.
    Возвращает True при успехе, иначе строку-код ошибки.
    """
    db = get_db()
    db.execute('''
        UPDATE tasks
           SET status = ?, accepted_by = ?
         WHERE chat_id = ? AND thread_id IS ? AND message_id = ?
    ''', (status, accepted_by, chat_id, thread_id, message_id))
    db.commit()
    return True

@_with_retry
def get_all_tasks(chat_id, thread_id):
    """
    Возвращает список message_id всех задач для данного чата и треда.
    При ошибке — возвращает строку-код ошибки или пустой список.
    """
    db = get_db()
    cur = db.cursor()
    cur.execute('''
        SELECT message_id
          FROM tasks
         WHERE chat_id = ? AND thread_id IS ?
    ''', (chat_id, thread_id))
    return [row[0] for row in cur.fetchall()]

@_with_retry
def get_tasks_by_status(chat_id, thread_id, status):
    """
    Возвращает список message_id задач с определённым статусом.
    При ошибке — возвращает строку-код ошибки или пустой список.
    """
    db = get_db()
    cur = db.cursor()
    cur.execute('''
        SELECT message_id
          FROM tasks
         WHERE chat_id = ? AND thread_id IS ? AND status = ?
    ''', (chat_id, thread_id, status))
    return [row[0] for row in cur.fetchall()]

@_with_retry
def get_task_by_id(chat_id, thread_id, message_id):
    """
    Возвращает кортеж (author, text, status, accepted_by) для задачи.
    При ошибке — возвращает строку-код ошибки или None.
    """
    db = get_db()
    cur = db.cursor()
    cur.execute('''
        SELECT author, text, status, accepted_by
          FROM tasks
         WHERE chat_id = ? AND thread_id IS ? AND message_id = ?
    ''', (chat_id, thread_id, message_id))
    return cur.fetchone()

@_with_retry
def delete_task(chat_id, thread_id, message_id):
    """
    Удаляет задачу по chat_id, thread_id и message_id.
    """
    db_conn = get_db()
    db_conn.execute('''
        DELETE FROM tasks
         WHERE chat_id = ? AND thread_id IS ? AND message_id = ?
    ''', (chat_id, thread_id, message_id))
    db_conn.commit()
    return True