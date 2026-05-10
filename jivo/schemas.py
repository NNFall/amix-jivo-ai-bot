from pydantic import BaseModel, ConfigDict, Field


class JivoSender(BaseModel):
    id: str | int | None = None
    name: str | None = None
    avatar: str | None = None
    email: str | None = None
    phone: str | None = None

    model_config = ConfigDict(extra="allow")


class JivoMessage(BaseModel):
    type: str = "TEXT"
    text: str = ""
    timestamp: int | None = None

    model_config = ConfigDict(extra="allow")


class JivoIncomingEvent(BaseModel):
    id: str
    event: str
    chat_id: str
    client_id: str
    message: JivoMessage | None = None
    sender: JivoSender | None = None
    agents_online: bool | None = Field(default=None, alias="agentsOnline")

    model_config = ConfigDict(extra="allow", populate_by_name=True)
