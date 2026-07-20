from datetime import UTC, datetime
import re

from sqlalchemy import and_, delete, or_, select, update

from database.models import (
    Chat,
    Customer,
    Handoff,
    JivoEvent,
    LLMCall,
    Message,
    ProcessingError,
    Product,
    ProductImport,
)
from products.article_utils import build_normalized_article_variants, normalize_article


DESCRIPTION_TOKEN_RE = re.compile(r"[0-9A-Za-zА-Яа-яЁё]+")


def _description_tokens(query: str) -> list[str]:
    tokens: list[str] = []
    for raw_token in DESCRIPTION_TOKEN_RE.findall(query):
        token = normalize_article(raw_token)
        if len(token) < 2 or token in tokens:
            continue
        tokens.append(token)
    return tokens


def create_event_if_new(session, event):
    existing = session.scalar(
        select(JivoEvent).where(JivoEvent.external_event_id == event.id)
    )
    if existing is not None:
        if existing.status == "failed":
            existing.status = "received"
            existing.error_text = None
            existing.payload = event.model_dump(mode="json")
            session.add(existing)
            session.flush()
            return existing, True
        return existing, False

    entity = JivoEvent(
        external_event_id=event.id,
        external_chat_id=event.chat_id,
        external_client_id=event.client_id,
        event_type=event.event,
        payload=event.model_dump(mode="json"),
    )
    session.add(entity)
    session.flush()
    return entity, True


def get_stored_event(session, event_record_id: int) -> JivoEvent | None:
    return session.get(JivoEvent, event_record_id)


def list_unfinished_event_ids(session) -> list[int]:
    return list(
        session.scalars(
            select(JivoEvent.id)
            .where(JivoEvent.status.in_({"received", "processing"}))
            .order_by(JivoEvent.id.asc())
        ).all()
    )


def mark_event_processing(session, event_record: JivoEvent) -> None:
    event_record.status = "processing"
    event_record.error_text = None
    session.add(event_record)


def mark_event_processed(session, event_record: JivoEvent) -> None:
    event_record.status = "processed"
    session.add(event_record)


def mark_event_superseded(session, event_record: JivoEvent) -> None:
    event_record.status = "superseded"
    session.add(event_record)


def mark_event_failed(session, event_record: JivoEvent, error_text: str) -> None:
    event_record.status = "failed"
    event_record.error_text = error_text
    session.add(event_record)


def get_or_create_customer(session, external_client_id: str, name: str | None = None) -> Customer:
    entity = session.scalar(
        select(Customer).where(Customer.external_client_id == external_client_id)
    )
    if entity is None:
        entity = Customer(external_client_id=external_client_id, name=name)
        session.add(entity)
        session.flush()
        return entity

    if name and not entity.name:
        entity.name = name
        session.add(entity)

    return entity


def get_or_create_chat(session, external_chat_id: str, customer_id: int) -> Chat:
    entity = session.scalar(select(Chat).where(Chat.external_chat_id == external_chat_id))
    if entity is None:
        entity = Chat(external_chat_id=external_chat_id, customer_id=customer_id, status="active")
        session.add(entity)
        session.flush()
        return entity
    return entity


def get_chat_by_external_id(session, external_chat_id: str) -> Chat | None:
    return session.scalar(select(Chat).where(Chat.external_chat_id == external_chat_id))


def mark_chat_status(session, external_chat_id: str, status: str) -> None:
    entity = session.scalar(select(Chat).where(Chat.external_chat_id == external_chat_id))
    if entity is None:
        return

    entity.status = status
    session.add(entity)


def mark_chat_handoff_requested_if_not_terminal(session, external_chat_id: str) -> bool:
    result = session.execute(
        update(Chat)
        .where(
            Chat.external_chat_id == external_chat_id,
            Chat.status.notin_({"agent_joined", "closed"}),
        )
        .values(status="handoff_requested")
        .execution_options(synchronize_session="fetch")
    )
    return bool(result.rowcount)


def reset_chat_context(session, external_chat_id: str) -> int:
    chat = session.scalar(select(Chat).where(Chat.external_chat_id == external_chat_id))
    if chat is None:
        return 0

    deleted_messages = session.execute(delete(Message).where(Message.chat_id == chat.id)).rowcount or 0
    session.execute(delete(Handoff).where(Handoff.external_chat_id == external_chat_id))
    chat.status = "active"
    session.add(chat)
    session.flush()
    return int(deleted_messages)


