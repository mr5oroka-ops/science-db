"""
Скрипт для удаления статей, которых нет в папке library
Удаляет статьи, у которых нет соответствующего PDF-файла в локальной папке library
Запуск: py clear_orphan_articles.py
"""

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
import os

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

# ── Папка с PDF ───────────────────────────────────────────────
LIBRARY_DIR = os.path.join(os.path.dirname(__file__), 'library')

# ── Подключение ───────────────────────────────────────────────
try:
    conn = psycopg2.connect(conn_str, cursor_factory=psycopg2.extras.RealDictCursor)
    cur = conn.cursor()
    print("✅ Подключение к БД успешно")
except Exception as e:
    print(f"❌ Ошибка подключения к БД: {e}")
    exit(1)

# ── Получаем список всех PDF-файлов в library ─────────────────
pdf_files = set()
for year_folder in os.listdir(LIBRARY_DIR):
    year_path = os.path.join(LIBRARY_DIR, year_folder)
    if os.path.isdir(year_path):
        for pdf_file in os.listdir(year_path):
            if pdf_file.endswith('.pdf'):
                pdf_files.add(pdf_file)

print(f"📁 Найдено PDF-файлов в library: {len(pdf_files)}")

# ── Получаем все статьи из БД ───────────────────────────────────
cur.execute("SELECT id, file_url, title FROM articles")
articles = cur.fetchall()
print(f"📊 Всего статей в БД: {len(articles)}")

# ── Находим статьи, которых нет в library ─────────────────────
orphan_articles = []
for article in articles:
    file_url = article['file_url']
    if file_url and file_url not in pdf_files:
        orphan_articles.append(article)

print(f"\n🗑️  Статей для удаления (нет в library): {len(orphan_articles)}")

if orphan_articles:
    print("\nСтатьи для удаления:")
    for article in orphan_articles[:10]:  # Показываем первые 10
        print(f"  - ID: {article['id']}, Файл: {article['file_url']}, Заголовок: {article['title'][:50]}...")
    if len(orphan_articles) > 10:
        print(f"  ... и ещё {len(orphan_articles) - 10}")
    
    confirm = input("\nУдалить эти статьи? (yes/no): ")
    if confirm.lower() != 'yes':
        print("❌ Отмена операции")
        exit(0)
    
    try:
        # Удаляем связи
        article_ids = [a['id'] for a in orphan_articles]
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
    print("✅ Все статьи в БД имеют соответствующие PDF-файлы")

cur.close()
conn.close()
