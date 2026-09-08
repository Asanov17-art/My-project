"""Command line front end: ``aliexpress <command> ...``.

Credentials come from the environment (``ALIEXPRESS_APP_KEY``,
``ALIEXPRESS_APP_SECRET``, ``ALIEXPRESS_TRACKING_ID``); ``--env-file`` loads
them from a dotenv-style file first.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from .affiliate import AffiliateClient
from .errors import AliExpressError
from .models import Order, Product


def load_env_file(path: str) -> None:
    """Read ``KEY=value`` lines into ``os.environ`` without overwriting it."""
    if not os.path.exists(path):
        raise SystemExit(f"env file not found: {path}")
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def _dump(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def _product_row(product: Product) -> str:
    price = f"{product.sale_price} {product.currency or ''}".strip()
    return " | ".join(
        [
            str(product.product_id or "-"),
            (product.title or "-")[:70],
            price or "-",
            f"orders={product.orders if product.orders is not None else '-'}",
            product.promotion_link or product.product_url or "-",
        ]
    )


def _order_row(order: Order) -> str:
    return " | ".join(
        [
            str(order.order_id or "-"),
            (order.product_title or "-")[:50],
            order.order_status or "-",
            f"commission={order.estimated_paid_commission} {order.currency or ''}".strip(),
        ]
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aliexpress", description=__doc__)
    parser.add_argument("--env-file", help="dotenv file with ALIEXPRESS_* variables")
    parser.add_argument("--json", action="store_true", help="print raw JSON instead of a table")
    parser.add_argument("-v", "--verbose", action="store_true", help="log retries and warnings")
    sub = parser.add_subparsers(dest="command", required=True)

    search = sub.add_parser("search", help="search the affiliate catalogue")
    search.add_argument("keywords")
    search.add_argument("--page", type=int, default=1)
    search.add_argument("--page-size", type=int, default=20)
    search.add_argument("--min-price", type=float)
    search.add_argument("--max-price", type=float)
    search.add_argument("--sort", help="e.g. SALE_PRICE_ASC, LAST_VOLUME_DESC")
    search.add_argument("--currency", default="USD")
    search.add_argument("--language", default="EN")
    search.add_argument("--ship-to", help="destination country code, e.g. KZ")

    hot = sub.add_parser("hot", help="query the hot products feed")
    hot.add_argument("--keywords")
    hot.add_argument("--page", type=int, default=1)
    hot.add_argument("--page-size", type=int, default=20)
    hot.add_argument("--currency", default="USD")
    hot.add_argument("--ship-to")

    link = sub.add_parser("link", help="generate tracked affiliate links")
    link.add_argument("urls", nargs="+")
    link.add_argument("--hot", action="store_true", help="request a hot link (type 2)")

    detail = sub.add_parser("detail", help="fetch product details by id")
    detail.add_argument("product_ids", nargs="+")
    detail.add_argument("--currency", default="USD")
    detail.add_argument("--ship-to")

    sub.add_parser("categories", help="list affiliate categories")

    orders = sub.add_parser("orders", help="list affiliate orders")
    orders.add_argument("--days", type=int, default=7, help="window size, ending now")
    orders.add_argument("--status")
    orders.add_argument("--page-size", type=int, default=50)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.ERROR,
        format="%(levelname)s %(name)s: %(message)s",
    )
    if args.env_file:
        load_env_file(args.env_file)

    try:
        client = AffiliateClient.from_env(
            target_currency=getattr(args, "currency", "USD"),
            target_language=getattr(args, "language", "EN"),
            ship_to_country=getattr(args, "ship_to", None),
        )
        return _dispatch(client, args)
    except AliExpressError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _dispatch(client: AffiliateClient, args: argparse.Namespace) -> int:
    if args.command == "search":
        page = client.search_products(
            args.keywords,
            page_no=args.page,
            page_size=args.page_size,
            min_sale_price=args.min_price,
            max_sale_price=args.max_price,
            sort=args.sort,
        )
        if args.json:
            _dump(page.raw)
        else:
            print(f"{page.total_record_count or 0} results, page {page.current_page_no}")
            for product in page:
                print(_product_row(product))
        return 0

    if args.command == "hot":
        page = client.hot_products(
            args.keywords, page_no=args.page, page_size=args.page_size
        )
        if args.json:
            _dump(page.raw)
        else:
            for product in page:
                print(_product_row(product))
        return 0

    if args.command == "link":
        links = client.generate_links(args.urls, promotion_link_type=2 if args.hot else 0)
        if args.json:
            _dump([link.raw for link in links])
        else:
            for link in links:
                print(f"{link.source_value} -> {link.promotion_link}")
        return 0

    if args.command == "detail":
        products = client.product_details(args.product_ids)
        if args.json:
            _dump([product.raw for product in products])
        else:
            for product in products:
                print(_product_row(product))
        return 0

    if args.command == "categories":
        categories = client.categories()
        if args.json:
            _dump([category.raw for category in categories])
        else:
            for category in categories:
                marker = "" if category.is_top_level else "  └ "
                print(f"{marker}{category.category_id}\t{category.category_name}")
        return 0

    if args.command == "orders":
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=args.days)
        page = client.orders(start, end, status=args.status, page_size=args.page_size)
        if args.json:
            _dump(page.raw)
        else:
            print(f"{page.total_record_count or 0} orders in the last {args.days} day(s)")
            for order in page:
                print(_order_row(order))
        return 0

    raise SystemExit(f"unknown command: {args.command}")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
