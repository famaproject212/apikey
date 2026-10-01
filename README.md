# Fama AI Gateway

Gateway API OpenAI-compatible yang membuat API key milik sendiri dengan prefix `ag-`.
Groq API key hanya berada di server sebagai environment variable.

## Penting

`fama/Fama2-12.9b` di proyek ini adalah **nama/alias API milik Fama**, bukan model
12.9B baru yang secara fisik dilatih dari beberapa model Groq. Backend inference
tetap memakai model Groq yang dikonfigurasi.

Mode:
- `auto`: pilih satu backend model.
- `single`: gunakan `FAMA_DEFAULT_MODEL`.
- `ensemble`: panggil sampai 3 backend lalu minta model synthesis menggabungkan hasil.

## Install

```bash
pip install -r requirements.txt
cp .env.example .env
nano .env
```

Isi `GROQ_API_KEY` dan `ADMIN_KEY`.

## Jalankan

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

Untuk internet publik, jalankan di VPS/cloud server atau gunakan tunnel HTTPS.
GitHub sendiri adalah tempat source code; GitHub bukan server API Python 24/7.

## Membuat API key

```bash
curl -X POST https://DOMAIN-KAMU/admin/keys   -H "X-Admin-Key: ADMIN_KEY_KAMU"
```

Hasil:

```json
{
  "api_key": "ag-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "model": "fama/Fama2-12.9b"
}
```

## Memakai Fama

```bash
curl https://DOMAIN-KAMU/v1/chat/completions   -H "Authorization: Bearer ag-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"   -H "Content-Type: application/json"   -d '{
    "model": "fama/Fama2-12.9b",
    "messages": [
      {"role": "user", "content": "Halo Fama"}
    ]
  }'
```

## Python client

```python
from openai import OpenAI

client = OpenAI(
    api_key="ag-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    base_url="https://DOMAIN-KAMU/v1"
)

r = client.chat.completions.create(
    model="fama/Fama2-12.9b",
    messages=[
        {"role": "user", "content": "Jelaskan Python"}
    ]
)

print(r.choices[0].message.content)
```
