"""High-level wrapper around the AliExpress Affiliate (Portals) API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterator, Mapping, Sequence

from .client import ClientConfig, TopClient, Transport, unwrap_result
from .errors import ConfigurationError
from .models import (
    Category,
    Order,
    OrderPage,
    Product,
    ProductPage,
    PromotionLink,
    unpack_list,
)
from .signing import GATEWAY_TZ

METHOD_PRODUCT_QUERY = "aliexpress.affiliate.product.query"
METHOD_HOTPRODUCT_QUERY = "aliexpress.affiliate.hotproduct.query"
METHOD_HOTPRODUCT_DOWNLOAD = "aliexpress.affiliate.hotproduct.download"
METHOD_PRODUCT_DETAIL = "aliexpress.affiliate.productdetail.get"
METHOD_LINK_GENERATE = "aliexpress.affiliate.link.generate"
METHOD_CATEGORY_GET = "aliexpress.affiliate.category.get"
METHOD_FEATUREDPROMO_GET = "aliexpress.affiliate.featuredpromo.get"
METHOD_FEATUREDPROMO_PRODUCTS = "aliexpress.affiliate.featuredpromo.products.get"
METHOD_ORDER_LIST = "aliexpress.affiliate.order.list"
METHOD_ORDER_LIST_BY_INDEX = "aliexpress.affiliate.order.listbyindex"
METHOD_ORDER_GET = "aliexpress.affiliate.order.get"

#: Fields requested by default for product searches. The API returns a much
#: smaller payload when ``fields`` is set, which keeps responses fast.
DEFAULT_PRODUCT_FIELDS = ",".join(
    [
        "product_id",
        "product_title",
        "product_main_image_url",
        "product_detail_url",
        "target_sale_price",
        "target_sale_price_currency",
        "target_original_price",
        "discount",
        "evaluate_rate",
        "lastest_volume",
        "commission_rate",
        "shop_name",
        "shop_url",
        "promotion_link",
        "first_level_category_id",
        "second_level_category_id",
    ]
)

DEFAULT_ORDER_FIELDS = ",".join(
    [
        "order_id",
        "product_id",
        "product_title",
        "order_status",
        "paid_time",
        "commission_rate",
        "estimated_paid_commission",
        "paid_amount",
        "paid_amount_currency",
    ]
)

#: The order APIs take timestamps in Beijing time.
_ORDER_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

#: The gateway rejects batches larger than this for both methods below.
MAX_PRODUCT_IDS_PER_CALL = 50
MAX_LINKS_PER_CALL = 50


def format_order_time(value: datetime | str) -> str:
    """Render ``value`` as ``yyyy-MM-dd HH:mm:ss`` in the gateway's timezone."""
    if isinstance(value, str):
        return value
    moment = value
    if moment.tzinfo is not None:
        moment = moment.astimezone(GATEWAY_TZ)
    return moment.strftime(_ORDER_TIME_FORMAT)


def _join_ids(values: Sequence[Any] | str, limit: int, label: str) -> str:
    items = [str(v).strip() for v in ([values] if isinstance(values, str) else values) if str(v).strip()]
    if not items:
        raise ConfigurationError(f"at least one {label} is required")
    if len(items) > limit:
        raise ConfigurationError(
            f"the API accepts at most {limit} {label}s per call, got {len(items)}"
        )
    return ",".join(items)


