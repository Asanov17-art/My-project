"""Light-weight views over the affiliate API's JSON payloads.

The gateway returns loosely typed JSON whose field names drift between API
versions, so every model keeps the original dictionary in ``raw`` and only
promotes the fields worth having autocomplete for.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence


def _collection_keys(key: str) -> tuple[str, ...]:
    """Names a collection of ``key`` elements can hide behind.

    ``category`` is the awkward one: the wrapper is ``categories``, not
    ``categorys``, so the English plural rule is applied explicitly.
    """
    plural = f"{key[:-1]}ies" if key.endswith("y") else f"{key}s"
    return (key, plural, f"{key}_list")


def unpack_list(container: Any, key: str) -> list[dict[str, Any]]:
    """Read a list out of AliExpress' inconsistent collection shapes.

    Depending on the method and on ``simplify``, a collection arrives as
    ``{"products": {"product": [...]}}``, as ``{"products": [...]}``, or as a
    bare list, and a lone element is sometimes returned unwrapped. Pass the
    container the collection lives in (or ``None``) and the singular element
    name; the result is always a list of plain dictionaries.
    """
    if container is None:
        return []
    if isinstance(container, Mapping):
        for candidate in _collection_keys(key):
            if candidate in container:
                return unpack_list(container[candidate], key)
        # No collection key in sight: the mapping is the single element itself.
        return [dict(container)] if container else []
    if isinstance(container, Sequence) and not isinstance(container, (str, bytes)):
        return [dict(item) for item in container if isinstance(item, Mapping)]
    return []


def _first(source: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in source and source[name] not in (None, ""):
            return source[name]
    return None


def _as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


@dataclass(slots=True)
class Product:
    """A product as returned by the search, hot-product and detail methods."""

    product_id: str | None
    title: str | None
    sale_price: float | None
    original_price: float | None
    currency: str | None
    discount: str | None
    rating: float | None
    orders: int | None
    image_url: str | None
    product_url: str | None
    promotion_link: str | None
    shop_name: str | None
    shop_url: str | None
    category_id: int | None
    commission_rate: str | None
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> "Product":
        return cls(
            product_id=_first(data, "product_id", "productId"),
            title=_first(data, "product_title", "productTitle"),
            sale_price=_as_float(_first(data, "target_sale_price", "sale_price", "app_sale_price")),
            original_price=_as_float(
                _first(data, "target_original_price", "original_price")
            ),
            currency=_first(
                data, "target_sale_price_currency", "sale_price_currency", "original_price_currency"
            ),
            discount=_first(data, "discount"),
            rating=_as_float(_first(data, "evaluate_rate", "product_rating")),
            orders=_as_int(_first(data, "lastest_volume", "latest_volume", "volume")),
            image_url=_first(data, "product_main_image_url", "product_small_image_urls"),
            product_url=_first(data, "product_detail_url", "product_url"),
            promotion_link=_first(data, "promotion_link"),
            shop_name=_first(data, "shop_name", "store_name"),
            shop_url=_first(data, "shop_url", "store_url"),
            category_id=_as_int(_first(data, "second_level_category_id", "first_level_category_id")),
            commission_rate=_first(data, "commission_rate", "hot_product_commission_rate"),
            raw=dict(data),
        )


@dataclass(slots=True)
class ProductPage:
    """One page of product results plus its pagination counters."""

    products: list[Product]
    current_page_no: int | None
    page_size: int | None
    total_record_count: int | None
    total_page_no: int | None
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    def __iter__(self) -> Iterable[Product]:
        return iter(self.products)

    def __len__(self) -> int:
        return len(self.products)

    @property
    def has_next_page(self) -> bool:
        if self.current_page_no is None:
            return False
        if self.total_page_no is not None:
            return self.current_page_no < self.total_page_no
        return bool(self.products)

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> "ProductPage":
        items = unpack_list(_first(data, "products", "product"), "product")
        return cls(
            products=[Product.from_api(item) for item in items],
            current_page_no=_as_int(data.get("current_page_no")),
            page_size=_as_int(_first(data, "current_record_count", "page_size")),
            total_record_count=_as_int(data.get("total_record_count")),
            total_page_no=_as_int(data.get("total_page_no")),
            raw=dict(data),
        )


@dataclass(slots=True)
class PromotionLink:
    """A tracked affiliate link generated for one source URL."""

    source_value: str | None
    promotion_link: str | None
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> "PromotionLink":
        return cls(
            source_value=_first(data, "source_value"),
            promotion_link=_first(data, "promotion_link"),
            raw=dict(data),
        )


@dataclass(slots=True)
class Category:
    """A product category, either top level or a child of one."""

    category_id: int | None
    category_name: str | None
    parent_category_id: int | None
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @property
    def is_top_level(self) -> bool:
        return self.parent_category_id is None

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> "Category":
        return cls(
            category_id=_as_int(data.get("category_id")),
            category_name=_first(data, "category_name"),
            parent_category_id=_as_int(data.get("parent_category_id")),
            raw=dict(data),
        )


@dataclass(slots=True)
class Order:
    """One affiliate order with the commission fields that matter for payouts."""

    order_id: str | None
    product_id: str | None
    product_title: str | None
    order_status: str | None
    paid_time: str | None
    commission_rate: str | None
    estimated_paid_commission: float | None
    paid_amount: float | None
    currency: str | None
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> "Order":
        return cls(
            order_id=_first(data, "order_id", "child_order_id"),
            product_id=_first(data, "product_id"),
            product_title=_first(data, "product_title"),
            order_status=_first(data, "order_status", "child_order_status"),
            paid_time=_first(data, "paid_time"),
            commission_rate=_first(data, "commission_rate"),
            estimated_paid_commission=_as_float(
                _first(data, "estimated_paid_commission", "new_buyer_bonus_commission")
            ),
            paid_amount=_as_float(_first(data, "paid_amount", "order_amount")),
            currency=_first(data, "paid_amount_currency", "order_amount_currency"),
            raw=dict(data),
        )


@dataclass(slots=True)
class OrderPage:
    """One page of affiliate orders."""

    orders: list[Order]
    current_page_no: int | None
    total_record_count: int | None
    total_page_no: int | None
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    def __iter__(self) -> Iterable[Order]:
        return iter(self.orders)

    def __len__(self) -> int:
        return len(self.orders)

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> "OrderPage":
        items = unpack_list(_first(data, "orders", "order"), "order")
        return cls(
            orders=[Order.from_api(item) for item in items],
            current_page_no=_as_int(data.get("current_page_no")),
            total_record_count=_as_int(data.get("total_record_count")),
            total_page_no=_as_int(data.get("total_page_no")),
            raw=dict(data),
        )
