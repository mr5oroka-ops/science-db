"""
Удаление статей с кракозябрами по DOI паттернам
Удаляет статьи из выпусков с повреждёнными PDF файлами
"""

import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

DATABASE_URL = os.getenv('DATABASE_URL')

if DATABASE_URL:
    conn_str = DATABASE_URL
else:
    DB_HOST = os.getenv('DB_HOST', 'localhost')
    DB_PORT = os.getenv('DB_PORT', '5432')
    DB_NAME = os.getenv('DB_NAME', 'science_db')
    DB_USER = os.getenv('DB_USER', 'postgres')
    DB_PASSWORD = os.getenv('DB_PASSWORD', '')
    conn_str = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# Паттерны DOI для удаления (выпуски с кракозябрами)
doi_patterns = [
    r'10\.36622/VSTU\.2022\.25\.4\.',  # 2022, выпуск 4
    r'10\.36622/VSTU\.2023\.26\.',     # 2023, выпуск 1-3
    r'10\.36622/VSTU\.2023\.4\.26\.',  # 2023, выпуск 4
]

# ── Подключение ───────────────────────────────────────────────
try:
    conn = psycopg2.connect(conn_str, cursor_factory=psycopg2.extras.RealDictCursor)
    cur = conn.cursor()
    print(f"✅ Подключение к БД успешно")
    print(f"📍 Строка подключения: {conn_str[:50]}...")
except Exception as e:
    print(f"❌ Ошибка подключения к БД: {e}")
    exit(1)

# ── Находим статьи для удаления ───────────────────────────────
import re

cur.execute("SELECT id, title, doi FROM articles")
articles = cur.fetchall()

articles_to_delete = []
for article in articles:
    if article['doi']:
        for pattern in doi_patterns:
            if re.search(pattern, article['doi']):
                articles_to_delete.append(article)
                break

print(f"📊 Всего статей в БД: {len(articles)}")
print(f"🗑️  Статей для удаления: {len(articles_to_delete)}")

if len(articles_to_delete) > 0:
    print("\nСтатьи для удаления:")
    for article in articles_to_delete[:10]:
        print(f"  - ID: {article['id']}, Название: {article['title'][:50]}..., DOI: {article['doi']}")
    if len(articles_to_delete) > 10:
        print(f"  ... и ещё {len(articles_to_delete) - 10}")

    confirm = input("\nУдалить эти статьи? (yes/no): ")
    if confirm.lower() == 'yes':
        # Удаляем связи с авторами
        author_ids = [a['id'] for a in articles_to_delete]
        cur.execute("DELETE FROM article_authors WHERE article_id = ANY(%s)", (author_ids,))
        deleted_authors = cur.rowcount

        # Удаляем связи с ключевыми словами
        cur.execute("DELETE FROM article_keywords WHERE article_id = ANY(%s)", (author_ids,))
        deleted_keywords = cur.rowcount

        # Удаляем связи с областями
        cur.execute("DELETE FROM article_areas WHERE article_id = ANY(%s)", (author_ids,))
        deleted_areas = cur.rowcount

        # Удаляем пересказы
        cur.execute("DELETE FROM summaries WHERE article_id = ANY(%s)", (author_ids,))
        deleted_summaries = cur.rowcount

        # Удаляем статьи
        cur.execute("DELETE FROM articles WHERE id = ANY(%s)", (author_ids,))
        deleted_articles = cur.rowcount

        conn.commit()

        print(f"\n✅ Удалено:")
        print(f"  - Статей: {deleted_articles}")
        print(f"  - Связей с авторами: {deleted_authors}")
        print(f"  - Связей с ключевыми словами: {deleted_keywords}")
        print(f"  - Связей с областями: {deleted_areas}")
        print(f"  - Пересказов: {deleted_summaries}")
    else:
        print("❌ Удаление отменено")
else:
    print("✅ Нет статей для удаления")

cur.close()
conn.close()
