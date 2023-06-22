from pydantic import BaseModel

class Call(BaseModel):
    id: str or None = None
    trunk: str
    to_number: str
    from_number: str
    action_url: str
    status_callback: str