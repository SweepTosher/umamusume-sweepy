from pydantic import BaseModel


class AddPresetRequest(BaseModel):
    preset: str

class DeletePresetRequest(BaseModel):
    name: str



