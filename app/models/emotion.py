from pydantic import BaseModel, Field, ConfigDict

class EmotionCreate(BaseModel):
    name: str = Field(..., min_length=1, description="Mindset profile tag")

class EmotionResponse(EmotionCreate):
    id: str = Field(..., alias="id")

    model_config = ConfigDict(populate_by_name=True)
