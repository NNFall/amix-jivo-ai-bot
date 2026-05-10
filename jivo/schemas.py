from pydantic import BaseModel, ConfigDict, Field


class JivoButton(BaseModel):
    id: str | int | None = None
    text: str

    model_config = ConfigDict(extra="allow")


class JivoChannel(BaseModel):
    id: str | None = None
    type: str | None = None

    model_config = ConfigDict(extra="allow")


class JivoSender(BaseModel):
    id: str | int | None = None
    name: str | None = None
    avatar: str | None = None
    url: str | None = None
    email: str | None = None
    phone: str | None = None
    user_token: str | None = None
    has_contacts: bool | None = None

    model_config = ConfigDict(extra="allow")


class JivoMessage(BaseModel):
    type: str = "TEXT"
    text: str | None = None
    title: str | None = None
    content: str | None = None
    force_reply: bool | None = None
    file: str | None = None
    file_name: str | None = None
    file_size: int | None = None
    thumb: str | None = None
    buttons: list[JivoButton] | None = None
    timestamp: int | None = None

    model_config = ConfigDict(extra="allow")


class JivoIncomingEvent(BaseModel):
    id: str
    event: str
    chat_id: str
    client_id: str
    site_id: str | None = None
    message: JivoMessage | None = None
    sender: JivoSender | None = None
    channel: JivoChannel | None = None
    agents_online: bool | None = Field(default=None, alias="agentsOnline")

    model_config = ConfigDict(extra="allow", populate_by_name=True)
