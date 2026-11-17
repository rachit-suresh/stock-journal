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

    def update_subscriptions(self, tokens: list[str]) -> bool:
        """Apply a new instrument set to an already-open connection."""
        return False

    def is_connected(self) -> bool:
        """Whether ticks are currently flowing."""
        return False
