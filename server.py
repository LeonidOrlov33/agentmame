#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Диплом-Чек AI — сервер проверки диплома нейросетью Groq.

Что делает:
  * принимает файл (.docx / .pdf / .txt / .md / .rtf) или вставленный текст;
  * вытаскивает текст (без внешних зависимостей для .docx и .txt);
  * отправляет текст в Groq (llama-3.3-70b-versatile по умолчанию) и получает
    список ошибок (severity=error) и недочётов (severity=warning);
  * находит точные позиции каждой находки в тексте и отдаёт их клиенту,
    чтобы тот подсветил красным / жёлтым и показал выноски при наведении;
  * если ключа Groq нет — работает локальный нормоконтроль (эвристики),
    так что интерфейс можно посмотреть и без ключа.

Запуск:
    python server.py                 # http://127.0.0.1:8765
    python server.py --port 9000
    python server.py --key gsk_...   # или переменная окружения GROQ_API_KEY
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import sys
import threading
import time
import uuid
import zipfile
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from xml.etree import ElementTree as ET
from urllib import request as urlreq
from urllib.error import HTTPError, URLError

# --------------------------------------------------------------------------
# Настройки
# --------------------------------------------------------------------------

HERE = os.path.dirname(os.path.abspath(__file__))
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

DEFAULT_MODEL = "llama-3.3-70b-versatile"
MODELS = [
    {"id": "llama-3.3-70b-versatile", "label": "Llama 3.3 70B — умная (рекомендуется)"},
    {"id": "llama-3.1-8b-instant", "label": "Llama 3.1 8B — самая быстрая"},
    {"id": "openai/gpt-oss-120b", "label": "GPT-OSS 120B — сильная логика"},
    {"id": "openai/gpt-oss-20b", "label": "GPT-OSS 20B — быстрая"},
    {"id": "qwen/qwen3-32b", "label": "Qwen3 32B — хорошо с русским"},
]

MAX_UPLOAD = 30 * 1024 * 1024      # 30 МБ
CHUNK_CHARS = 6000                 # сколько символов отдаём модели за один запрос
MAX_CHUNKS = 8                     # больше не проверяем (документ огромный)
PARA_CHARS_PER_PAGE = 1500         # сколько символов на «страницу» документа

CATEGORIES = [
    "Орфография", "Пунктуация", "Грамматика", "Стиль",
    "Структура", "Оформление", "Повторы", "Факты", "Логика", "Экономика",
]

KIND_TITLES = {
    "typo": "Опечатка",
    "error": "Ошибка",
    "flaw": "Недочёт",
}

KIND_WEIGHT = {"typo": 1, "error": 3, "flaw": 2}


def mark_for_score(score):
    """Переводит 100-балльный балл в академическую отметку."""
    if score >= 90:
        return "5 (отлично)"
    if score >= 75:
        return "4 (хорошо)"
    if score >= 60:
        return "3 (удовлетворительно)"
    if score >= 40:
        return "2 (неудовлетворительно)"
    return "1 (работа не готова)"


