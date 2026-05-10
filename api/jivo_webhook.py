import secrets
from json import JSONDecodeError

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from pydantic import ValidationError

from core.message_processor import process_event_record
from database.db import session_scope
from database.repositories import create_event_if_new
from jivo.schemas import JivoIncomingEvent
from settings import get_settings


router = APIRouter(prefix="/webhooks", tags=["jivo"])


@router.post("/jivo/{bot_token}")
async def handle_jivo_webhook(
    bot_token: str,
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict[str, bool]:
    settings = get_settings()

    if not secrets.compare_digest(bot_token, settings.jivo_webhook_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid webhook token")

    try:
        payload = await request.json()
    except JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON payload") from exc

    try:
        event = JivoIncomingEvent.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    with session_scope() as session:
        event_record, created = create_event_if_new(session, event)

    if created:
        background_tasks.add_task(process_event_record, event_record.id)

    return {"ok": True, "accepted": created, "duplicate": not created}
