"""
Скрипт для загрузки PDF файлов в Railway Bucket
"""
import os
import boto3
from pathlib import Path

# Переменные окружения для Railway Bucket
BUCKET_ENDPOINT_URL = os.getenv("BUCKET_ENDPOINT_URL")
BUCKET_ACCESS_KEY_ID = os.getenv("BUCKET_ACCESS_KEY_ID")
BUCKET_SECRET_ACCESS_KEY = os.getenv("BUCKET_SECRET_ACCESS_KEY")
BUCKET_NAME = os.getenv("BUCKET_NAME", "railway")
BUCKET_REGION = os.getenv("BUCKET_REGION", "us-east-1")

# Папка с PDF файлами
LIBRARY_PATH = "library"

def upload_to_bucket(file_path):
    """Загрузить один PDF файл в Bucket"""
    filename = os.path.basename(file_path)
    object_key = f"library/{filename}"
    
    try:
        # Создаем S3 клиент
        s3 = boto3.client(
            's3',
            endpoint_url=BUCKET_ENDPOINT_URL,
            aws_access_key_id=BUCKET_ACCESS_KEY_ID,
            aws_secret_access_key=BUCKET_SECRET_ACCESS_KEY,
            region_name=BUCKET_REGION
        )
        
        # Загружаем файл
        s3.upload_file(file_path, BUCKET_NAME, object_key)
        print(f"✓ {filename} - загружен")
        return True
    except Exception as e:
        print(f"✗ {filename} - ошибка: {str(e)}")
        return False

def main():
    """Загрузить все PDF файлы в Bucket"""
    # Проверяем переменные окружения
    if not BUCKET_ENDPOINT_URL or not BUCKET_ACCESS_KEY_ID:
        print("Ошибка: Не установлены переменные окружения BUCKET_ENDPOINT_URL или BUCKET_ACCESS_KEY_ID")
        print("Получи их из Railway dashboard и установи как переменные окружения")
        return
    
    # Находим все PDF файлы
    pdf_files = []
    for root, dirs, files in os.walk(LIBRARY_PATH):
        for file in files:
            if file.endswith('.pdf'):
                pdf_files.append(os.path.join(root, file))
    
    print(f"Найдено {len(pdf_files)} PDF файлов")
    print(f"Bucket: {BUCKET_NAME}")
    print(f"Endpoint: {BUCKET_ENDPOINT_URL}")
    print(f"Начинаю загрузку...")
    
    success_count = 0
    for i, file_path in enumerate(pdf_files, 1):
        print(f"[{i}/{len(pdf_files)}] ", end="")
        if upload_to_bucket(file_path):
            success_count += 1
    
    print(f"\nЗагружено: {success_count}/{len(pdf_files)} файлов")

if __name__ == "__main__":
    main()