def create_llm_call(
    session,
    *,
    external_chat_id: str | None,
    request_id: str,
    provider: str,
    model: str | None,
    purpose: str,
    status: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    thinking_tokens: int | None,
    total_tokens: int | None,
    latency_ms: int | None,
    estimated_usd,
    estimated_rub,
    outbound_event_id: str | None,
) -> LLMCall:
    chat = get_chat_by_external_id(session, external_chat_id) if external_chat_id else None
    entity = LLMCall(
        chat_id=chat.id if chat else None,
        request_id=request_id,
        provider=provider,
        model=model,
        purpose=purpose,
        status=status,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        thinking_tokens=thinking_tokens,
        total_tokens=total_tokens,
        latency_ms=latency_ms,
        estimated_usd=estimated_usd,
        estimated_rub=estimated_rub,
        outbound_event_id=outbound_event_id,
    )
    session.add(entity)
    session.flush()
    return entity


def append_message(
    session,
    external_chat_id: str,
    sender_role: str,
    text: str,
    external_event_id: str | None = None,
    payload: dict | None = None,
):
    chat = session.scalar(select(Chat).where(Chat.external_chat_id == external_chat_id))
    if chat is None:
        raise ValueError(f"Chat {external_chat_id} is not registered")

    entity = Message(
        chat_id=chat.id,
        external_event_id=external_event_id,
        sender_role=sender_role,
        text=text,
        payload=payload or {},
    )
    session.add(entity)
    session.flush()
    return entity


def message_exists_by_external_event_id(session, external_event_id: str) -> bool:
    return session.scalar(
        select(Message.id).where(Message.external_event_id == external_event_id).limit(1)
    ) is not None


def list_messages(session, external_chat_id: str) -> list[Message]:
    chat = session.scalar(select(Chat).where(Chat.external_chat_id == external_chat_id))
    if chat is None:
        return []

    return list(
        session.scalars(
            select(Message)
            .where(Message.chat_id == chat.id)
            .order_by(Message.created_at.asc(), Message.id.asc())
        ).all()
    )


def delete_generated_messages_for_turn(
    session,
    external_chat_id: str,
    turn_id: str,
    *,
    bot_only: bool = False,
) -> int:
    deleted = 0
    for message in list_messages(session, external_chat_id):
        payload = message.payload or {}
        belongs_to_turn = message.external_event_id == turn_id or payload.get("turn_id") == turn_id
        if belongs_to_turn and (not bot_only or message.sender_role == "bot"):
            session.delete(message)
            deleted += 1
    session.flush()
    return deleted


def list_recent_messages(session, external_chat_id: str, limit: int = 20) -> list[Message]:
    chat = session.scalar(select(Chat).where(Chat.external_chat_id == external_chat_id))
    if chat is None:
        return []

    rows = session.scalars(
        select(Message)
        .where(Message.chat_id == chat.id)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(limit)
    ).all()
    return list(reversed(rows))


def create_handoff(session, external_chat_id: str, reason: str) -> Handoff:
    entity = Handoff(external_chat_id=external_chat_id, reason=reason)
    session.add(entity)
    session.flush()
    return entity


def log_processing_error(
    session,
    external_event_id: str,
    scope: str,
    error_text: str,
    payload: dict,
) -> ProcessingError:
    entity = ProcessingError(
        external_event_id=external_event_id,
        scope=scope,
        error_text=error_text,
        payload=payload,
    )
    session.add(entity)
    session.flush()
    return entity


def upsert_product(
    session,
    *,
    code: str | None,
    article: str,
    normalized_article: str,
    corporate_price,
    retail_price,
    unit: str | None,
    weight,
    volume,
    free_stock,
    raw_payload: dict,
):
    entity = None
    if code:
        entity = session.scalar(select(Product).where(Product.code == code))
    if entity is None and not code and normalized_article:
        entity = session.scalar(
            select(Product).where(Product.normalized_article == normalized_article)
        )

    created = entity is None
    if entity is None:
        entity = Product(
            code=code,
            article=article,
            normalized_article=normalized_article,
            corporate_price=corporate_price,
            retail_price=retail_price,
            unit=unit,
            weight=weight,
            volume=volume,
            free_stock=free_stock,
            raw_payload=raw_payload,
        )
        session.add(entity)
        session.flush()
        return entity, created

    entity.code = code or entity.code
    entity.article = article
    entity.normalized_article = normalized_article
    entity.corporate_price = corporate_price
    entity.retail_price = retail_price
    entity.unit = unit
    entity.weight = weight
    entity.volume = volume
    entity.free_stock = free_stock
    entity.raw_payload = raw_payload
    entity.updated_at = datetime.now(UTC)
    session.add(entity)
    session.flush()
    return entity, created


