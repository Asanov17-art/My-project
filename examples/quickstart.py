"""End-to-end example: search, then turn the results into affiliate links.

Run it with real credentials in the environment (or in a .env file):

    python examples/quickstart.py "wireless earbuds"
"""

from __future__ import annotations

import sys

from aliexpress_affiliate import AffiliateClient
from aliexpress_affiliate.errors import AliExpressError
from aliexpress_affiliate.cli import load_env_file


def main() -> int:
    keywords = sys.argv[1] if len(sys.argv) > 1 else "wireless earbuds"

    try:
        load_env_file(".env")
    except SystemExit:
        pass  # fall back to whatever is already in the environment

    client = AffiliateClient.from_env(target_currency="USD", ship_to_country="KZ")

    try:
        page = client.search_products(keywords, page_size=5, sort="LAST_VOLUME_DESC")
        print(f"{page.total_record_count} products match {keywords!r}\n")

        for product in page:
            print(f"{product.title}\n  {product.sale_price} {product.currency} "
                  f"({product.discount or 'no discount'}), {product.orders} orders")

        urls = [p.product_url for p in page if p.product_url]
        for link in client.generate_links(urls):
            print(f"\n{link.source_value}\n  -> {link.promotion_link}")
    except AliExpressError as exc:
        print(f"API call failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