# --------------------------------------------------------------------------
# Извлечение текста
# --------------------------------------------------------------------------

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _decode_bytes(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1251", "koi8-r", "cp866", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


def _docx_paragraphs(data: bytes):
    """Возвращает [(text, kind)] из word/document.xml без python-docx."""
    out = []
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = [n for n in zf.namelist() if n.endswith("document.xml")]
        if not names:
            raise ValueError("В DOCX не найден word/document.xml")
        xml = zf.read(names[0])
    root = ET.fromstring(xml)

    for p in root.iter(W_NS + "p"):
        buf = []
        for node in p.iter():
            tag = node.tag
            if tag == W_NS + "t":
                if node.text:
                    buf.append(node.text)
            elif tag == W_NS + "tab":
                buf.append(" ")
            elif tag in (W_NS + "br", W_NS + "cr"):
                buf.append(" ")
        text = re.sub(r"[ \t]+", " ", "".join(buf)).strip()
        if not text:
            continue

        kind = "p"
        ppr = p.find(W_NS + "pPr")
        if ppr is not None:
            style = ppr.find(W_NS + "pStyle")
            if style is not None:
                val = (style.get(W_NS + "val") or "").lower()
                if "heading1" in val or val in ("1", "title", "заголовок1"):
                    kind = "h1"
                elif "heading2" in val or val == "2":
                    kind = "h2"
                elif "heading" in val or "заголовок" in val:
                    kind = "h3"
                elif "title" in val:
                    kind = "h1"
            if ppr.find(W_NS + "numPr") is not None:
                kind = "li"
            lvl = ppr.find(W_NS + "outlineLvl")
            if lvl is not None:
                try:
                    n = int(lvl.get(W_NS + "val") or "0")
                except ValueError:
                    n = 0
                kind = "h1" if n == 0 else ("h2" if n == 1 else "h3")
        out.append((text, kind))
    return out


def _pdf_text_pypdf(data: bytes) -> str:
    from pypdf import PdfReader  # необязательная зависимость

    reader = PdfReader(io.BytesIO(data))
    parts = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            parts.append("")
    return "\n\n".join(parts)


def _pdf_text_crude(data: bytes) -> str:
    """Очень простой распаковщик PDF (без библиотек). Кириллицу может не взять."""
    chunks = []
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", data, re.S):
        raw = m.group(1)
        try:
            raw = zlib.decompress(raw)
        except zlib.error:
            pass
        if b"Tj" not in raw and b"TJ" not in raw:
            continue
        for tm in re.finditer(rb"\((?:\\.|[^\\()])*\)", raw):
            s = tm.group(0)[1:-1]
            s = s.replace(b"\\(", b"(").replace(b"\\)", b")").replace(b"\\\\", b"\\")
            chunks.append(_decode_bytes(s))
        chunks.append("\n")
    return " ".join(chunks)


def _guess_kind(line: str) -> str:
    t = line.strip()
    if not t:
        return "p"
    if len(t) <= 90 and re.match(r"^(глава|часть|раздел)\s", t, re.I):
        return "h1"
    if len(t) <= 120 and re.match(r"^\d+(\.\d+)*\.?\s+\S", t) and t.count(" ") <= 12:
        return "h2"
    if len(t) <= 70 and t == t.upper() and re.search(r"[А-ЯЁ]{4}", t):
        return "h1"
    if re.match(r"^[-–—•·]\s+", t):
        return "li"
    if re.match(r"^\d+[.)]\s+", t) and len(t) < 200:
        return "li"
    return "p"


def extract_paragraphs(filename: str, data: bytes):
    name = (filename or "").lower()

    if name.endswith(".docx") or name.endswith(".docm"):
        return _docx_paragraphs(data)

    if name.endswith(".pdf") or data[:5] == b"%PDF-":
        text = ""
        try:
            text = _pdf_text_pypdf(data)
        except Exception:
            text = ""
        if len(re.findall(r"[А-Яа-яЁё]", text)) < 40:
            crude = _pdf_text_crude(data)
            if len(re.findall(r"[А-Яа-яЁё]", crude)) > len(re.findall(r"[А-Яа-яЁё]", text)):
                text = crude
        if len(re.findall(r"[А-Яа-яЁё]", text)) < 40:
            raise ValueError(
                "Не удалось прочитать текст из PDF. Установите библиотеку: "
                "pip install pypdf  — либо сохраните диплом как .docx / .txt."
            )
        return [(ln.strip(), _guess_kind(ln)) for ln in text.split("\n") if ln.strip()]

    if name.endswith(".rtf"):
        text = _decode_bytes(data)
        text = re.sub(r"\\'([0-9a-fA-F]{2})", lambda m: bytes([int(m.group(1), 16)]).decode("cp1251", "ignore"), text)
        text = re.sub(r"\\[a-zA-Z]+-?\d* ?", "", text)
        text = text.replace("{", "").replace("}", "")
        return [(ln.strip(), _guess_kind(ln)) for ln in re.split(r"\\par|[\r\n]+", text) if ln.strip()]

    # txt / md / csv / всё остальное
    text = _decode_bytes(data).replace("\r\n", "\n").replace("\r", "\n")
    out = []
    for line in text.split("\n"):
        s = line.strip()
        if not s:
            continue
        s = re.sub(r"[ \t]+", " ", s)
        out.append((s, _guess_kind(s)))
    return out


def normalize_paragraphs(raw):
    """Убирает мусор, склеивает разорванные строки, ставит id."""
    merged = []
    for text, kind in raw:
        text = text.strip()
        if not text:
            continue
        # одни цифры (номер страницы) — выкидываем
        if re.fullmatch(r"[\d\s\W]{1,6}", text) and not re.search(r"[А-Яа-яA-Za-z]", text):
            continue
        if len(text) < 3 and kind == "p":
            continue
        if (
            merged
            and kind == "p"
            and merged[-1][1] == "p"
            and len(merged[-1][0]) < 60
            and not re.search(r"[.!?:;]$", merged[-1][0])
            and text[:1].islower()
        ):
            merged[-1] = (merged[-1][0] + " " + text, "p")
            continue
        merged.append((text, kind))

    paras = []
    for i, (text, kind) in enumerate(merged, start=1):
        paras.append({"id": i, "text": text, "kind": kind})
    return paras


def make_pages(paras):
    pages, cur, size = [], [], 0
    for p in paras:
        L = len(p["text"])
        if cur and size + L > PARA_CHARS_PER_PAGE:
            pages.append(cur)
            cur, size = [], 0
        cur.append(p["id"])
        size += L
    if cur:
        pages.append(cur)
    return pages or [[]]


# --------------------------------------------------------------------------
# Поиск позиции цитаты в тексте
# --------------------------------------------------------------------------

def find_span(text: str, quote: str):
    """Возвращает (start, end) фрагмента quote внутри text или None."""
    if not text or not quote:
        return None
    q = quote.strip()
    q = q.strip("«»\"'`""„").strip()
    q = re.sub(r"\s+", " ", q)
    if len(q) < 2:
        return None

    i = text.find(q)
    if i >= 0:
        return (i, i + len(q))

    low, qlow = text.lower(), q.lower()
    i = low.find(qlow)
    if i >= 0:
        return (i, i + len(q))

    # пробуем по частям: самое длинное слово
    toks = [t for t in re.findall(r"[\w\-]{4,}", q, re.UNICODE)]
    for tok in sorted(set(toks), key=len, reverse=True)[:3]:
        j = low.find(tok.lower())
        if j >= 0:
            s = j
            e = j + len(tok)
            # расширяем до границ слова
            while s > 0 and re.match(r"\w", text[s - 1]):
                s -= 1
            while e < len(text) and re.match(r"\w", text[e]):
                e += 1
            return (s, e)
    return None


def clamp_span(span, text_len):
    if not span:
        return None
    s, e = span
    s = max(0, min(s, text_len))
    e = max(s, min(e, text_len))
    if e - s < 2:
        return None
    return (s, e)


# --------------------------------------------------------------------------
# Локальный нормоконтроль (работает без ключа Groq)
# --------------------------------------------------------------------------

RULES = [
    # (regex, severity, category, title, explanation, suggestion)
    (r"\s{2,}", "warning", "Оформление", "Двойной пробел",
     "В тексте два и более пробела подряд — типографская небрежность.",
     "Оставьте один пробел."),
    (r"\s+[,.;:!?]", "error", "Пунктуация", "Пробел перед знаком препинания",
     "По правилам русской типографики знак препинания ставится сразу после слова, без пробела.",
     "Уберите пробел перед знаком."),
    (r"[,;:][А-Яа-яЁёA-Za-z]", "error", "Пунктуация", "Нет пробела после знака препинания",
     "После запятой, точки с запятой или двоеточия нужен пробел.",
     "Поставьте пробел после знака."),
    (r"\.(?=[А-ЯЁ])", "error", "Пунктуация", "Нет пробела после точки",
     "Точка завершает предложение, следующее слово пишется через пробел.",
     "Поставьте пробел после точки."),
    (r"\b(\w{3,})\s+\1\b", "error", "Повторы", "Повтор слова",
     "Слово повторено дважды подряд — вероятная опечатка при наборе.",
     "Удалите лишнее слово."),
    (r"\.{2,}|!{2,}|\?{2,}", "error", "Пунктуация", "Двойной знак",
     "Два и более одинаковых знака препинания подряд в научном тексте недопустимы.",
     "Оставьте один знак (или многоточие как единый символ)."),
    (r"\s-\s", "warning", "Оформление", "Дефис вместо тире",
     "В роли тире между частями предложения используется длинное тире «—», а не дефис.",
     "Замените « - » на « — »."),
    (r"\bв течении\b", "error", "Грамматика", "«в течении» или «в течение»",
     "Если речь о времени («в течение трёх месяцев») — пишется «в течение» с «е» на конце.",
     "Исправьте на «в течение»."),
    (r"\bв виду\b", "error", "Грамматика", "«в виду» или «ввиду»",
     "Предлог причины пишется слитно: «ввиду». Раздельно — только «иметь в виду».",
     "Исправьте на «ввиду» (или «иметь в виду»)."),
    (r"\bне смотря на\b", "error", "Грамматика", "«не смотря на» или «несмотря на»",
     "Уступительный предлог пишется слитно: «несмотря на».",
     "Исправьте на «несмотря на»."),
    (r"\bчто-бы\b|\bчто бы\b(?=\s+(сделать|показать|проверить))", "error", "Грамматика", "«что бы» или «чтобы»",
     "Союз цели пишется слитно: «чтобы».",
     "Исправьте на «чтобы»."),
    (r"\bтак-же\b|\bто-же\b", "error", "Орфография", "Лишний дефис",
     "Союзы «также», «тоже» пишутся слитно, без дефиса.",
     "Уберите дефис."),
    (r"\bв-общем\b|\bвпринципе\b|\bпо-этому\b", "error", "Орфография", "Ошибка в написании наречия",
     "«В общем» пишется раздельно, «в принципе» — раздельно, «поэтому» — слитно.",
     "Исправьте написание."),
    (r"\bт\.\s?д\.?(?!\s)", "warning", "Оформление", "Сокращение «т. д.»",
     "Сокращения «т. д.», «т. п.», «т. е.» пишутся с пробелами.",
     "Пишите «т. д.» с пробелами."),
    (r"\d(?=[А-Яа-яЁё])", "error", "Оформление", "Нет пробела между числом и словом",
     "Число и следующее за ним слово разделяются пробелом (исключение — «5-й»).",
     "Поставьте пробел."),
    (r"[А-Яа-яЁё][A-Za-z]|[A-Za-z][А-Яа-яЁё]", "warning", "Орфография", "Смешение алфавитов",
     "В одном слове смешаны кириллица и латиница — так бывает при копировании или опечатке.",
     "Наберите слово в одном алфавите."),
    (r"\bявляется\b", "warning", "Стиль", "Канцелярит: «является»",
     "Конструкция «является» — тяжёлый канцелярит, типичный недочёт научного текста.",
     "Замените на «—», «представляет собой», «служит»."),
    (r"\bв данной работе\b|\bв настоящей работе\b|\bна сегодняшний день\b", "warning", "Стиль", "Речевой штамп",
     "Шаблонная фраза, которой лучше избегать в ВКР.",
     "Переформулируйте конкретнее."),
    (r"\bстоит отметить\b|\bнеобходимо отметить\b|\bследует отметить\b", "warning", "Стиль", "Вводная конструкция-клише",
     "Частые вводные обороты утяжеляют текст.",
     "Скажите мысль прямо, без «стоит отметить»."),
    (r"\bочень\b|\bмного\b(?=\s+\w+ов)", "warning", "Стиль", "Разговорная лексика",
     "В научном тексте избегают оценочных и разговорных слов.",
     "Замените на нейтральное или количественное выражение."),
]


# --------------------------------------------------------------------------
# Профиль «Экономика»: ВКР по экономике, финансам, учёту, менеджменту
# --------------------------------------------------------------------------

PROFILES = [
    {"id": "economy", "label": "Экономика (ВКР по экономике и финансам)"},
    {"id": "universal", "label": "Универсальный (любая специальность)"},
]

DEFAULT_PROFILE = "economy"

# Правила, специфичные для экономических текстов: единицы измерения,
# экономическая терминология, типичные тавтологии и канцелярит.
ECONOMY_RULES = [
    # (regex, severity, category, title, explanation, suggestion)
    (r"\d(?=(?:руб|тыс|млн|млрд|шт|чел|га|кг|км|тонн))", "error", "Оформление",
     "Нет пробела между числом и единицей измерения",
     "По ГОСТ 8.417 между числом и обозначением единицы ставится пробел: «150 руб.», «12 тыс. чел.». Слитное написание — грубая ошибка в экономической ВКР.",
     "Поставьте пробел: «150 руб.»."),
    (r"\b(?:тыс|млн|млрд)\.(?:руб|чел|т|шт)", "warning", "Оформление",
     "Слитное сокращение «тыс.руб.»",
     "Сокращения пишутся с пробелом: «тыс. руб.», «млн руб.», «млрд руб.».",
     "Поставьте пробел после сокращения."),
    (r"(?<!\d)%\s*\d", "error", "Оформление",
     "Знак «%» стоит перед числом",
     "Знак процента ставится после числа: «5 %», а не «%5».",
     "Переставьте: «5 %»."),
    (r"\d+\.\d+(?=\s*(?:%|руб|тыс|млн|млрд))", "error", "Оформление",
     "Точка вместо запятой в десятичной дроби",
     "В русском тексте разделителем целой и дробной части служит запятая: «12,5 %», «3,4 млн руб.».",
     "Замените точку на запятую."),
    (r"(?<![\d.,])\d{5,}(?![\d])", "warning", "Оформление",
     "Число без разделения разрядов",
     "Многозначные числа в экономических расчётах разделяют неразрывным пробелом: «1 250 000 руб.», «12 500 тыс. руб.».",
     "Разделите разряды пробелом."),
    (r"\bв отличии\b", "error", "Грамматика",
     "«в отличии» вместо «в отличие»",
     "В значении «в сравнении с чем-либо» пишется «в отличие от». «В отличии» — предложный падеж существительного «отличие» и здесь неуместен.",
     "Исправьте на «в отличие от»."),
    (r"\bна протяжении\b(?!\s+[а-яё]+ия)", "warning", "Грамматика",
     "Проверьте «на протяжении»",
     "Если речь о времени или расстоянии, пишется «на протяжении» — ошибки нет; если о процессе — «на протяжении» тоже верно. Убедитесь, что не имелось в виду «на протяжении всего периода».",
     "Проверьте окончание: «на протяжении»."),
    (r"\bв следствие\b(?!\s+по\b)", "warning", "Грамматика",
     "«в следствие» вместо «вследствие»",
     "Предлог причины пишется слитно: «вследствие роста затрат». Раздельно — только существительное «в следствие» (устаревшее, о следствии по делу).",
     "Исправьте на «вследствие»."),
    (r"\bза счет\b", "warning", "Орфография",
     "«за счет» без «ё»",
     "В предлоге «за счёт» пишется «ё»: «за счёт снижения себестоимости». В экономических текстах это одна из самых частых ошибок.",
     "Напишите «за счёт»."),
    (r"\bпроизошл[ои]\s+(?:увеличение|уменьшение|снижение|сокращение|рост|падение|повышение)", "warning", "Стиль",
     "Канцелярит: «произошло увеличение»",
     "Конструкция «произошло увеличение показателя» — тяжёлый канцелярит. Пишут: «показатель вырос», «выручка снизилась».",
     "Замените на глагол: «выросла», «снизилась»."),
    (r"\bдинамик\w*\s+(?:рост|увелич|снижен|сокращен|падени)", "warning", "Логика",
     "Тавтология: «динамика роста»",
     "«Динамика» уже означает изменение во времени, поэтому «динамика роста» — тавтология. Достаточно «динамика показателя» или «рост показателя».",
     "Уберите лишнее слово."),
    (r"\bподорожани\w*\s+цен\b", "warning", "Логика",
     "Тавтология: «подорожание цен»",
     "Дорожают сами товары, а не цены: «рост цен», «подорожание продукции».",
     "Переформулируйте: «рост цен»."),
    (r"\bсебестоимост\w*\s+затрат\b", "warning", "Логика",
     "Тавтология: «себестоимость затрат»",
     "Себестоимость — это и есть денежное выражение затрат. Пишут «себестоимость продукции» или «величина затрат».",
     "Уберите лишнее слово."),
    (r"\bболее\s+(?:лучш|хужш|оптимальн|предпочтительн)", "error", "Логика",
     "Неверная степень сравнения",
     "Нельзя сказать «более лучший» или «более оптимальный»: эти прилагательные уже означают высшую степень.",
     "Напишите «лучше», «оптимальнее»."),
    (r"\bсам(?:ый|ая|ое|ые)\s+(?:оптимальн|максимальн|минимальн|наилучш)", "error", "Логика",
     "Плеоназм: «самый оптимальный»",
     "«Оптимальный», «максимальный», «минимальный» не образуют составную превосходную степень.",
     "Напишите «оптимальный», «максимальный»."),
    (r"\bв условиях\s+(?:рыночной|современной|нестабильной)\s+экономики\b", "warning", "Стиль",
     "Речевой штамп",
     "Оборот «в условиях рыночной экономики» — шаблон, который встречается в каждой второй экономической ВКР.",
     "Скажите конкретнее: о каком рынке, периоде и условиях речь."),
    (r"\bиграет\s+(?:важную|ключевую|большую)\s+роль\b", "warning", "Стиль",
     "Речевой штамп: «играет важную роль»",
     "Шаблонная конструкция без конкретики. Покажите, в чём именно выражается роль показателя или фактора.",
     "Замените на конкретное утверждение с цифрой или механизмом."),
    (r"\bв рамках данного\b|\bв рамках настоящего\b", "warning", "Стиль",
     "Канцелярит: «в рамках данного»",
     "Обороты «в рамках данного исследования» утяжеляют текст.",
     "Замените на «в работе», «здесь», «при анализе»."),
    (r"\bчто касается\b", "warning", "Стиль",
     "Канцелярит: «что касается»",
     "Вводный оборот «что касается… то…» — разговорно-канцелярская конструкция.",
     "Перестройте фразу без него."),
]

# Обязательные смысловые блоки экономической ВКР (проверяются по всему тексту).
ECONOMY_STRUCTURE = [
    (r"актуальност", "Актуальность темы",
     "Во введении ВКР по экономике обязательно обосновывается актуальность темы."),
    (r"объект\s+(?:исследования|изучения)", "Объект исследования",
     "Укажите объект исследования — организацию, отрасль или рынок, на материале которых выполнена работа."),
    (r"предмет\s+(?:исследования|изучения)", "Предмет исследования",
     "Укажите предмет исследования — конкретные экономические отношения, показатели или процессы."),
    (r"цел\w*\s+(?:работы|исследования|выпускной)", "Цель работы",
     "Сформулируйте цель работы одной фразой во введении."),
    (r"задач\w*\s+(?:работы|исследования)", "Задачи работы",
     "Перечислите задачи работы: они должны соответствовать цели и выводам."),
    (r"методолог|методы\s+исследования", "Методология исследования",
     "Опишите методы: анализ и синтез, статистические и экономико-математические методы, сравнение, группировку."),
    (r"практическ\w*\s+значимост", "Практическая значимость",
     "Для экономической ВКР нужен раздел о практической значимости и внедрении результатов."),
    (r"заключени", "Заключение",
     "В заключении сформулируйте выводы и результаты по каждой задаче."),
    (r"список\s+(?:использованных\s+)?(?:источник|литератур)", "Список источников",
     "Оформите список использованных источников по ГОСТ Р 7.0.100-2018."),
]


def economy_structure_issues(paras, stats):
    """Проверяет наличие обязательных разделов экономической ВКР (только для полного текста)."""
    if not paras or stats.get("words", 0) < 500:
        return []  # короткий фрагмент — структурные требования не применяем
    whole = "\n".join(p["text"] for p in paras).lower()
    first = paras[0]
    issues = []
    for pat, title, expl in ECONOMY_STRUCTURE:
        if re.search(pat, whole):
            continue
        issues.append({
            "severity": "warning",
            "category": "Структура",
            "para": first["id"],
            "start": 0,
            "end": min(60, len(first["text"])),
            "quote": first["text"][:60],
            "title": "Не найден раздел: %s" % title,
            "explanation": expl,
            "suggestion": "Добавьте раздел и озаглавьте его стандартно.",
            "source": "local",
        })
    return issues


ECONOMY_PROMPT_ADD = """
Это выпускная квалификационная работа по экономике (экономика, финансы, бухгалтерский учёт, менеджмент).
Дополнительно проверяй профессиональные требования:
- корректность экономических терминов: выручка, доход, прибыль, себестоимость, рентабельность, темп роста и темп прироста не взаимозаменяемы;
- единицы измерения по ГОСТ 8.417 (пробел между числом и единицей), десятичная запятая, «руб.», «тыс. руб.», «млн руб.»;
- проценты и процентные пункты: «вырос на 5 %» и «вырос на 5 п. п.» — разные вещи;
- при любых цифрах о рынке или организации должна быть ссылка на источник;
- подписи таблиц и рисунков, сквозная нумерация формул;
- структура экономической ВКР: актуальность, объект, предмет, цель, задачи, методы, практическая значимость, выводы по главам.
Для таких находок указывай category «Экономика».
"""


def local_check(paras, profile="universal"):
    rules = RULES + (ECONOMY_RULES if profile == "economy" else [])
    issues = []
    for p in paras:
        text = p["text"]
        for pat, sev, cat, title, expl, sugg in rules:
            for m in re.finditer(pat, text, re.IGNORECASE if pat.islower() else 0):
                s, e = m.start(), m.end()
                frag = text[s:e]
                if not frag.strip():
                    continue
                # для двойного пробела подсветим само слово рядом
                if re.fullmatch(r"\s+", frag):
                    ws = s
                    while ws > 0 and text[ws - 1].isspace():
                        ws -= 1
                    we = e
                    while we < len(text) and text[we].isspace():
                        we += 1
                    s = max(0, ws - 1)
                    e = min(len(text), we + 1)
                issues.append({
                    "severity": sev,
                    "category": cat,
                    "para": p["id"],
                    "start": s,
                    "end": e,
                    "quote": text[s:e][:140],
                    "title": title,
                    "explanation": expl,
                    "suggestion": sugg,
                    "source": "local",
                })
        # длинные предложения
        for m in re.finditer(r"[^.!?]+[.!?]", text):
            sent = m.group(0)
            words = len(re.findall(r"[\w\-]+", sent))
            if words >= 38:
                issues.append({
                    "severity": "warning",
                    "category": "Стиль",
                    "para": p["id"],
                    "start": m.start(),
                    "end": min(len(text), m.start() + 120),
                    "quote": text[m.start():m.start() + 120],
                    "title": "Слишком длинное предложение",
                    "explanation": f"В предложении {words} слов — читать и понимать его тяжело.",
                    "suggestion": "Разбейте на 2–3 предложения по смыслу.",
                    "source": "local",
                })
        # абзац без точки в конце
        if len(text) > 80 and not re.search(r"[.!?:;»)\]]\s*$", text):
            issues.append({
                "severity": "warning",
                "category": "Пунктуация",
                "para": p["id"],
                "start": max(0, len(text) - 60),
                "end": len(text),
                "quote": text[-60:],
                "title": "Абзац не завершён знаком препинания",
                "explanation": "Абзац обрывается без точки — возможно, предложение недописано.",
                "suggestion": "Поставьте точку или допишите мысль.",
                "source": "local",
            })
        # кавычки-лапки
        for m in re.finditer(r'"[^"]{3,}"', text):
            issues.append({
                "severity": "warning",
                "category": "Оформление",
                "para": p["id"],
                "start": m.start(),
                "end": m.end(),
                "quote": m.group(0)[:140],
                "title": "Прямые кавычки",
                "explanation": "В русском тексте используют «ёлочки», а не машинные \"кавычки\".",
                "suggestion": "Замените на «…».",
                "source": "local",
            })
    return issues


# --------------------------------------------------------------------------
# Groq
# --------------------------------------------------------------------------

SYSTEM_PROMPT = """Ты — строгий преподаватель экономики. Твоя задача — найти ВСЕ ошибки в тексте диплома.

Твоя задача — проверить присланный фрагмент дипломной работы и вернуть СТРОГО ОДИН JSON-объект без markdown, без ``` и без текста вокруг.
Внимательно прочитай текст от начала до конца. 
НЕ ОСТАНАВЛИВАЙСЯ на первой ошибке. Найди абсолютно все.


=====================================================================
ЧТО ТЫ ИЩЕШЬ
=====================================================================

Ты находишь находки ТРЁХ типов, и в каждой обязан указать kind:

1) kind = "typo" — ОПЕЧАТКА.
   Механическая ошибка набора: пропущена/лишняя/переставлена буква, слиплись два слова,
   неверная раскладка клавиатуры, лишний или недостающий пробел внутри слова.
   Примеры: «экономка» → «экономика», «инфляцыя» → «инфляция», «вобласти» → «в области»,
   «ghjlb;tybt» → «продукции», «прдприятие» → «предприятие».
   Для опечатки обязательно заполняй поле should_be.

2) kind = "error" — ОШИБКА.
   Нарушение норм русского языка или экономического смысла:
   - орфография: «в течении года» → «в течение года», «не смотря на» → «несмотря на»,
     «в виду» → «ввиду», «то-же» → «то же», «в отличии» → «в отличие»;
   - пунктуация: нет запятой перед «что/который/если/чтобы/где», лишняя запятая между
     подлежащим и сказуемым, не выделен причастный или деепричастный оборот,
     машинные "кавычки" вместо «ёлочек», дефис вместо тире;
   - грамматика: «согласно приказа» → «согласно приказу», «благодаря роста» → «благодаря росту»,
     неверное согласование рода, числа и падежа, разрыв устойчивого оборота;
   - экономика и факты: путаница «выручка/прибыль», «рентабельность/доходность»,
     «ликвидность/платёжеспособность», «амортизация/износ»; неверная формула или единица
     измерения; вывод, не следующий из таблицы; числа в тексте противоречат таблице;
     битая нумерация «рис. 0», «таблица ?», ссылка «[0]»;
   - логика: утверждение без ссылки на источник, подмена объекта и предмета исследования,
     цель и задачи не согласованы.

3) kind = "flaw" — НЕДОЧЁТ.
   Текст формально верен, но слаб:
   - канцелярит и вода: «в рамках осуществления мероприятий по…», «имеет место быть»;
   - повтор слова или корня в соседних предложениях;
   - предложение длиннее 35–40 слов, смысл теряется;
   - нет вывода в конце главы или параграфа;
   - нарушена структура ВКР: нет введения, заключения, списка литературы;
   - оформление: нет пробела перед «%», разные тире, разные интервалы;
   - злоупотребление «является», «осуществляется», «производится», «данный».

Не выдумывай находок. Если в абзаце всё в порядке — не упоминай его вовсе.

=====================================================================
ПОЧЕМУ ЭТО ОШИБКА — поле why
=====================================================================

В каждом issue поле why объясняет ПРИЧИНУ, а не пересказывает находку.
Для орфографии и пунктуации — назови правило русского языка.
Для грамматики — назови норму согласования или управления.
Для экономики — объясни, чем один показатель отличается от другого
или почему формула/единица измерения неверна.
Для структуры и оформления — сошлись на требование к ВКР или ГОСТ.
Поле why — 1–2 предложения, по делу, без воды.

=====================================================================
КАК СТАВИТЬ ОЦЕНКУ — блок grade
=====================================================================

Ты сам выставляешь оценку работе по 100-балльной шкале и переводишь её в отметку:

  90–100 — «5 (отлично)»             — работа готова к защите;
  75–89  — «4 (хорошо)»              — отдельные опечатки и недочёты;
  60–74  — «3 (удовлетворительно)»   — заметные ошибки, нужна доработка;
  40–59  — «2 (неудовлетворительно)» — много ошибок, логические провалы;
  ниже 40 — «1 (работа не готова)»   — подавать на нормоконтроль нельзя.

Считай так: старт 100 баллов;
  −4 за каждую ошибку category «Экономика» / «Факты» / «Логика»;
  −3 за каждую ошибку «Орфография» / «Грамматика»;
  −2 за каждую ошибку «Пунктуация»;
  −1 за каждую опечатку (kind="typo");
  −2 за каждый недочёт (kind="flaw");
но не ниже 5 и не выше 100. В grade.comment объясни, что сильнее всего снизило балл.

=====================================================================
ФОРМАТ ОТВЕТА
=====================================================================

Верни ровно такой JSON и ничего кроме него:

{
  "grade": {
    "score": 78,
    "mark": "4 (хорошо)",
    "comment": "Балл снижен за 3 орфографические ошибки и 4 стилистических недочёта; структура и экономическая логика в порядке."
  },
  "verdict": "Работа в целом готова, но требует вычитки: 5 ошибок, 7 недочётов.",
  "issues": [
    {
      "kind": "typo",
      "severity": "error",
      "category": "Орфография",
      "para": 12,
      "quote": "экономка",
      "found": "экономка",
      "should_be": "экономика",
      "why": "Пропущена буква «и» — слово искажено, это опечатка.",
      "fix": "Замените на «экономика».",
      "confidence": 0.99
    }
  ]
}

Поля каждого issue:
  kind       — строго "typo", "error" или "flaw";
  severity   — "error" для typo/error, "warning" для flaw;
  category   — Орфография, Пунктуация, Грамматика, Стиль, Структура,
               Оформление, Повторы, Факты, Логика или Экономика;
  para       — целое число, номер абзаца из метки [#N];
  quote      — ДОСЛОВНЫЙ фрагмент из этого абзаца, ровно как в тексте, до 120 символов;
  found      — что именно не так (обычно совпадает с quote);
  should_be  — правильный вариант; для flaw можно пустую строку;
  why        — ПОЧЕМУ это ошибка (правило, экономическая причина или требование ГОСТ);
  fix        — как исправить, конкретно;
  confidence — число от 0 до 1.

Жёсткие правила:
  * quote обязан встречаться в присланном тексте дословно — иначе находку не возвращай;
  * не более 16 находок на фрагмент, самые важные — первыми;
  * если ошибок нет — "issues": [] и score 100;
  * grade и verdict обязательны всегда;
  * пиши по-русски, кратко, без вступлений.
"""

USER_TEMPLATE = """Проверь фрагмент дипломной работы по экономике. Абзацы помечены метками [#номер].

Верни строго JSON по схеме из системной инструкции: grade, verdict, issues.

ТЕКСТ:
{body}"""


def _extract_json(text: str):
    if not text:
        return None
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    i, j = text.find("{"), text.rfind("}")
    if i >= 0 and j > i:
        try:
            return json.loads(text[i:j + 1])
        except Exception:
            return None
    return None


def groq_chat(key: str, model: str, user: str, max_tokens: int = 2600,
              json_mode: bool = True) -> str:
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
        "temperature": 0.1,
        "top_p": 0.9,
        "max_tokens": max_tokens,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    req = urlreq.Request(
        GROQ_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "diplom-check-ai/1.0",
        },
    )
    try:
        with urlreq.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except HTTPError as e:
        # некоторые модели не поддерживают строгий JSON-режим — повторяем без него
        if e.code == 400 and json_mode:
            try:
                e.read()
            except Exception:
                pass
            return groq_chat(key, model, user, max_tokens, json_mode=False)
        raise
    return (data["choices"][0]["message"]["content"] or "").strip()