class AffiliateClient:
    """Typed access to the affiliate methods of the AliExpress Open Platform.

    ``tracking_id`` is the affiliate tracking id created in the Portals console.
    Every method accepts an explicit ``tracking_id`` override, so one client can
    serve several campaigns.
    """

    def __init__(
        self,
        config: ClientConfig,
        *,
        tracking_id: str | None = None,
        target_currency: str = "USD",
        target_language: str = "EN",
        ship_to_country: str | None = None,
        transport: Transport | None = None,
        client: TopClient | None = None,
    ) -> None:
        self.config = config
        self.tracking_id = tracking_id
        self.target_currency = target_currency
        self.target_language = target_language
        self.ship_to_country = ship_to_country
        self._client = client or TopClient(config, transport)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None, **kwargs: Any) -> "AffiliateClient":
        """Build a client from ``ALIEXPRESS_*`` environment variables."""
        import os

        source = os.environ if env is None else env
        kwargs.setdefault("tracking_id", source.get("ALIEXPRESS_TRACKING_ID"))
        kwargs.setdefault("ship_to_country", source.get("ALIEXPRESS_SHIP_TO_COUNTRY"))
        return cls(ClientConfig.from_env(source), **kwargs)

    # -- internals --------------------------------------------------------

    def _call(self, method: str, params: Mapping[str, Any]) -> Any:
        cleaned = {k: v for k, v in params.items() if v is not None}
        return unwrap_result(self._client.call(method, cleaned))

    def _tracking_id(self, override: str | None) -> str | None:
        return override or self.tracking_id

    # -- product discovery ------------------------------------------------

    def search_products(
        self,
        keywords: str | None = None,
        *,
        category_ids: str | Sequence[Any] | None = None,
        min_sale_price: float | None = None,
        max_sale_price: float | None = None,
        page_no: int = 1,
        page_size: int = 20,
        sort: str | None = None,
        delivery_days: int | None = None,
        platform_product_type: str | None = None,
        ship_to_country: str | None = None,
        target_currency: str | None = None,
        target_language: str | None = None,
        tracking_id: str | None = None,
        fields: str = DEFAULT_PRODUCT_FIELDS,
    ) -> ProductPage:
        """Search the affiliate catalogue.

        ``sort`` accepts the platform's own tokens, e.g. ``SALE_PRICE_ASC``,
        ``SALE_PRICE_DESC``, ``LAST_VOLUME_ASC``, ``LAST_VOLUME_DESC``.
        Prices are expressed in ``target_currency``.
        """
        params = {
            "keywords": keywords,
            "category_ids": ",".join(str(c) for c in category_ids)
            if isinstance(category_ids, (list, tuple))
            else category_ids,
            "min_sale_price": min_sale_price,
            "max_sale_price": max_sale_price,
            "page_no": page_no,
            "page_size": page_size,
            "sort": sort,
            "delivery_days": delivery_days,
            "platform_product_type": platform_product_type,
            "ship_to_country": ship_to_country or self.ship_to_country,
            "target_currency": target_currency or self.target_currency,
            "target_language": target_language or self.target_language,
            "tracking_id": self._tracking_id(tracking_id),
            "fields": fields,
        }
        return ProductPage.from_api(self._call(METHOD_PRODUCT_QUERY, params))

    def iter_products(
        self,
        keywords: str | None = None,
        *,
        max_pages: int | None = None,
        max_items: int | None = None,
        **kwargs: Any,
    ) -> Iterator[Product]:
        """Yield products page by page, stopping at ``max_pages``/``max_items``.

        Pagination is the caller's most common source of accidental quota burn,
        so both limits are enforced here rather than left to the loop body.
        """
        page_no = kwargs.pop("page_no", 1)
        seen = 0
        pages = 0
        while True:
            page = self.search_products(keywords, page_no=page_no, **kwargs)
            for product in page.products:
                yield product
                seen += 1
                if max_items is not None and seen >= max_items:
                    return
            pages += 1
            if max_pages is not None and pages >= max_pages:
                return
            if not page.has_next_page:
                return
            page_no += 1

    def hot_products(
        self,
        keywords: str | None = None,
        *,
        category_ids: str | Sequence[Any] | None = None,
        min_sale_price: float | None = None,
        max_sale_price: float | None = None,
        page_no: int = 1,
        page_size: int = 20,
        sort: str | None = None,
        delivery_days: int | None = None,
        platform_product_type: str | None = None,
        ship_to_country: str | None = None,
        target_currency: str | None = None,
        target_language: str | None = None,
        tracking_id: str | None = None,
        fields: str = DEFAULT_PRODUCT_FIELDS,
    ) -> ProductPage:
        """Query the curated "hot products" feed."""
        params = {
            "keywords": keywords,
            "category_ids": ",".join(str(c) for c in category_ids)
            if isinstance(category_ids, (list, tuple))
            else category_ids,
            "min_sale_price": min_sale_price,
            "max_sale_price": max_sale_price,
            "page_no": page_no,
            "page_size": page_size,
            "sort": sort,
            "delivery_days": delivery_days,
            "platform_product_type": platform_product_type,
            "ship_to_country": ship_to_country or self.ship_to_country,
            "target_currency": target_currency or self.target_currency,
            "target_language": target_language or self.target_language,
            "tracking_id": self._tracking_id(tracking_id),
            "fields": fields,
        }
        return ProductPage.from_api(self._call(METHOD_HOTPRODUCT_QUERY, params))

    def download_hot_products(
        self,
        *,
        category_id: int | str | None = None,
        page_no: int = 1,
        page_size: int = 50,
        country: str | None = None,
        locale: str | None = None,
        target_currency: str | None = None,
        target_language: str | None = None,
        tracking_id: str | None = None,
        fields: str = DEFAULT_PRODUCT_FIELDS,
    ) -> ProductPage:
        """Bulk feed of hot products, meant for building a local catalogue."""
        params = {
            "category_id": category_id,
            "page_no": page_no,
            "page_size": page_size,
            "country": country or self.ship_to_country,
            "locale": locale,
            "target_currency": target_currency or self.target_currency,
            "target_language": target_language or self.target_language,
            "tracking_id": self._tracking_id(tracking_id),
            "fields": fields,
        }
        return ProductPage.from_api(self._call(METHOD_HOTPRODUCT_DOWNLOAD, params))

    def product_details(
        self,
        product_ids: Sequence[Any] | str,
        *,
        country: str | None = None,
        target_currency: str | None = None,
        target_language: str | None = None,
        tracking_id: str | None = None,
        fields: str = DEFAULT_PRODUCT_FIELDS,
    ) -> list[Product]:
        """Fetch full details for up to 50 product ids in one call."""
        params = {
            "product_ids": _join_ids(product_ids, MAX_PRODUCT_IDS_PER_CALL, "product id"),
            "country": country or self.ship_to_country,
            "target_currency": target_currency or self.target_currency,
            "target_language": target_language or self.target_language,
            "tracking_id": self._tracking_id(tracking_id),
            "fields": fields,
        }
        result = self._call(METHOD_PRODUCT_DETAIL, params)
        return [Product.from_api(item) for item in unpack_list(result, "product")]

    # -- links ------------------------------------------------------------

    def generate_links(
        self,
        urls: Sequence[str] | str,
        *,
        promotion_link_type: int = 0,
        tracking_id: str | None = None,
        app_signature: str | None = None,
    ) -> list[PromotionLink]:
        """Turn plain product URLs into tracked affiliate links.

        ``promotion_link_type`` is ``0`` for a normal link and ``2`` for a hot
        link (higher commission, restricted to eligible products).
        """
        resolved_tracking_id = self._tracking_id(tracking_id)
        if not resolved_tracking_id:
            raise ConfigurationError(
                "tracking_id is required to generate links "
                "(pass it to AffiliateClient or set ALIEXPRESS_TRACKING_ID)"
            )
        params = {
            "promotion_link_type": promotion_link_type,
            "source_values": _join_ids(urls, MAX_LINKS_PER_CALL, "URL"),
            "tracking_id": resolved_tracking_id,
            "app_signature": app_signature,
        }
        result = self._call(METHOD_LINK_GENERATE, params)
        return [
            PromotionLink.from_api(item)
            for item in unpack_list(result, "promotion_link")
        ]

    def generate_link(self, url: str, **kwargs: Any) -> PromotionLink | None:
        """Convenience wrapper around :meth:`generate_links` for a single URL."""
        links = self.generate_links([url], **kwargs)
        return links[0] if links else None

    # -- catalogue metadata ----------------------------------------------

    def categories(self) -> list[Category]:
        """List every affiliate category, top level and children together."""
        result = self._call(METHOD_CATEGORY_GET, {})
        return [Category.from_api(item) for item in unpack_list(result, "category")]

    def featured_promos(self) -> list[dict[str, Any]]:
        """List the currently running featured promotions."""
        result = self._call(METHOD_FEATUREDPROMO_GET, {})
        return unpack_list(result, "promo")

    def featured_promo_products(
        self,
        promotion_name: str,
        *,
        category_id: int | str | None = None,
        page_no: int = 1,
        page_size: int = 20,
        sort: str | None = None,
        country: str | None = None,
        target_currency: str | None = None,
        target_language: str | None = None,
        tracking_id: str | None = None,
        fields: str = DEFAULT_PRODUCT_FIELDS,
    ) -> ProductPage:
        """Products taking part in one featured promotion."""
        params = {
            "promotion_name": promotion_name,
            "category_id": category_id,
            "page_no": page_no,
            "page_size": page_size,
            "sort": sort,
            "country": country or self.ship_to_country,
            "target_currency": target_currency or self.target_currency,
            "target_language": target_language or self.target_language,
            "tracking_id": self._tracking_id(tracking_id),
            "fields": fields,
        }
        return ProductPage.from_api(self._call(METHOD_FEATUREDPROMO_PRODUCTS, params))

    # -- reporting --------------------------------------------------------

    def orders(
        self,
        start_time: datetime | str,
        end_time: datetime | str,
        *,
        status: str | None = None,
        page_no: int = 1,
        page_size: int = 50,
        locale_site: str | None = None,
        fields: str = DEFAULT_ORDER_FIELDS,
    ) -> OrderPage:
        """Page through affiliate orders in a time window.

        ``status`` filters on the platform's own values (``Payment Completed``,
        ``Buyer Confirmed Receipt``, ``Finished``, ``Invalid``).
        """
        params = {
            "start_time": format_order_time(start_time),
            "end_time": format_order_time(end_time),
            "status": status,
            "page_no": page_no,
            "page_size": page_size,
            "locale_site": locale_site,
            "fields": fields,
        }
        return OrderPage.from_api(self._call(METHOD_ORDER_LIST, params))

    def orders_by_index(
        self,
        start_time: datetime | str,
        end_time: datetime | str,
        *,
        status: str | None = None,
        page_size: int = 50,
        start_query_index_id: str | None = None,
        fields: str = DEFAULT_ORDER_FIELDS,
    ) -> dict[str, Any]:
        """Cursor-based order listing — the reliable way to walk large windows.

        Returns the raw payload because the cursor
        (``next_query_index_id``) lives beside the orders and callers need it to
        continue; the orders themselves are exposed under ``"orders"``.
        """
        params = {
            "start_time": format_order_time(start_time),
            "end_time": format_order_time(end_time),
            "status": status,
            "page_size": page_size,
            "start_query_index_id": start_query_index_id,
            "fields": fields,
        }
        result = self._call(METHOD_ORDER_LIST_BY_INDEX, params)
        payload = dict(result) if isinstance(result, Mapping) else {}
        payload["orders"] = [
            Order.from_api(item) for item in unpack_list(payload.get("orders"), "order")
        ]
        return payload

    def iter_orders(
        self,
        start_time: datetime | str,
        end_time: datetime | str,
        *,
        status: str | None = None,
        page_size: int = 50,
        fields: str = DEFAULT_ORDER_FIELDS,
    ) -> Iterator[Order]:
        """Walk every order in a window using the cursor-based endpoint."""
        cursor: str | None = None
        while True:
            payload = self.orders_by_index(
                start_time,
                end_time,
                status=status,
                page_size=page_size,
                start_query_index_id=cursor,
                fields=fields,
            )
            orders: list[Order] = payload.get("orders", [])
            yield from orders
            cursor = payload.get("next_query_index_id")
            if not cursor or not orders:
                return

    def order_details(
        self,
        order_ids: Sequence[Any] | str,
        *,
        fields: str = DEFAULT_ORDER_FIELDS,
    ) -> list[Order]:
        """Fetch specific orders by id."""
        params = {
            "order_ids": _join_ids(order_ids, MAX_PRODUCT_IDS_PER_CALL, "order id"),
            "fields": fields,
        }
        result = self._call(METHOD_ORDER_GET, params)
        return [Order.from_api(item) for item in unpack_list(result, "order")]
