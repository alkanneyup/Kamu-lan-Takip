import requests

URL = "https://kariyerkapisi.gov.tr/"

response = requests.get(URL, timeout=30)

print("HTTP DURUMU:", response.status_code)
print("SAYFA UZUNLUĞU:", len(response.text))
print("BAĞLANTI BAŞARILI")