def lookup_products(session, query: str, exact_limit: int = 20, similar_limit: int = 20) -> tuple[list[Product], list[Product]]:
    query_clean = (query or "").strip()
    if not query_clean:
        return [], []

    variants = build_normalized_article_variants(query_clean)
    exact_clauses = [Product.code == query_clean]
    if variants:
        exact_clauses.append(Product.normalized_article.in_(variants))

    exact_matches = session.scalars(
        select(Product).where(or_(*exact_clauses)).order_by(Product.article.asc(), Product.code.asc()).limit(exact_limit)
    ).all()

    description_tokens = _description_tokens(query_clean)
    if not exact_matches and len(description_tokens) >= 3:
        exact_matches = session.scalars(
            select(Product)
            .where(
                and_(
                    *(Product.normalized_article.like(f"%{token}%") for token in description_tokens)
                )
            )
            .order_by(Product.article.asc(), Product.code.asc())
            .limit(exact_limit)
        ).all()

    exact_ids = {product.id for product in exact_matches}
    similar_clauses = []
    for variant in variants:
        token = variant[:6] or variant
        if token:
            similar_clauses.append(Product.normalized_article.like(f"%{token}%"))

    if query_clean:
        similar_clauses.append(Product.code.like(f"%{query_clean}%"))

    if not similar_clauses:
        return exact_matches, []

    similar_all = session.scalars(
        select(Product).where(or_(*similar_clauses)).order_by(Product.article.asc(), Product.code.asc()).limit(similar_limit * 3)
    ).all()

    similar_matches: list[Product] = []
    for product in similar_all:
        if product.id in exact_ids:
            continue
        similar_matches.append(product)
        if len(similar_matches) >= similar_limit:
            break

    return exact_matches, similar_matches


def search_products_structured(
    session,
    *,
    query: str,
    exact_limit: int = 20,
    similar_limit: int = 20,
) -> dict:
    query_raw = (query or "").strip().strip(".,;:!?\"'«»")

    result = {
        "query": query_raw,
        "status": "invalid_query",
        "exact_matches_count": 0,
        "similar_matches_count": 0,
        "exact_matches": [],
        "similar_matches": [],
    }
    if not query_raw:
        return result

    exact_matches, similar_matches = lookup_products(
        session,
        query=query_raw,
        exact_limit=exact_limit,
        similar_limit=similar_limit,
    )
    exact_ids = {product.id for product in exact_matches}
    strict_similar = [product for product in similar_matches if product.id not in exact_ids]

    result["exact_matches"] = [_serialize_product(product) for product in exact_matches]
    result["similar_matches"] = [_serialize_product(product) for product in strict_similar]
    result["exact_matches_count"] = len(result["exact_matches"])
    result["similar_matches_count"] = len(result["similar_matches"])

    if result["exact_matches_count"] == 1:
        result["status"] = "exact_found"
    elif result["exact_matches_count"] > 1:
        result["status"] = "multiple_exact"
    elif result["similar_matches_count"] > 0:
        result["status"] = "similar_found"
    else:
        result["status"] = "not_found"

    return result


def _serialize_product(product: Product) -> dict:
    return {
        "code": product.code,
        "article": product.article,
        "retail_price": str(product.retail_price) if product.retail_price is not None else None,
        "retail_price_display": _format_price_display(product.retail_price),
        "corporate_price": str(product.corporate_price) if product.corporate_price is not None else None,
        "corporate_price_display": _format_price_display(product.corporate_price),
        "unit": product.unit,
        "weight": str(product.weight) if product.weight is not None else None,
        "volume": str(product.volume) if product.volume is not None else None,
        "stock": str(product.free_stock) if product.free_stock is not None else None,
    }


def _format_price_display(value) -> str | None:
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    if "." in text:
        whole, fraction = text.split(".", 1)
        fraction = fraction.rstrip("0")
        whole = _group_price_whole(whole)
        if fraction:
            return f"{whole},{fraction} руб."
        return f"{whole} руб."
    return f"{text} руб."


def _group_price_whole(value: str) -> str:
    stripped = value.strip().replace(" ", "")
    if not stripped.isdigit():
        return value
    return f"{int(stripped):,}".replace(",", " ")


def create_product_import(session, filename: str, source_path: str) -> ProductImport:
    entity = ProductImport(filename=filename, source_path=source_path, status="started")
    session.add(entity)
    session.flush()
    return entity


def finish_product_import(
    session,
    product_import: ProductImport,
    *,
    status: str,
    imported_count: int,
    updated_count: int,
    error_count: int,
    error_text: str | None = None,
) -> None:
    product_import.status = status
    product_import.imported_count = imported_count
    product_import.updated_count = updated_count
    product_import.error_count = error_count
    product_import.error_text = error_text
    product_import.finished_at = datetime.now(UTC)
    session.add(product_import)