def make_chunks(paras):
    chunks, cur, size = [], [], 0
    for p in paras:
        block = "[#%d] %s" % (p["id"], p["text"])
        if cur and size + len(block) > CHUNK_CHARS:
            chunks.append(cur)
            cur, size = [], 0
        cur.append(block)
        size += len(block) + 1
    if cur:
        chunks.append(cur)
    return chunks


def ai_check(paras, key, model, progress, profile="universal"):
    chunks = make_chunks(paras)
    note = None
    if len(chunks) > MAX_CHUNKS:
        note = "Документ очень большой: нейросеть проверила первые %d фрагментов." % MAX_CHUNKS
        chunks = chunks[:MAX_CHUNKS]

    raw_issues = []
    verdict = ""
    grade_scores = []
    grade_mark = ""
    grade_comment = ""
    total = max(1, len(chunks))
    for idx, chunk in enumerate(chunks):
        progress(0.08 + 0.86 * (idx / total), "Нейросеть читает фрагмент %d из %d…" % (idx + 1, total))
        body = "\n".join(chunk)
        prompt = USER_TEMPLATE.replace("{body}", body)
        content = None
        for attempt in range(3):
            try:
                content = groq_chat(key, model, prompt)
                break
            except HTTPError as e:
                detail = ""
                try:
                    detail = e.read().decode("utf-8", "replace")[:400]
                except Exception:
                    pass
                if e.code in (401, 403):
                    raise RuntimeError("Groq отклонил ключ API (%s). Проверьте GROQ_API_KEY." % e.code)
                if e.code == 429:
                    time.sleep(2.0 + attempt * 2.0)
                    continue
                raise RuntimeError("Ошибка Groq %s: %s" % (e.code, detail or e.reason))
            except URLError as e:
                time.sleep(1.0 + attempt)
                if attempt == 2:
                    raise RuntimeError("Нет связи с Groq: %s" % e.reason)
            except Exception:
                time.sleep(1.0)

        if not content:
            continue
        data = _extract_json(content)
        if not isinstance(data, dict):
            continue
        # --- общая оценка от нейросети (блок grade) ---
        g = data.get("grade")
        if isinstance(g, dict):
            try:
                sc = int(round(float(g.get("score"))))
            except Exception:
                sc = None
            if sc is not None:
                sc = max(5, min(100, sc))
                grade_scores.append(sc)
            mark = str(g.get("mark") or "").strip()[:80]
            comment = str(g.get("comment") or "").strip()[:600]
            if mark and not grade_mark:
                grade_mark = mark
            if comment and not grade_comment:
                grade_comment = comment

        if not verdict and isinstance(data.get("verdict"), str):
            verdict = data["verdict"].strip()[:400]

        for it in data.get("issues") or []:
            if not isinstance(it, dict):
                continue
            kind = str(it.get("kind") or "").strip().lower()
            if kind not in ("typo", "error", "flaw"):
                # обратная совместимость со старым форматом
                kind = "error" if str(it.get("severity", "")).lower() == "error" else "flaw"
            sev = "warning" if kind == "flaw" else "error"
            cat = str(it.get("category") or "Стиль").strip()
            if cat not in CATEGORIES:
                cat = next((c for c in CATEGORIES if c.lower() in cat.lower()), "Стиль")
            try:
                pid = int(it.get("para"))
            except Exception:
                pid = 0
            raw_issues.append({
                "kind": kind,
                "severity": sev,
                "category": cat,
                "para": pid,
                "quote": str(it.get("quote") or "")[:200],
                "found": str(it.get("found") or "")[:160],
                "should_be": str(it.get("should_be") or "")[:160],
                "title": str(it.get("title") or "")[:160],
                "why": str(it.get("why") or it.get("explanation") or "")[:900],
                "explanation": str(it.get("why") or it.get("explanation") or "")[:900],
                "fix": str(it.get("fix") or it.get("suggestion") or "")[:600],
                "suggestion": str(it.get("fix") or it.get("suggestion") or "")[:600],
                "confidence": it.get("confidence"),
                "source": "ai",
            })

    progress(0.96, "Сверяю находки с текстом…")
    issues = resolve_issues(paras, raw_issues)
    grade = None
    if grade_scores:
        avg = int(round(sum(grade_scores) / float(len(grade_scores))))
        grade = {"score": avg, "mark": grade_mark or mark_for_score(avg), "comment": grade_comment}
    return issues, verdict, note, grade


