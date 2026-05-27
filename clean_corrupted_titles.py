"""
Скрипт для очистки статей с некорректными названиями (кракозябры)
Удаляет статьи, в названиях которых много спецсимволов
Запуск: py clean_corrupted_titles.py
"""

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
import os
import re

# Загружаем переменные окружения
load_dotenv()

# ── Настройки подключения к БД ──────────────────────────────────
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = os.getenv('DB_PORT', '5432')
DB_NAME = os.getenv('DB_NAME', 'science_db')
DB_USER = os.getenv('DB_USER', 'postgres')
DB_PASSWORD = os.getenv('DB_PASSWORD', '')
DATABASE_URL = os.getenv('DATABASE_URL')

if DATABASE_URL:
    conn_str = DATABASE_URL
else:
    conn_str = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# ── Подключение ───────────────────────────────────────────────
try:
    conn = psycopg2.connect(conn_str, cursor_factory=psycopg2.extras.RealDictCursor)
    cur = conn.cursor()
    print(f"✅ Подключение к БД успешно")
    print(f"📍 Строка подключения: {conn_str[:50]}...")
except Exception as e:
    print(f"❌ Ошибка подключения к БД: {e}")
    exit(1)

# ── Функция проверки корректности текста ───────────────────────
def is_corrupted_text(text):
    """Проверяет, содержит ли текст много некорректных символов"""
    if not text:
        return True
    
    # Считаем количество символов с кодом > 127 (не ASCII)
    non_ascii = sum(1 for c in text if ord(c) > 127)
    total = len(text)
    
    # Если более 50% символов не ASCII и текст короткий - считаем поврежденным
    if total > 0 and non_ascii / total > 0.5 and total < 50:
        return True
    
    # Проверяем на наличие специфических кракозябр - более агрессивные паттерны
    corrupted_patterns = [
        r'[ɂɇФɈȺЦȻЕɁɉ]+',  # специфические кракозябры из elibrary
        r'[GS;6<@BEF9=]+',  # специфические кракозябры из elibrary
        r'[@4ELF45<DB64A]+',  # специфические кракозябры из elibrary
        r'[ɂɇ$Ɉ]+',  # специфические кракозябры из elibrary
        r'[ɂ!Ф\"$]+',  # специфические кракозябры из elibrary
        r'[ɂ!(\"$]+',  # специфические кракозябры из elibrary
        r'[ȺȿɁ\"#Ⱥ%!]+',  # специфические кракозябры из elibrary
        r'[ȼO\?\.]+',  # специфические кракозябры из elibrary
    ]
    
    for pattern in corrupted_patterns:
        if re.search(pattern, text):
            return True
    
    # Проверяем на отсутствие нормальных слов (менее 3 последовательных букв)
    words = re.findall(r'[А-Яа-яЁёA-Za-z]{3,}', text)
    if len(words) < 2 and total > 10:  # если меньше 2 нормальных слов и текст не короткий
        return True
    
    return False

# ── Получаем все статьи ───────────────────────────────────────
cur.execute("SELECT id, title, file_url FROM articles")
articles = cur.fetchall()
print(f"📊 Всего статей в БД: {len(articles)}")

# ── Находим статьи с некорректными названиями ─────────────────
corrupted_articles = []
for article in articles:
    if is_corrupted_text(article['title']):
        corrupted_articles.append(article)

print(f"\n🗑️  Статей с некорректными названиями: {len(corrupted_articles)}")

if corrupted_articles:
    print("\nСтатьи для удаления:")
    for article in corrupted_articles[:10]:
        print(f"  - ID: {article['id']}, Название: {article['title'][:50]}..., Файл: {article['file_url']}")
    if len(corrupted_articles) > 10:
        print(f"  ... и ещё {len(corrupted_articles) - 10}")
    
    confirm = input("\nУдалить эти статьи? (yes/no): ")
    if confirm.lower() != 'yes':
        print("❌ Отмена операции")
        exit(0)
    
    try:
        # Удаляем связи
        article_ids = [a['id'] for a in corrupted_articles]
        cur.execute(
            "DELETE FROM article_authors WHERE article_id = ANY(%s)",
            (article_ids,)
        )
        deleted_authors = cur.rowcount
        
        cur.execute(
            "DELETE FROM article_keywords WHERE article_id = ANY(%s)",
            (article_ids,)
        )
        deleted_keywords = cur.rowcount
        
        cur.execute(
            "DELETE FROM article_areas WHERE article_id = ANY(%s)",
            (article_ids,)
        )
        deleted_areas = cur.rowcount
        
        cur.execute(
            "DELETE FROM summaries WHERE article_id = ANY(%s)",
            (article_ids,)
        )
        deleted_summaries = cur.rowcount
        
        # Удаляем сами статьи
        cur.execute(
            "DELETE FROM articles WHERE id = ANY(%s)",
            (article_ids,)
        )
        deleted_articles = cur.rowcount
        
        conn.commit()
        
        print(f"\n✅ Удалено:")
        print(f"  - Статей: {deleted_articles}")
        print(f"  - Связей с авторами: {deleted_authors}")
        print(f"  - Связей с ключевыми словами: {deleted_keywords}")
        print(f"  - Связей с областями: {deleted_areas}")
        print(f"  - Пересказов: {deleted_summaries}")
        
    except Exception as e:
        conn.rollback()
        print(f"\n❌ Ошибка при удалении: {e}")
        exit(1)
else:
    print("✅ Все статьи имеют корректные названия")

cur.close()
conn.close()
