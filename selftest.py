# -*- coding: utf-8 -*-
"""Автотест: гоняет полный конвейер server.py без браузера."""
import base64
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server  # noqa: E402

SAMPLE = """ВВЕДЕНИЕ

В данной работе рассматривается  проблема классификации текстов .
Актуальность темы обусловлена тем что объемы данных растут очень быстро.
Нейросети  являются  эффективным инструментом,однако требуют данных.
В течении последних лет появились трансформеры, которые которые показали
высокое качество. Не смотря на это, остается много открытых вопросов
Стоит отметить, что модель обучается на большом корпусе и это очень важно для качества
результата, потому что без данных обучение невозможно и поэтому исследователи
собирают огромные наборы текстов из разных источников чтобы улучшить качество
модели и получить более высокие показатели на тестовой выборке, что является
основной целью большинства современных работ в этой области знаний.
"""

print("=" * 60)
print("1. Извлечение и нормализация абзацев")
raw = server.extract_paragraphs("sample.txt", SAMPLE.encode("utf-8"))
paras = server.normalize_paragraphs(raw)
print("   абзацев:", len(paras))
for p in paras[:4]:
    print("   #%d [%s] %s" % (p["id"], p["kind"], p["text"][:60]))
assert len(paras) >= 5, "слишком мало абзацев"
assert all("id" in p and "text" in p and "kind" in p for p in paras)

print("2. Локальный нормоконтроль")
issues = server.local_check(paras)
print("   находок:", len(issues))
kinds = {}
for it in issues:
    kinds[it["severity"]] = kinds.get(it["severity"], 0) + 1
print("   по типам:", kinds)
assert issues, "локальный нормоконтроль ничего не нашёл"
by_id = {p["id"]: p for p in paras}
for it in issues:
    host = by_id.get(it["para"])
    assert host, "находка ссылается на несуществующий абзац %r" % it["para"]
    assert 0 <= it["start"] < it["end"] <= len(host["text"]), \
        "span %r-%r вне абзаца %r (длина %d)" % (it["start"], it["end"], it["para"], len(host["text"]))
print("   примеры:")
for it in issues[:5]:
    print("     -", it["severity"], "|", it["title"], "|", repr(it["quote"][:40]))

print("3. Разбивка на страницы")
pages = server.make_pages(paras)
print("   страниц:", len(pages), "| на первой:", len(pages[0]))
flat = [i for pg in pages for i in pg]
assert sorted(flat) == sorted(p["id"] for p in paras), "потерялись абзацы при разбивке"

print("4. Нормализация находок ИИ (сырой JSON -> подсветка)")
raw_ai = [
    {"severity": "error", "category": "Пунктуация", "para": paras[1]["id"],
     "quote": "данной работе рассматривается  проблема",
     "title": "Лишний пробел", "explanation": "Два пробела.",
     "suggestion": "Один пробел."},
    {"severity": "warning", "category": "Стиль", "para": paras[1]["id"],
     "quote": "Актуальность темы обусловлена тем что",
     "title": "Канцелярит", "explanation": "Штамп.", "suggestion": "Проще."},
    {"severity": "error", "category": "Пунктуация", "para": 9999,
     "quote": "несуществующий абзац", "title": "Мусор",
     "explanation": "x", "suggestion": "y"},
]
resolved = server.resolve_issues(paras, raw_ai)
print("   принято:", len(resolved), "из", len(raw_ai))
assert len(resolved) == 2, "должен отсечься мусорный абзац"
for it in resolved:
    p = next(p for p in paras if p["id"] == it["para"])
    assert 0 <= it["start"] < it["end"] <= len(p["text"]), "span вне абзаца: %r" % it
print("   ок, спаны внутри текста")

print("5. Оценка, статистика, диаграмма")
stats = server.build_stats(paras)
chart = server.build_chart(issues + resolved)
summary = server.build_summary(3, 5, stats)
print("   статистика:", stats)
print("   диаграмма (категории):", [r["name"] for r in chart])
print("   вывод:", summary[:80])
assert chart and all("errors" in r and "warnings" in r for r in chart)

print("6. Структура результата для клиента")
allissues = server.resolve_issues(paras, issues)
for i, it in enumerate(allissues, 1):
    it["id"] = i
errs = sum(1 for i in allissues if i["severity"] == "error")
warns = sum(1 for i in allissues if i["severity"] == "warning")
print("   ошибок:", errs, "| недочётов:", warns, "| всего:", len(allissues))

print("7. HTTP-сервер: health / check / job")
import threading  # noqa: E402
from http.server import ThreadingHTTPServer  # noqa: E402

srv = ThreadingHTTPServer(("127.0.0.1", 8791), server.Handler)
srv.daemon_threads = True
threading.Thread(target=srv.serve_forever, daemon=True).start()
time.sleep(0.4)
BASE = "http://127.0.0.1:8791"

with urllib.request.urlopen(BASE + "/api/health", timeout=5) as r:
    health = json.loads(r.read().decode("utf-8"))
print("   health:", {k: health[k] for k in ("ok", "has_key", "default_model") if k in health})
assert health.get("ok") and health.get("models")

with urllib.request.urlopen(BASE + "/", timeout=5) as r:
    html = r.read().decode("utf-8")
print("   index.html отдан:", len(html), "символов")
assert "<canvas" in html and "api/check" in html

req = urllib.request.Request(
    BASE + "/api/check",
    data=SAMPLE.encode("utf-8"),
    headers={
        "Content-Type": "application/octet-stream",
        "X-Filename-B64": base64.b64encode("тест.txt".encode("utf-8")).decode("ascii"),
        "X-Mode": "local",
        "X-Model": "llama-3.3-70b-versatile",
    },
    method="POST",
)
with urllib.request.urlopen(req, timeout=10) as r:
    job = json.loads(r.read().decode("utf-8"))
print("   задача:", job.get("ok"), job.get("filename"), job.get("job_id", "")[:8])
assert job.get("ok"), job

result = None
for _ in range(60):
    with urllib.request.urlopen(BASE + "/api/job?id=" + job["job_id"], timeout=5) as r:
        j = json.loads(r.read().decode("utf-8"))
    if j.get("status") == "done":
        result = j["result"]
        break
    if j.get("status") == "error":
        raise SystemExit("ошибка задачи: " + str(j.get("error")))
    time.sleep(0.25)

assert result, "задача не завершилась"
print("   результат: score=%s errors=%s warnings=%s абзацев=%s страниц=%s находок=%s"
      % (result["score"], result["errors"], result["warnings"],
         len(result["paragraphs"]), len(result["pages"]), len(result["issues"])))
assert result["issues"], "нет находок"
assert result["pages"], "нет страниц"
for it in result["issues"]:
    assert set(it) >= {"id", "severity", "category", "para", "start", "end",
                       "quote", "title", "explanation", "suggestion", "source"}
print("   поля находок полные, id уникальны:",
      len({i["id"] for i in result["issues"]}) == len(result["issues"]))

srv.shutdown()
print("=" * 60)
print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")