def resolve_issues(paras, raw_issues):
    by_id = {p["id"]: p for p in paras}
    resolved, seen = [], set()
    for it in raw_issues:
        p = by_id.get(it.get("para"))
        quote = (it.get("quote") or "").strip()
        span = None
        if p:
            span = find_span(p["text"], quote)
        if not span and quote:
            for cand in paras:
                span = find_span(cand["text"], quote)
                if span:
                    p = cand
                    break
        if not span or not p:
            continue
        span = clamp_span(span, len(p["text"]))
        if not span:
            continue
        key = (p["id"], span[0], span[1])
        if key in seen:
            continue
        seen.add(key)
        kind = it.get("kind") or ("flaw" if it["severity"] == "warning" else "error")
        found = (it.get("found") or "").strip() or p["text"][span[0]:span[1]][:160]
        title = (it.get("title") or "").strip()
        if not title:
            title = KIND_TITLES.get(kind, "Замечание")
        resolved.append({
            "kind": kind,
            "severity": it["severity"],
            "category": it["category"],
            "para": p["id"],
            "start": span[0],
            "end": span[1],
            "quote": p["text"][span[0]:span[1]][:160],
            "found": found[:200],
            "should_be": (it.get("should_be") or "")[:200],
            "title": title[:160],
            "why": it["explanation"],
            "explanation": it["explanation"],
            "fix": it["suggestion"],
            "suggestion": it["suggestion"],
            "confidence": it.get("confidence"),
            "source": it.get("source", "ai"),
        })
    resolved.sort(key=lambda x: (x["para"], x["start"]))
    for i, it in enumerate(resolved, start=1):
        it["id"] = i
    return resolved


