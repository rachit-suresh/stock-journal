from pydantic import BaseModel, Field

class StrategyCreate(BaseModel):
    name: str = Field(..., min_length=1, description="Strategy name tag")
