from datetime import UTC, datetime, time
from decimal import Decimal
from html import escape
import asyncio
import base64
import hashlib
import hmac
from pathlib import Path
import re
import secrets
from xml.etree.ElementTree import Element, SubElement, tostring

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import func, select

from database.db import session_scope
from database.models import Chat, LLMCall, Product, ProductImport
from products.remote_xml_importer import ProductRemoteXmlImporter
from products.xml_importer import ProductXmlImporter
from settings import BASE_DIR, get_settings


router = APIRouter(tags=["admin"])

ADMIN_COOKIE_NAME = "amix_admin_session"
ADMIN_COOKIE_MAX_AGE = 60 * 60 * 24 * 30
ADMIN_SESSION_VALUE = "admin"


def require_admin(request: Request) -> None:
    if _is_admin_authenticated(request):
        return
    raise HTTPException(
        status_code=status.HTTP_303_SEE_OTHER,
        detail="Admin login required",
        headers={"Location": "/admin/login"},
    )


@router.get("/admin/login", response_class=HTMLResponse)
def admin_login_page(request: Request, next: str = "/admin") -> HTMLResponse:
    if _is_admin_authenticated(request):
        return HTMLResponse(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": _safe_admin_path(next)},
        )
    return HTMLResponse(_render_login_page(next_path=_safe_admin_path(next)))