# --------------------------------------------------------------------------
# Сборка результата
# --------------------------------------------------------------------------

def build_stats(paras):
    text = "\n".join(p["text"] for p in paras)
    words = len(re.findall(r"[\w\-]+", text, re.UNICODE))
    return {
        "chars": len(text),
        "words": words,
        "paras": len(paras),
        "sheets": max(1, round(words / 1800)),
        "sentences": max(1, len(re.findall(r"[.!?]+", text))),
    }


def build_chart(issues):
    order, acc = [], {}
    for it in issues:
        cat = it["category"]
        if cat not in acc:
            acc[cat] = {"name": cat, "errors": 0, "warnings": 0}
            order.append(cat)
        acc[cat]["errors" if it["severity"] == "error" else "warnings"] += 1
    rows = [acc[c] for c in order]
    rows.sort(key=lambda r: (r["errors"] + r["warnings"]), reverse=True)
    return rows


def plural(n, one, few, many):
    """Русская форма числительного: 1 ошибка, 2 ошибки, 5 ошибок."""
    n = abs(int(n)) % 100
    if 11 <= n <= 19:
        return many
    n %= 10
    if n == 1:
        return one
    if 2 <= n <= 4:
        return few
    return many


def build_summary(errors, warnings, stats):
    if errors == 0 and warnings == 0:
        return "Замечаний не найдено — текст выглядит аккуратно."
    parts = ["Найдено"]
    parts.append("%d %s" % (errors, plural(errors, "ошибка", "ошибки", "ошибок")))
    parts.append("и")
    parts.append("%d %s" % (warnings, plural(warnings, "недочёт", "недочёта", "недочётов")))
    tail = ""
    if stats.get("words"):
        tail = " на %d %s (≈%d %s)" % (
            stats["words"],
            plural(stats["words"], "слово", "слова", "слов"),
            stats["sheets"],
            plural(stats["sheets"], "страница", "страницы", "страниц"),
        )
    return " ".join(parts) + tail + "."


