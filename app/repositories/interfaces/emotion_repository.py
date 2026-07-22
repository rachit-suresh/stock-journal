from abc import ABC, abstractmethod
from typing import List

class IEmotionRepository(ABC):
    @abstractmethod
    async def get_all_emotions(self) -> List[str]:
        """Fetch all mindset/emotion profile names."""
        pass

    @abstractmethod
    async def add_emotion(self, name: str) -> bool:
        """Add a new mindset profile."""
        pass

    @abstractmethod
    async def delete_emotion(self, name: str) -> bool:
        """Delete a mindset profile by name."""
        pass

    @abstractmethod
    async def reset_emotions(self, emotions: List[str]) -> None:
        """Bulk replace all mindset tags."""
        pass
