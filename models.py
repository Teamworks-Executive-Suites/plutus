from pydantic import BaseModel


class Name(BaseModel):
    name: str

class Dispute(BaseModel):
    ref: str
    category: str
    reason: str
    amount: float