"""
Скрипт для очистки предыдущей парсировки из базы данных
Удаляет все статьи, авторов и связанные данные, загруженные import_pdfs.py
Запуск: py clear_import.py
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

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# ── Подключение ───────────────────────────────────────────────
try:
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    cur = conn.cursor()
    print("✅ Подключение к БД успешно")
except Exception as e:
    print(f"❌ Ошибка подключения к БД: {e}")
    exit(1)

print("\n⚠️  ВНИМАНИЕ: Это действие удалит все данные из таблиц!")
print("Будут удалены:")
print("  - Все статьи")
print("  - Все авторы (кроме демо-данных)")
print("  - Все связи статей с авторами, ключевыми словами, областями")
print("  - Все AI-пересказы")

confirm = input("\nВы уверены? (yes/no): ")
if confirm.lower() != 'yes':
    print("❌ Отмена операции")
    exit(0)

try:
    # Удаляем AI-пересказы
    cur.execute("DELETE FROM summaries")
    summaries_deleted = cur.rowcount
    print(f"✓ Удалено пересказов: {summaries_deleted}")
    
    # Удаляем связи статей с ключевыми словами
    cur.execute("DELETE FROM article_keywords")
    article_keywords_deleted = cur.rowcount
    print(f"✓ Удалено связей статьи-ключевые слова: {article_keywords_deleted}")
    
    # Удаляем связи статей с предметными областями
    cur.execute("DELETE FROM article_areas")
    article_areas_deleted = cur.rowcount
    print(f"✓ Удалено связей статьи-области: {article_areas_deleted}")
    
    # Удаляем связи статей с авторами
    cur.execute("DELETE FROM article_authors")
    article_authors_deleted = cur.rowcount
    print(f"✓ Удалено связей статьи-авторы: {article_authors_deleted}")
    
    # Удаляем все статьи
    cur.execute("DELETE FROM articles")
    articles_deleted = cur.rowcount
    print(f"✓ Удалено статей: {articles_deleted}")
    
    # Удаляем авторов (кроме демо-данных из schema.sql)
    # Демо-авторы: id 1, 2, 3
    cur.execute("DELETE FROM authors WHERE id > 3")
    authors_deleted = cur.rowcount
    print(f"✓ Удалено авторов: {authors_deleted}")
    
    # Сбрасываем последовательности
    cur.execute("ALTER SEQUENCE articles_id_seq RESTART WITH 1")
    cur.execute("ALTER SEQUENCE authors_id_seq RESTART WITH 4")
    cur.execute("ALTER SEQUENCE summaries_id_seq RESTART WITH 1")
    
    conn.commit()
    
    print("\n" + "="*50)
    print("✅ Очистка базы данных завершена успешно")
    print("="*50)
    
except Exception as e:
    conn.rollback()
    print(f"\n❌ Ошибка при очистке: {e}")
    exit(1)

cur.close()
conn.close()
