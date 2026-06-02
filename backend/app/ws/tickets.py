"""In-memory single-use WS upgrade tickets (30s TTL)."""
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Ticket:
    user_id: str
    expires_at: float  # monotonic time


class TicketStore:
    def __init__(self) -> None:
        self._store: dict[str, Ticket] = {}
        self._lock = threading.Lock()

    def issue(self, user_id: str) -> str:
        ticket_id = str(uuid.uuid4())
        expires_at = time.monotonic() + 30
        with self._lock:
            self._store[ticket_id] = Ticket(user_id=user_id, expires_at=expires_at)
        return ticket_id

    def consume(self, ticket_id: str) -> str | None:
        """Return user_id and delete the ticket (single-use). None if invalid/expired."""
        with self._lock:
            ticket = self._store.pop(ticket_id, None)
        if ticket is None:
            return None
        if time.monotonic() > ticket.expires_at:
            return None
        return ticket.user_id

    def sweep_expired(self) -> None:
        now = time.monotonic()
        with self._lock:
            expired = [k for k, v in self._store.items() if now > v.expires_at]
            for k in expired:
                del self._store[k]


ticket_store = TicketStore()