def run_check(filename, data, mode, model, key, progress, profile="universal"):
    progress(0.03, "Читаю файл «%s»…" % filename)
    raw = extract_paragraphs(filename, data)
    paras = normalize_paragraphs(raw)
    if not paras:
        raise ValueError("В файле не найден текст для проверки.")
    stats = build_stats(paras)
    progress(0.08, "Текст разобран: %d абзацев, %d слов." % (stats["paras"], stats["words"]))

    verdict = ""
    note = None
    grade = None
    used_mode = mode

    if mode == "ai" and key:
        try:
            issues, verdict, note, grade = ai_check(paras, key, model, progress, profile)
        except RuntimeError as e:  # ключ, сеть, лимиты — откатываемся на локальный режим
            progress(0.9, "Нейросеть недоступна, включаю локальный нормоконтроль…")
            issues = local_check(paras, profile)
            used_mode = "local"
            note = "%s Выполнен локальный нормоконтроль." % e
        except Exception as e:  # сеть/парсинг — тоже локальный режим
            issues = local_check(paras, profile)
            used_mode = "local"
            note = "Нейросеть недоступна (%s) — выполнен локальный нормоконтроль." % type(e).__name__
    else:
        progress(0.35, "Локальный нормоконтроль…")
        issues = local_check(paras, profile)
        used_mode = "local"
        if mode == "ai" and not key:
            note = "Ключ Groq не задан — выполнен локальный нормоконтроль (без нейросети)."

    if profile == "economy":
        progress(0.96, "Проверяю структуру экономической ВКР…")
        issues = economy_structure_issues(paras, stats) + issues

    progress(0.98, "Готовлю подсветку…")
    issues = issues[:400]
    for i, it in enumerate(issues, start=1):
        it["id"] = i

    errors = sum(1 for i in issues if i["severity"] == "error")
    warnings = sum(1 for i in issues if i["severity"] == "warning")
    typos = sum(1 for i in issues if i.get("kind") == "typo")

    # оценка: приоритет у нейросети, иначе считаем локально
    if grade and isinstance(grade.get("score"), int):
        score = grade["score"]
        mark = grade.get("mark") or mark_for_score(score)
        grade_comment = grade.get("comment") or ""
    else:
        score = max(5, min(100, 100 - errors * 5 - warnings * 2))
        mark = mark_for_score(score)
        grade_comment = ""

    summary = verdict or build_summary(errors, warnings, stats)

    progress(1.0, "Готово")
    return {
        "ok": True,
        "mode": used_mode,
        "model": model if used_mode == "ai" else None,
        "file": filename,
        "stats": stats,
        "pages": make_pages(paras),
        "paragraphs": paras,
        "issues": issues,
        "chart": build_chart(issues),
        "summary": summary,
        "verdict": summary,
        "score": score,
        "mark": mark,
        "grade": {
            "score": score,
            "mark": mark,
            "comment": grade_comment,
            "by_ai": bool(grade),
        },
        "errors": errors,
        "warnings": warnings,
        "typos": typos,
        "notes": [n for n in [note] if n],
        "profile": profile,
    }


