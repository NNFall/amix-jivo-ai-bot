from datetime import UTC, datetime, time
from decimal import Decimal
from html import escape
from pathlib import Path
import re
import secrets
from xml.etree.ElementTree import Element, SubElement, tostring

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import func, select

from database.db import session_scope
from database.models import Chat, Product, ProductImport
from products.xml_importer import ProductXmlImporter
from settings import BASE_DIR, get_settings


router = APIRouter(tags=["admin"])
security = HTTPBasic()


def require_admin(credentials: HTTPBasicCredentials = Depends(security)) -> None:
    settings = get_settings()
    username_ok = secrets.compare_digest(credentials.username, settings.admin_username)
    password_ok = secrets.compare_digest(credentials.password, settings.admin_password)
    if not username_ok or not password_ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin credentials",
            headers={"WWW-Authenticate": "Basic"},
        )


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


def _load_admin_stats() -> dict[str, str]:
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

    return {
        "service_status": "Бот работает",
        "product_count": _format_int(product_count),
        "chats_today": _format_int(chats_today),
        "latest_import": _format_datetime(latest_import.finished_at if latest_import else None),
        "xml_status": "актуальна" if latest_import else "ещё не загружена",
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


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return "нет данных"
    return value.strftime("%d.%m.%Y %H:%M")


def _build_upload_filename(filename: str) -> str:
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(filename).name).strip("._")
    if not safe_name:
        safe_name = "products.xml"
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"{timestamp}-{safe_name}"


def _build_flash_message(import_status: str | None, error: str | None) -> str:
    if import_status == "ok":
        return '<div class="flash flash-success">XML загружен, база товаров обновлена.</div>'

    errors = {
        "empty_filename": "Не удалось определить имя файла.",
        "not_xml": "Загрузите файл в формате XML.",
        "import_failed": "Импорт не завершился. Проверьте XML-файл.",
    }
    if error:
        return f'<div class="flash flash-error">{escape(errors.get(error, "Не удалось загрузить файл."))}</div>'
    return ""


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

    .status-dot {{
      width: 9px;
      height: 9px;
      border-radius: 999px;
      background: var(--green);
      box-shadow: 0 0 0 5px rgba(22, 124, 74, 0.11);
    }}

    .stats {{
      display: grid;
      grid-template-columns: 1.05fr 1fr 0.82fr;
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

    .button:active {{
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

    input[type="file"] {{
      display: block;
      width: 100%;
      margin-bottom: 12px;
      border-radius: 16px;
      border: 1px dashed #b8c0cc;
      background: #fdfdfc;
      padding: 16px;
      color: var(--muted);
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

      .status-pill,
      .xml-status {{
        margin-top: 18px;
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
      <div class="status-pill"><span class="status-dot"></span>{escape(stats["service_status"])}</div>
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
          <p class="action-note">Файл XML из 1С. Обработка запускается сразу после загрузки.</p>
          <form method="post" action="/admin/products/import" enctype="multipart/form-data">
            <input name="file" type="file" accept=".xml,application/xml,text/xml" aria-label="Выберите XML-файл" required>
            <button class="button button-primary" type="submit">Загрузить XML</button>
          </form>
        </article>
      </div>
    </section>

    <p class="footnote">Последняя проверка: только что. Админ-доступ защищён паролем.</p>
  </main>
</body>
</html>"""
