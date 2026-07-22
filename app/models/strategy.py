from pydantic import BaseModel, Field, ConfigDict

class StrategyCreate(BaseModel):
    name: str = Field(..., min_length=1, description="Strategy name tag")

class StrategyResponse(StrategyCreate):
    id: str = Field(..., alias="id")

    model_config = ConfigDict(populate_by_name=True)
