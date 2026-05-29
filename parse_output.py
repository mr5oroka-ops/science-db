import re
import psycopg2
import psycopg2.extras

DATABASE_URL = "postgresql://postgres:YCSCulfKQPFFuzkvmFxLkGaTmpGYgNNW@autorack.proxy.rlwy.net:41049/railway"

with open("drive_output.txt", "r", encoding="cp1251", errors="ignore") as f:
    content = f.read()

pattern = r'Processing file ([A-Za-z0-9_\-]+) (elibrary_\S+\.pdf)'
matches = re.findall(pattern, content)
print(f"Найдено файлов: {len(matches)}")

conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
cur = conn.cursor()

cur.execute("SELECT id, file_url FROM articles WHERE file_url IS NOT NULL AND file_url LIKE 'elibrary%.pdf'")
articles = cur.fetchall()
filename_to_article = {a['file_url']: a['id'] for a in articles}
print(f"Статей в БД: {len(filename_to_article)}")

updated = 0
not_found = 0

for file_id, filename in matches:
    if filename in filename_to_article:
        article_id = filename_to_article[filename]
        drive_url = f"https://drive.google.com/uc?export=download&id={file_id}"
        cur.execute("UPDATE articles SET file_url = %s WHERE id = %s", (drive_url, article_id))
        updated += 1
        print(f"  ✓ {filename}")
    else:
        not_found += 1

conn.commit()
cur.close()
conn.close()
print(f"\n✅ Обновлено: {updated}")
print(f"⚠️  Нет в БД: {not_found}")