@router.post("/admin/login")
def admin_login_submit(
    password: str = Form(...),
    next: str = Form("/admin"),
) -> Response:
    settings = get_settings()
    if not secrets.compare_digest(password, settings.admin_password):
        return HTMLResponse(
            _render_login_page(next_path=_safe_admin_path(next), error="Неверный пароль"),
            status_code=status.HTTP_200_OK,
        )

    response = RedirectResponse(_safe_admin_path(next), status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        ADMIN_COOKIE_NAME,
        _build_session_cookie_value(),
        max_age=ADMIN_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    return response


@router.post("/admin/logout")
def admin_logout() -> RedirectResponse:
    response = RedirectResponse("/admin/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(ADMIN_COOKIE_NAME)
    return response


@router.get("/admin", response_class=HTMLResponse)
def admin_page(
    import_status: str | None = None,
    error: str | None = None,
    _: None = Depends(require_admin),
) -> HTMLResponse:
    stats = _load_admin_stats()
    message = _build_flash_message(import_status=import_status, error=error)
    return HTMLResponse(_render_admin_page(stats=stats, flash_message=message))


@router.get("/admin/products.xml")
def download_products_xml(_: None = Depends(require_admin)) -> Response:
    xml_content = _export_products_xml()
    filename = f"amix-products-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.xml"
    return Response(
        content=xml_content,
        media_type="application/xml; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/admin/products/import")
async def import_products_xml(
    file: UploadFile = File(...),
    _: None = Depends(require_admin),
) -> RedirectResponse:
    if not file.filename:
        return RedirectResponse("/admin?error=empty_filename", status_code=status.HTTP_303_SEE_OTHER)

    if not file.filename.lower().endswith(".xml"):
        return RedirectResponse("/admin?error=not_xml", status_code=status.HTTP_303_SEE_OTHER)

    incoming_dir = BASE_DIR / "data" / "incoming_xml"
    incoming_dir.mkdir(parents=True, exist_ok=True)

    target_path = incoming_dir / _build_upload_filename(file.filename)
    content = await file.read()
    target_path.write_bytes(content)

    result = ProductXmlImporter().import_file(target_path)
    if result.status != "completed":
        return RedirectResponse("/admin?error=import_failed", status_code=status.HTTP_303_SEE_OTHER)

    return RedirectResponse("/admin?import_status=ok", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/products/import-remote")
async def import_products_remote(_: None = Depends(require_admin)) -> RedirectResponse:
    settings = get_settings()
    importer = ProductRemoteXmlImporter.from_settings(settings)
    result = await asyncio.to_thread(importer.download_and_import)
    if result.status != "completed":
        return RedirectResponse("/admin?error=remote_import_failed", status_code=status.HTTP_303_SEE_OTHER)

    return RedirectResponse("/admin?import_status=remote_ok", status_code=status.HTTP_303_SEE_OTHER)


def _is_admin_authenticated(request: Request) -> bool:
    cookie_value = request.cookies.get(ADMIN_COOKIE_NAME)
    if not cookie_value:
        return False
    expected = _build_session_cookie_value()
    return secrets.compare_digest(cookie_value, expected)


def _build_session_cookie_value() -> str:
    settings = get_settings()
    signature = hmac.new(
        settings.admin_password.encode("utf-8"),
        ADMIN_SESSION_VALUE.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    token = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
    return f"{ADMIN_SESSION_VALUE}.{token}"


def _safe_admin_path(value: str) -> str:
    if value.startswith("/admin") and not value.startswith("//"):
        return value
    return "/admin"


def _load_admin_stats() -> dict[str, str]:
    settings = get_settings()
    today_start = datetime.combine(datetime.now(UTC).date(), time.min, tzinfo=UTC)
    with session_scope() as session:
        product_count = session.scalar(select(func.count(Product.id))) or 0
        chats_today = (
            session.scalar(select(func.count(Chat.id)).where(Chat.created_at >= today_start)) or 0
        )
        latest_import = session.scalar(
            select(ProductImport)
            .where(ProductImport.status == "completed")
            .order_by(ProductImport.finished_at.desc(), ProductImport.id.desc())
            .limit(1)
        )
        llm_calls, llm_tokens, llm_cost_rub = session.execute(
            select(
                func.count(LLMCall.id),
                func.coalesce(func.sum(LLMCall.total_tokens), 0),
                func.coalesce(func.sum(LLMCall.estimated_rub), 0),
            )
        ).one()

    return {
        "service_status": "Бот работает",
        "product_count": _format_int(product_count),
        "chats_today": _format_int(chats_today),
        "llm_calls_label": _format_count(llm_calls or 0, "запрос", "запроса", "запросов"),
        "llm_tokens": _format_int(llm_tokens or 0),
        "llm_cost_rub": f"{Decimal(llm_cost_rub or 0):.2f} ₽",
        "latest_import": _format_datetime(latest_import.finished_at if latest_import else None),
        "xml_status": "актуальна" if latest_import else "ещё не загружена",
        "remote_url": settings.products_xml_remote_url,
        "auto_import_status": "включено" if settings.products_xml_auto_import_enabled else "выключено",
        "auto_import_interval": _format_interval(settings.products_xml_auto_import_interval_seconds),
    }


def _export_products_xml() -> bytes:
    root = Element("root")
    with session_scope() as session:
        products = session.scalars(select(Product).order_by(Product.article.asc(), Product.code.asc())).all()

    for product in products:
        record = SubElement(root, "record")
        _append_text(record, "Код", product.code)
        _append_text(record, "Артикул", product.article)
        _append_text(record, "ЦенаКорпоративная", _format_decimal(product.corporate_price, places=2))
        _append_text(record, "ЦенаРозничная", _format_decimal(product.retail_price, places=2))
        _append_text(record, "ЕдиницаИзмерения", product.unit)
        _append_text(record, "Вес", _format_decimal(product.weight, places=3))
        _append_text(record, "Объем", _format_decimal(product.volume, places=3))
        _append_text(record, "СвободныйОстаток", _format_decimal(product.free_stock, places=3))

    return b'<?xml version="1.0" encoding="utf-8"?>\n' + tostring(root, encoding="utf-8")


def _append_text(parent: Element, tag: str, value: str | None) -> None:
    element = SubElement(parent, tag)
    element.text = value or ""


def _format_decimal(value: Decimal | None, *, places: int) -> str | None:
    if value is None:
        return None
    return f"{value:.{places}f}"


def _format_int(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def _format_count(value: int, one: str, few: str, many: str) -> str:
    number = int(value)
    if number % 10 == 1 and number % 100 != 11:
        suffix = one
    elif number % 10 in {2, 3, 4} and number % 100 not in {12, 13, 14}:
        suffix = few
    else:
        suffix = many
    return f"{_format_int(number)} {suffix}"


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return "нет данных"
    return value.strftime("%d.%m.%Y %H:%M")


def _format_interval(seconds: int) -> str:
    minutes = max(1, round(seconds / 60))
    return f"{minutes} мин"


def _build_upload_filename(filename: str) -> str:
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(filename).name).strip("._")
    if not safe_name:
        safe_name = "products.xml"
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"{timestamp}-{safe_name}"


def _build_flash_message(import_status: str | None, error: str | None) -> str:
    if import_status == "ok":
        return '<div class="flash flash-success">XML загружен, база товаров обновлена.</div>'
    if import_status == "remote_ok":
        return '<div class="flash flash-success">XML скачан по ссылке, база товаров обновлена.</div>'

    errors = {
        "empty_filename": "Не удалось определить имя файла.",
        "not_xml": "Загрузите файл в формате XML.",
        "import_failed": "Импорт не завершился. Проверьте XML-файл.",
        "remote_import_failed": "Не удалось скачать или импортировать XML по ссылке.",
    }
    if error:
        return f'<div class="flash flash-error">{escape(errors.get(error, "Не удалось загрузить файл."))}</div>'
    return ""


def _render_login_page(*, next_path: str, error: str | None = None) -> str:
    error_html = f'<div class="login-error">{escape(error)}</div>' if error else ""
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Вход в панель AMIX</title>
  <style>
    :root {{
      --page: #f3f4f6;
      --surface: #fbfbfa;
      --text: #1d232b;
      --muted: #657080;
      --line: #d8dde5;
      --blue: #2563eb;
      --blue-dark: #1d4ed8;
      --red: #b42318;
      --red-bg: #fff0ed;
      --shadow: 0 24px 70px rgba(31, 41, 55, 0.08);
    }}

    * {{ box-sizing: border-box; }}

    body {{
      margin: 0;
      min-height: 100dvh;
      display: grid;
      place-items: center;
      padding: 22px;
      background:
        radial-gradient(circle at top left, rgba(37, 99, 235, 0.08), transparent 32rem),
        var(--page);
      color: var(--text);
      font-family: "Manrope", "Aptos", "Segoe UI", sans-serif;
    }}

    .login {{
      width: min(100%, 430px);
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 30px;
      box-shadow: var(--shadow);
      padding: clamp(24px, 6vw, 36px);
    }}

    h1 {{
      margin: 0;
      font-size: clamp(28px, 8vw, 42px);
      line-height: 0.96;
      letter-spacing: -0.045em;
    }}

    p {{
      color: var(--muted);
      line-height: 1.55;
      margin: 14px 0 24px;
    }}

    label {{
      display: block;
      font-size: 14px;
      font-weight: 720;
      margin-bottom: 8px;
    }}

    input {{
      width: 100%;
      min-height: 52px;
      border-radius: 16px;
      border: 1px solid var(--line);
      background: #fdfdfc;
      color: var(--text);
      font-size: 17px;
      padding: 0 15px;
      outline: none;
    }}

    input:focus {{
      border-color: rgba(37, 99, 235, 0.72);
      box-shadow: 0 0 0 4px rgba(37, 99, 235, 0.1);
    }}

    button {{
      width: 100%;
      min-height: 52px;
      margin-top: 14px;
      border: 0;
      border-radius: 16px;
      background: var(--blue);
      color: #f8fafc;
      font-weight: 760;
      font-size: 15px;
      cursor: pointer;
      transition: transform 160ms ease, background 160ms ease;
    }}

    button:hover {{ background: var(--blue-dark); }}
    button:active {{ transform: translateY(1px) scale(0.99); }}

    .login-error {{
      border-radius: 16px;
      border: 1px solid rgba(180, 35, 24, 0.18);
      background: var(--red-bg);
      color: var(--red);
      padding: 12px 14px;
      margin-bottom: 16px;
      font-weight: 650;
    }}
  </style>
</head>
<body>
  <main class="login">
    <h1>Вход в панель</h1>
    <p>Введите пароль администратора, чтобы открыть управление базой товаров AMIX.</p>
    {error_html}
    <form method="post" action="/admin/login">
      <input type="hidden" name="next" value="{escape(next_path)}">
      <label for="password">Пароль</label>
      <input id="password" name="password" type="password" autocomplete="current-password" autofocus required>
      <button type="submit">Войти</button>
    </form>
  </main>
</body>
</html>"""


def _render_admin_page(*, stats: dict[str, str], flash_message: str) -> str:
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AMIX AI бот</title>
  <style>
    :root {{
      --page: #f3f4f6;
      --surface: #fbfbfa;
      --surface-strong: #f7f7f5;
      --text: #1d232b;
      --muted: #657080;
      --line: #d8dde5;
      --blue: #2563eb;
      --blue-dark: #1d4ed8;
      --green: #167c4a;
      --green-bg: #e7f5ed;
      --red: #b42318;
      --red-bg: #fff0ed;
      --shadow: 0 24px 70px rgba(31, 41, 55, 0.08);
    }}

    * {{
      box-sizing: border-box;
    }}

    body {{
      margin: 0;
      background:
        radial-gradient(circle at top left, rgba(37, 99, 235, 0.08), transparent 34rem),
        var(--page);
      color: var(--text);
      font-family: "Manrope", "Aptos", "Segoe UI", sans-serif;
      min-height: 100dvh;
    }}

    .page {{
      width: min(100% - 32px, 980px);
      margin: 0 auto;
      padding: 44px 0 56px;
    }}

    .topbar {{
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 20px;
      margin-bottom: 28px;
    }}

    h1 {{
      margin: 0;
      font-size: clamp(30px, 5vw, 48px);
      line-height: 0.96;
      letter-spacing: -0.045em;
      font-weight: 760;
    }}

    .subtitle {{
      color: var(--muted);
      margin-top: 12px;
      max-width: 54ch;
      font-size: 16px;
      line-height: 1.55;
    }}

    .status-area {{
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }}

    .status-pill {{
      display: inline-flex;
      align-items: center;
      gap: 9px;
      white-space: nowrap;
      border-radius: 999px;
      border: 1px solid rgba(22, 124, 74, 0.2);
      background: var(--green-bg);
      color: var(--green);
      padding: 10px 14px;
      font-weight: 700;
      font-size: 14px;
    }}

    .logout-form {{
      margin: 0;
    }}

    .logout-button {{
      border: 1px solid var(--line);
      background: rgba(251, 251, 250, 0.78);
      color: var(--muted);
      border-radius: 999px;
      min-height: 39px;
      padding: 0 13px;
      cursor: pointer;
      font-weight: 700;
      transition: transform 160ms ease, background 160ms ease;
    }}

    .logout-button:hover {{
      background: #e7ebf1;
    }}

    .status-dot {{
      width: 9px;
      height: 9px;
      border-radius: 999px;
      background: var(--green);
      box-shadow: 0 0 0 5px rgba(22, 124, 74, 0.11);
    }}

    .stats {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-bottom: 18px;
    }}

    .stat {{
      background: rgba(251, 251, 250, 0.74);
      border: 1px solid var(--line);
      border-radius: 24px;
      padding: 20px;
    }}

    .stat-label {{
      color: var(--muted);
      font-size: 14px;
      margin-bottom: 8px;
    }}

    .stat-value {{
      font-size: clamp(22px, 4vw, 32px);
      line-height: 1;
      letter-spacing: -0.035em;
      font-weight: 760;
    }}

    .stat-note {{
      margin-top: 8px;
      color: var(--muted);
      font-size: 13px;
    }}

    .panel {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 32px;
      box-shadow: var(--shadow);
      padding: clamp(22px, 5vw, 38px);
    }}

    .panel-head {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 20px;
      padding-bottom: 26px;
      border-bottom: 1px solid var(--line);
    }}

    h2 {{
      margin: 0 0 8px;
      font-size: clamp(24px, 4vw, 34px);
      line-height: 1.05;
      letter-spacing: -0.035em;
    }}

    .panel-text {{
      color: var(--muted);
      line-height: 1.55;
      margin: 0;
      max-width: 56ch;
    }}

    .xml-status {{
      border-radius: 18px;
      padding: 12px 14px;
      background: var(--surface-strong);
      border: 1px solid var(--line);
      min-width: 150px;
      text-align: right;
    }}

    .xml-status span {{
      display: block;
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 4px;
    }}

    .xml-status strong {{
      font-size: 15px;
    }}

    .actions {{
      display: grid;
      grid-template-columns: 0.86fr 1.14fr;
      gap: 14px;
      margin-top: 26px;
    }}

    .action-card {{
      border: 1px solid var(--line);
      border-radius: 26px;
      padding: 20px;
      background: var(--surface-strong);
    }}

    .action-title {{
      font-size: 18px;
      font-weight: 740;
      letter-spacing: -0.02em;
      margin-bottom: 8px;
    }}

    .action-note {{
      color: var(--muted);
      margin: 0 0 18px;
      line-height: 1.5;
      font-size: 14px;
    }}

    .button {{
      width: 100%;
      min-height: 50px;
      border: 0;
      border-radius: 16px;
      padding: 0 18px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-weight: 760;
      font-size: 15px;
      text-decoration: none;
      cursor: pointer;
      transition: transform 160ms ease, background 160ms ease;
    }}

    .button:active,
    .logout-button:active {{
      transform: translateY(1px) scale(0.99);
    }}

    .button-primary {{
      background: var(--blue);
      color: #f8fafc;
    }}

    .button-primary:hover {{
      background: var(--blue-dark);
    }}

    .button-secondary {{
      background: #e7ebf1;
      color: var(--text);
    }}

    .button-secondary:hover {{
      background: #dfe5ee;
    }}

    .remote-source {{
      color: var(--muted);
      font-size: 13px;
      line-height: 1.45;
      overflow-wrap: anywhere;
      margin-bottom: 14px;
    }}

    .action-divider {{
      height: 1px;
      background: var(--line);
      margin: 18px 0;
    }}

    .dropzone {{
      position: relative;
      display: grid;
      place-items: center;
      width: 100%;
      min-height: 120px;
      margin-bottom: 12px;
      border-radius: 20px;
      border: 1px dashed #aeb8c6;
      background: #fdfdfc;
      padding: 20px;
      color: var(--muted);
      text-align: center;
      overflow: hidden;
    }}

    .dropzone input[type="file"] {{
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      opacity: 0;
      cursor: pointer;
    }}

    .dropzone strong {{
      display: block;
      color: var(--text);
      font-size: 16px;
      margin-bottom: 5px;
    }}

    .dropzone span {{
      font-size: 13px;
    }}

    .selected-file {{
      display: block;
      min-height: 19px;
      margin: -2px 0 12px;
      color: var(--muted);
      font-size: 13px;
    }}

    .flash {{
      border-radius: 18px;
      padding: 14px 16px;
      margin-bottom: 18px;
      border: 1px solid;
      font-weight: 650;
    }}

    .flash-success {{
      background: var(--green-bg);
      color: var(--green);
      border-color: rgba(22, 124, 74, 0.22);
    }}

    .flash-error {{
      background: var(--red-bg);
      color: var(--red);
      border-color: rgba(180, 35, 24, 0.18);
    }}

    .footnote {{
      margin: 18px 4px 0;
      color: var(--muted);
      font-size: 13px;
    }}

    @media (max-width: 760px) {{
      .page {{
        width: min(100% - 22px, 520px);
        padding-top: 24px;
      }}

      .topbar,
      .panel-head {{
        display: block;
      }}

      .status-area,
      .xml-status {{
        margin-top: 18px;
        justify-content: flex-start;
      }}

      .xml-status {{
        text-align: left;
      }}

      .stats,
      .actions {{
        grid-template-columns: 1fr;
      }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <section class="topbar" aria-labelledby="page-title">
      <div>
        <h1 id="page-title">AMIX AI бот</h1>
        <div class="subtitle">Минимальная панель для проверки состояния сервиса и обновления товарной базы из XML.</div>
      </div>
      <div class="status-area">
        <div class="status-pill"><span class="status-dot"></span>{escape(stats["service_status"])}</div>
        <form class="logout-form" method="post" action="/admin/logout">
          <button class="logout-button" type="submit">Выйти</button>
        </form>
      </div>
    </section>

    {flash_message}

    <section class="stats" aria-label="Краткая информация">
      <div class="stat">
        <div class="stat-label">Товаров в базе</div>
        <div class="stat-value">{escape(stats["product_count"])}</div>
      </div>
      <div class="stat">
        <div class="stat-label">Последний импорт</div>
        <div class="stat-value">{escape(stats["latest_import"])}</div>
      </div>
      <div class="stat">
        <div class="stat-label">Диалогов сегодня</div>
        <div class="stat-value">{escape(stats["chats_today"])}</div>
      </div>
      <div class="stat">
        <div class="stat-label">Токенов LLM</div>
        <div class="stat-value">{escape(stats["llm_tokens"])}</div>
        <div class="stat-note">{escape(stats["llm_calls_label"])}</div>
      </div>
      <div class="stat">
        <div class="stat-label">Расход LLM</div>
        <div class="stat-value">{escape(stats["llm_cost_rub"])}</div>
      </div>
    </section>

    <section class="panel" aria-labelledby="products-title">
      <div class="panel-head">
        <div>
          <h2 id="products-title">База товаров</h2>
          <p class="panel-text">Скачайте текущую базу или загрузите свежую выгрузку из 1С. После загрузки бот будет искать товары уже по новым данным.</p>
        </div>
        <div class="xml-status">
          <span>XML</span>
          <strong>{escape(stats["xml_status"])}</strong>
        </div>
      </div>

      <div class="actions">
        <article class="action-card">
          <div class="action-title">Текущая база</div>
          <p class="action-note">Экспорт товаров, которые сейчас сохранены в сервисе.</p>
          <a class="button button-secondary" href="/admin/products.xml">Скачать текущую базу</a>
        </article>

        <article class="action-card">
          <div class="action-title">Новая выгрузка</div>
          <p class="action-note">Основной источник теперь постоянная ссылка. Ручная загрузка остаётся запасным вариантом.</p>
          <div class="remote-source">
            Автообновление: {escape(stats["auto_import_status"])} · интервал {escape(stats["auto_import_interval"])}<br>
            Источник: {escape(stats["remote_url"])}
          </div>
          <form method="post" action="/admin/products/import-remote">
            <button class="button button-primary" type="submit">Обновить по ссылке</button>
          </form>
          <div class="action-divider"></div>
          <form method="post" action="/admin/products/import" enctype="multipart/form-data">
            <label class="dropzone">
              <input id="xml-file" name="file" type="file" accept=".xml,application/xml,text/xml" required>
              <span>
                <strong>Выберите файл или перенесите сюда</strong>
                <span>Подходит свежая XML-выгрузка из 1С</span>
              </span>
            </label>
            <span class="selected-file" id="selected-file">Файл ещё не выбран</span>
            <button class="button button-primary" type="submit">Загрузить XML</button>
          </form>
        </article>
      </div>
    </section>

    <p class="footnote">Последняя проверка: только что. Админ-доступ защищён паролем.</p>
  </main>
  <script>
    const fileInput = document.getElementById("xml-file");
    const selectedFile = document.getElementById("selected-file");
    fileInput?.addEventListener("change", () => {{
      selectedFile.textContent = fileInput.files?.[0]?.name || "Файл ещё не выбран";
    }});
  </script>
</body>
</html>"""