# --------------------------------------------------------------------------
# Очередь задач
# --------------------------------------------------------------------------

JOBS = {}
JOBS_LOCK = threading.Lock()
JOBS_TTL = 3600


def job_set(job_id, **kw):
    with JOBS_LOCK:
        j = JOBS.get(job_id)
        if j:
            j.update(kw)
            j["ts"] = time.time()


def job_get(job_id):
    with JOBS_LOCK:
        j = JOBS.get(job_id)
        return dict(j) if j else None


def jobs_gc():
    now = time.time()
    with JOBS_LOCK:
        for k in [k for k, v in JOBS.items() if now - v.get("ts", now) > JOBS_TTL]:
            JOBS.pop(k, None)


def job_worker(job_id, filename, data, mode, model, key, profile=DEFAULT_PROFILE):
    def progress(p, stage):
        job_set(job_id, progress=round(float(p), 3), stage=stage, status="running")

    try:
        result = run_check(filename, data, mode, model, key, progress, profile)
        job_set(job_id, status="done", progress=1.0, stage="Готово", result=result)
    except Exception as e:
        job_set(job_id, status="error", stage="Ошибка", error=str(e) or type(e).__name__)


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

INDEX_NAMES = ["index.html", "client.html"]


class Handler(BaseHTTPRequestHandler):
    server_version = "DiplomCheck/1.0"
    protocol_version = "HTTP/1.1"

    # ---- helpers -------------------------------------------------------
    def _send(self, code, body: bytes, ctype="application/json; charset=utf-8", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def log_message(self, fmt, *args):
        sys.stderr.write("  %s\n" % (fmt % args))

    # ---- GET -----------------------------------------------------------
    def do_GET(self):
        path = self.path.split("?")[0]
        query = {}
        if "?" in self.path:
            for part in self.path.split("?", 1)[1].split("&"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    query[k] = v

        if path in ("/", "/index.html", "/client.html"):
            return self._serve_index()

        if path == "/api/health":
            jobs_gc()
            key = current_key()
            return self._json({
                "ok": True,
                "has_key": bool(key),
                "key_hint": (key[:6] + "…" + key[-4:]) if key and len(key) > 12 else ("есть" if key else ""),
                "models": MODELS,
                "default_model": DEFAULT_MODEL,
                "local_mode": True,
                "profiles": PROFILES,
                "default_profile": DEFAULT_PROFILE,
            })

        if path == "/api/job":
            jid = query.get("id", "")
            j = job_get(jid)
            if not j:
                return self._json({"ok": False, "error": "Задача не найдена"}, 404)
            out = {
                "ok": True,
                "status": j.get("status", "running"),
                "progress": j.get("progress", 0.0),
                "stage": j.get("stage", ""),
            }
            if j.get("status") == "done":
                out["result"] = j.get("result")
            if j.get("status") == "error":
                out["error"] = j.get("error", "Неизвестная ошибка")
            return self._json(out)

        if path == "/favicon.ico":
            return self._send(204, b"", "image/x-icon")

        return self._send(404, b'{"ok":false,"error":"not found"}')

    def _serve_index(self):
        for name in INDEX_NAMES:
            fp = os.path.join(HERE, name)
            if os.path.isfile(fp):
                with open(fp, "rb") as f:
                    return self._send(200, f.read(), "text/html; charset=utf-8")
        return self._send(
            200,
            b"<h1>index.html not found</h1><p>Put index.html next to server.py</p>",
            "text/html; charset=utf-8",
        )

    # ---- POST ----------------------------------------------------------
    def do_POST(self):
        path = self.path.split("?")[0]

        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length > MAX_UPLOAD:
            return self._json({"ok": False, "error": "Файл больше 30 МБ"}, 413)

        body = b""
        if length:
            try:
                body = self.rfile.read(length)
            except Exception:
                body = b""

        if path == "/api/check":
            return self._handle_check(body)

        return self._json({"ok": False, "error": "not found"}, 404)

    def _handle_check(self, body):
        if not body:
            return self._json({"ok": False, "error": "Пустой файл"}, 400)

        fn_b64 = self.headers.get("X-Filename-B64") or ""
        try:
            filename = base64.b64decode(fn_b64.encode("ascii")).decode("utf-8", "replace") if fn_b64 else "document.txt"
        except Exception:
            filename = "document.txt"
        filename = os.path.basename(filename.replace("\\", "/")) or "document.txt"

        mode = (self.headers.get("X-Mode") or "ai").strip().lower()
        if mode not in ("ai", "local"):
            mode = "ai"
        model = (self.headers.get("X-Model") or DEFAULT_MODEL).strip()
        if model not in [m["id"] for m in MODELS]:
            model = DEFAULT_MODEL
        profile = (self.headers.get("X-Profile") or DEFAULT_PROFILE).strip().lower()
        if profile not in [p["id"] for p in PROFILES]:
            profile = DEFAULT_PROFILE

        # Ключ берётся только на стороне сервера: --key при запуске
        # или переменная окружения GROQ_API_KEY. Браузер ключ не передаёт.
        key = current_key()
        job_id = uuid.uuid4().hex
        with JOBS_LOCK:
            JOBS[job_id] = {
                "status": "running",
                "progress": 0.01,
                "stage": "Ставлю задачу в очередь…",
                "ts": time.time(),
            }
        jobs_gc()
        t = threading.Thread(
            target=job_worker,
            args=(job_id, filename, body, mode, model, key, profile),
            daemon=True,
        )
        t.start()
        return self._json({"ok": True, "job_id": job_id, "filename": filename})


# --------------------------------------------------------------------------
# Запуск
# --------------------------------------------------------------------------

CLI_KEY = None


def current_key():
    """Ключ сервера: --key в командной строке или переменная окружения.

    Ключ нигде не хранится на диске и не кэшируется.
    """
    if CLI_KEY:
        return CLI_KEY
    env = os.environ.get("GROQ_API_KEY") or os.environ.get("GROQ_KEY") or ""
    if env.strip():
        return env.strip()
    return None


def main(argv):
    global CLI_KEY
    # консоль хостинга/Windows может быть в cp1251 — принудительно UTF-8, иначе баннер падает
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass
    # Render/Heroku и подобные хостинги передают порт в $PORT и требуют 0.0.0.0
    env_port = os.environ.get("PORT", "").strip()
    env_host = os.environ.get("HOST", "").strip()
    if env_port:
        host = env_host or "0.0.0.0"
        port = int(env_port)
    else:
        host, port = env_host or "127.0.0.1", 8765
    args = list(argv[1:])
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("--port", "-p") and i + 1 < len(args):
            port = int(args[i + 1]); i += 2; continue
        if a in ("--host",) and i + 1 < len(args):
            host = args[i + 1]; i += 2; continue
        if a in ("--key", "-k") and i + 1 < len(args):
            CLI_KEY = args[i + 1].strip(); i += 2; continue
        if a in ("--help", "-h"):
            print(__doc__)
            return 0
        i += 1

    key = current_key()
    srv = ThreadingHTTPServer((host, port), Handler)
    srv.daemon_threads = True

    print("")
    print("  ╔══════════════════════════════════════════════════════════╗")
    print("  ║        ДИПЛОМ-ЧЕК AI  ·  проверка диплома нейросетью      ║")
    print("  ╚══════════════════════════════════════════════════════════╝")
    print("")
    print("  Откройте в браузере:  http://%s:%d" % (host, port))
    print("")
    if key:
        print("  Groq: ключ найден (%s…%s), модель по умолчанию: %s" % (key[:6], key[-4:], DEFAULT_MODEL))
    else:
        print("  Groq: ключ НЕ задан — работает локальный нормоконтроль.")
        print("        Чтобы включить нейросеть, задайте переменную окружения GROQ_API_KEY")
        print("        или вставьте ключ gsk_… прямо в поле на странице (он нигде не сохраняется).")
        print("        Ключ: https://console.groq.com/keys")
    print("")
    print("  Остановить сервер: Ctrl+C")
    print("")

    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  Сервер остановлен.")
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
