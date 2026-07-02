# Эпатаж — лендинг

Мини-приложение лендинга магазина «Эпатаж». Отдаёт статичную страницу
и принимает заявки с формы, отправляя их на email через SMTP.

Без базы данных и без регистрации — заявки приходят на почту.

## Что внутри

```
epatazh-landing/
  app.py             # FastAPI: приём заявки + отдача статики
  requirements.txt   # зависимости
  .env.example       # шаблон настроек (скопировать в .env)
  static/
    index.html       # лендинг
    privacy.html     # политика конфиденциальности
    favicon.svg      # иконка сайта
```

## Запуск локально

1. Создай и активируй виртуальное окружение:
   ```
   python -m venv venv
   source venv/bin/activate        # Windows: venv\Scripts\activate
   ```

2. Поставь зависимости:
   ```
   pip install -r requirements.txt
   ```

3. Скопируй настройки и впиши свои:
   ```
   cp .env.example .env
   ```
   Открой `.env` и заполни SMTP (ящик Яндекса и **пароль приложения** —
   не основной пароль! Создаётся в Яндекс ID → Безопасность → Пароли приложений).

4. Запусти:
   ```
   uvicorn app:app --reload
   ```

5. Открой http://127.0.0.1:8000 — увидишь лендинг. Заполни форму,
   проверь, что письмо пришло на почту из `MAIL_TO`.

## Проверка без отправки почты

Если SMTP ещё не настроен, заявка вернёт ошибку отправки — это нормально.
Сам сайт и форма работают; письмо уйдёт, когда заполнишь `.env`.

## Деплой на сервер (коротко)

На сервере (Ubuntu) понадобится Python, плюс веб-сервер nginx как
обратный прокси и HTTPS через certbot. Общая схema:

1. Скопировать проект на сервер, поставить зависимости в venv.
2. Создать `.env` с боевыми SMTP-настройками.
3. Запустить uvicorn как сервис (systemd), например на порту 8001.
4. nginx проксирует домен (epatazh.ru) на этот порт.
5. certbot выдаёт HTTPS-сертификат.

### Пример конфига nginx

```nginx
server {
    listen 443 ssl;
    server_name epatazh.ru;

    # SSL — certbot пропишет эти строки сам
    # ssl_certificate     /etc/letsencrypt/live/epatazh.ru/fullchain.pem;
    # ssl_certificate_key /etc/letsencrypt/live/epatazh.ru/privkey.pem;

    # --- Заголовки безопасности ---
    # HSTS включай только когда HTTPS уже работает (после certbot)!
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains" always;
    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Content-Security-Policy "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; frame-ancestors 'none'" always;

    location / {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        # Нужно, чтобы приложение видело настоящий IP клиента (rate-limit заявок)
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

После правки конфига проверь синтаксис и перезапусти nginx:

```bash
sudo nginx -t && sudo systemctl reload nginx
```

## Эндпоинты

- `GET /` — лендинг.
- `GET /privacy.html` — политика.
- `POST /api/lead` — приём заявки (JSON: name, phone, order_type, comment).
- `GET /health` — проверка живости (отдаёт `{"status":"ok"}`).

## Защита от спама

- **Honeypot**: скрытое поле `website` — если заполнено (бот), заявка молча отбрасывается.
- **Rate-limit**: не больше `RATE_LIMIT` заявок с одного IP за `RATE_WINDOW_MIN` минут.
