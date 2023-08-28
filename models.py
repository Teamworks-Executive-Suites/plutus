from pydantic import BaseModel
from devtools import debug


class Name(BaseModel):
    name: str

class Dispute(BaseModel):
    ref: str
    category: str
    reason: str
    amount: float