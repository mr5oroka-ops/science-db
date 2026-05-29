"""
Скрипт для загрузки PDF файлов в Railway Bucket через requests (без boto3)
"""
import os
import requests
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
    """Загрузить один PDF файл в Bucket через requests"""
    filename = os.path.basename(file_path)
    object_key = f"library/{filename}"
    
    try:
        # Формируем URL для S3 объекта
        endpoint = BUCKET_ENDPOINT_URL.rstrip('/')
        url = f"{endpoint}/{BUCKET_NAME}/{object_key}"
        
        # Читаем файл
        with open(file_path, 'rb') as f:
            file_data = f.read()
        
        # Загружаем файл через PUT запрос
        headers = {
            "Content-Type": "application/pdf",
            "Authorization": f"AWS4-HMAC-SHA256 Credential={BUCKET_ACCESS_KEY_ID}/{BUCKET_REGION}/s3/aws4_request"
        }
        
        response = requests.put(url, data=file_data, headers=headers, timeout=30)
        
        if response.status_code in [200, 201]:
            print(f"✓ {filename} - загружен")
            return True
        else:
            print(f"✗ {filename} - ошибка: {response.status_code} - {response.text}")
            return False
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
