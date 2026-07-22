from pydantic import BaseModel, Field

class EmotionCreate(BaseModel):
    name: str = Field(..., min_length=1, description="Mindset profile tag")
