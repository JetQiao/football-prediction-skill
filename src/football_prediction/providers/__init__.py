"""外部数据源适配器。"""

from .base import ProviderError
from .sporttery import SportteryProvider

__all__ = ["ProviderError", "SportteryProvider"]
