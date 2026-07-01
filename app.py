"""
Эпатаж — мини-приложение лендинга.
Делает две вещи:
  1. Отдаёт статику (сам лендинг: index.html, index.html, favicon.svg).
  2. Принимает заявки с формы (POST /api/lead) и шлёт их на email через SMTP.

Без базы данных и без регистрации — заявки приходят на почту.
Настройки берутся из переменных окружения (файл .env).
"""

import os
import re
import ssl
import smtplib
import logging
from email.message import EmailMessage
from datetime import datetime, timezone, timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # читает .env рядом с app.py, если есть

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import HTTPException
from pydantic import BaseModel, field_validator

# --- настройки из окружения -------------------------------------------------

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.yandex.ru")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER = os.getenv("SMTP_USER", "")           # логин/ящик отправителя
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")   # пароль приложения (не основной!)
MAIL_FROM = os.getenv("MAIL_FROM", SMTP_USER)    # от кого письмо
MAIL_TO = os.getenv("MAIL_TO", SMTP_USER)        # кому приходят заявки

# через запятую можно указать несколько получателей
MAIL_TO_LIST = [a.strip() for a in MAIL_TO.split(",") if a.strip()]

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("epatazh-landing")

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

# --- простая защита от спама (память процесса, без БД) ----------------------

# не больше N заявок с одного IP за окно времени
RATE_LIMIT = int(os.getenv("RATE_LIMIT", "5"))
RATE_WINDOW_MIN = int(os.getenv("RATE_WINDOW_MIN", "10"))
_recent: dict[str, list[datetime]] = {}


def _too_many(ip: str) -> bool:
    now = datetime.now(timezone.utc)
    window = timedelta(minutes=RATE_WINDOW_MIN)
    hits = [t for t in _recent.get(ip, []) if now - t < window]
    hits.append(now)
    _recent[ip] = hits
    return len(hits) > RATE_LIMIT


# --- модель заявки ----------------------------------------------------------

ORDER_TYPES = {
    "Готовая модель из каталога",
    "Индивидуальный пошив",
    "Форма для команды / клуба",
    "Оптовый заказ",
    "Другое",
}


class Lead(BaseModel):
    name: str
    phone: str
    order_type: str
    comment: str = ""
    # honeypot: скрытое поле, которое заполняют только боты
    website: str = ""

    @field_validator("name", "phone")
    @classmethod
    def not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("пустое поле")
        if len(v) > 200:
            raise ValueError("слишком длинно")
        return v

    @field_validator("phone")
    @classmethod
    def valid_phone(cls, v: str) -> str:
        # считаем только цифры (пробелы, скобки, дефисы, + игнорируем)
        digits = re.sub(r"\D", "", v)
        if not (10 <= len(digits) <= 15):
            raise ValueError("некорректный номер телефона")
        return v.strip()

    @field_validator("comment")
    @classmethod
    def limit_comment(cls, v: str) -> str:
        return v.strip()[:2000]


# --- отправка письма --------------------------------------------------------

def send_email(lead: Lead) -> None:
    tz = timezone(timedelta(hours=3))  # МСК
    when = datetime.now(tz).strftime("%d.%m.%Y %H:%M")

    text = (
        f"Новая заявка с сайта «Эпатаж»\n"
        f"{'-' * 32}\n"
        f"Имя:         {lead.name}\n"
        f"Телефон:     {lead.phone}\n"
        f"Тип заказа:  {lead.order_type}\n"
        f"Комментарий: {lead.comment or '—'}\n"
        f"{'-' * 32}\n"
        f"Получено: {when} (МСК)\n"
    )

    msg = EmailMessage()
    msg["Subject"] = f"Новая заявка: {lead.name}, {lead.phone}"
    msg["From"] = f"Эпатаж — заявки <{MAIL_FROM}>"
    msg["To"] = ", ".join(MAIL_TO_LIST)
    msg["Reply-To"] = MAIL_FROM
    msg.set_content(text)  # кириллица уйдёт корректно (UTF-8)

    context = ssl.create_default_context()
    if SMTP_PORT == 465:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context) as s:
            s.login(SMTP_USER, SMTP_PASSWORD)
            s.send_message(msg)
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.starttls(context=context)
            s.login(SMTP_USER, SMTP_PASSWORD)
            s.send_message(msg)


# --- приложение -------------------------------------------------------------

app = FastAPI(title="Эпатаж — лендинг", docs_url=None, redoc_url=None)


@app.exception_handler(404)
async def not_found_handler(request: Request, exc: HTTPException):
    return FileResponse(STATIC_DIR / "404.html", status_code=404)


@app.post("/api/lead")
async def create_lead(lead: Lead, request: Request):
    # honeypot: если бот заполнил скрытое поле — делаем вид, что всё ок
    if lead.website:
        log.info("honeypot сработал, заявка отброшена")
        return JSONResponse({"ok": True})

    ip = request.client.host if request.client else "unknown"
    if _too_many(ip):
        log.warning("rate limit для %s", ip)
        return JSONResponse(
            {"ok": False, "error": "too_many"}, status_code=429
        )

    if lead.order_type not in ORDER_TYPES:
        return JSONResponse(
            {"ok": False, "error": "bad_type"}, status_code=422
        )

    try:
        send_email(lead)
    except Exception as e:  # noqa: BLE001
        log.exception("ошибка отправки письма: %s", e)
        return JSONResponse(
            {"ok": False, "error": "send_failed"}, status_code=502
        )

    log.info("заявка отправлена: %s, %s", lead.name, lead.phone)
    return JSONResponse({"ok": True})


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/robots.txt")
async def robots(request: Request) -> Response:
    base = str(request.base_url).rstrip("/")
    content = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /api/\n"
        f"\nSitemap: {base}/sitemap.xml\n"
    )
    return Response(content=content, media_type="text/plain")


@app.get("/sitemap.xml")
async def sitemap(request: Request) -> Response:
    base = str(request.base_url).rstrip("/")
    urls = [
        (f"{base}/", "1.0"),
        (f"{base}/privacy/", "0.3"),
    ]
    items = "\n".join(
        f"  <url><loc>{loc}</loc><priority>{pr}</priority></url>"
        for loc, pr in urls
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{items}\n"
        "</urlset>\n"
    )
    return Response(content=xml, media_type="application/xml")


# отдаём статику: главная — index.html, плюс index.html, favicon и т.д.
@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")