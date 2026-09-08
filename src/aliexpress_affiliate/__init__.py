"""A small, dependency-light client for the AliExpress Affiliate API."""

from .affiliate import AffiliateClient, format_order_time
from .client import ClientConfig, RequestsTransport, TopClient, unwrap_result
from .errors import (
    AliExpressError,
    ApiError,
    BusinessError,
    ConfigurationError,
    RateLimitError,
    TransportError,
)
from .models import (
    Category,
    Order,
    OrderPage,
    Product,
    ProductPage,
    PromotionLink,
)
from .signing import sign

__version__ = "0.1.0"

__all__ = [
    "AffiliateClient",
    "AliExpressError",
    "ApiError",
    "BusinessError",
    "Category",
    "ClientConfig",
    "ConfigurationError",
    "Order",
    "OrderPage",
    "Product",
    "ProductPage",
    "PromotionLink",
    "RateLimitError",
    "RequestsTransport",
    "TopClient",
    "TransportError",
    "__version__",
    "format_order_time",
    "sign",
    "unwrap_result",
]
