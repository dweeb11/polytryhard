from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from core.domain.feature import FeatureValue
from core.settings import Settings


@dataclass
class FeatureContext:
    request_id: str
    settings: Settings
    session: Session


class FeatureProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def version(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def is_enabled(self, settings: Settings) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def compute(self, as_of: datetime, ctx: FeatureContext) -> list[FeatureValue]:
        raise NotImplementedError
