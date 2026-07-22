from abc import ABC, abstractmethod

class IMarketDataStreamer(ABC):
    @abstractmethod
    def authenticate(self) -> bool:
        """Execute daily session authentication."""
        pass

    @abstractmethod
    def connect_and_stream(self, tokens: list[str]) -> None:
        """Connect WebSocket stream and listen for ticks."""
        pass

    @abstractmethod
    def on_tick_received(self, token: str, ltp: float) -> None:
        """Process incoming price tick."""
        pass
