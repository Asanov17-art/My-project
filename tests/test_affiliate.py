from datetime import datetime, timezone

import pytest

from aliexpress_affiliate.affiliate import AffiliateClient, format_order_time
from aliexpress_affiliate.errors import ConfigurationError

PRODUCT = {
    "product_id": "1005001",
    "product_title": "Wireless earbuds",
    "target_sale_price": "19.90",
    "target_sale_price_currency": "USD",
    "target_original_price": "39.80",
    "discount": "50%",
    "evaluate_rate": "94.5",
    "lastest_volume": "1240",
    "product_detail_url": "https://www.aliexpress.com/item/1005001.html",
    "shop_name": "Audio Store",
    "commission_rate": "8.0%",
}


def product_page_response(products, **counters):
    payload = {
        "current_page_no": counters.get("current_page_no", 1),
        "total_page_no": counters.get("total_page_no", 1),
        "total_record_count": counters.get("total_record_count", len(products)),
        "products": {"product": products},
    }
    return {"resp_result": {"resp_code": 200, "result": payload}}


def test_search_products_sends_the_expected_method_and_params(affiliate, transport):
    transport.queue(product_page_response([PRODUCT], total_record_count=57, total_page_no=3))

    page = affiliate.search_products("earbuds", page_size=1, min_sale_price=5, sort="SALE_PRICE_ASC")

    request = transport.last_request
    assert request["method"] == "aliexpress.affiliate.product.query"
    assert request["keywords"] == "earbuds"
    assert request["page_size"] == "1"
    assert request["min_sale_price"] == "5"
    assert request["sort"] == "SALE_PRICE_ASC"
    assert request["tracking_id"] == "demo-tracking"
    assert request["target_currency"] == "USD"
    assert "product_id" in request["fields"]

    assert page.total_record_count == 57
    assert page.has_next_page is True
    assert len(page) == 1
    product = page.products[0]
    assert product.product_id == "1005001"
    assert product.sale_price == 19.90
    assert product.original_price == 39.80
    assert product.orders == 1240
    assert product.rating == 94.5
    assert product.raw["commission_rate"] == "8.0%"


def test_category_ids_are_joined_for_the_wire(affiliate, transport):
    transport.queue(product_page_response([]))
    affiliate.search_products("case", category_ids=[100, 200])
    assert transport.last_request["category_ids"] == "100,200"


def test_last_page_reports_no_next_page(affiliate, transport):
    transport.queue(product_page_response([PRODUCT], current_page_no=3, total_page_no=3))
    assert affiliate.search_products("earbuds", page_no=3).has_next_page is False


def test_iter_products_walks_pages_until_the_last_one(affiliate, transport):
    transport.queue(product_page_response([PRODUCT, PRODUCT], current_page_no=1, total_page_no=2))
    transport.queue(product_page_response([PRODUCT], current_page_no=2, total_page_no=2))

    products = list(affiliate.iter_products("earbuds", page_size=2))

    assert len(products) == 3
    assert [request["page_no"] for request in transport.requests] == ["1", "2"]


def test_iter_products_honours_max_items(affiliate, transport):
    transport.queue(product_page_response([PRODUCT, PRODUCT], current_page_no=1, total_page_no=9))
    assert len(list(affiliate.iter_products("earbuds", max_items=1))) == 1
    assert len(transport.requests) == 1


def test_iter_products_honours_max_pages(affiliate, transport):
    transport.queue(product_page_response([PRODUCT], current_page_no=1, total_page_no=9))
    assert len(list(affiliate.iter_products("earbuds", max_pages=1))) == 1
    assert len(transport.requests) == 1


def test_generate_links_returns_one_link_per_source_url(affiliate, transport):
    transport.queue(
        {
            "resp_result": {
                "resp_code": 200,
                "result": {
                    "promotion_links": {
                        "promotion_link": [
                            {
                                "source_value": "https://www.aliexpress.com/item/1.html",
                                "promotion_link": "https://s.click.aliexpress.com/e/_abc",
                            }
                        ]
                    }
                },
            }
        }
    )

    links = affiliate.generate_links(["https://www.aliexpress.com/item/1.html"])

    request = transport.last_request
    assert request["method"] == "aliexpress.affiliate.link.generate"
    assert request["source_values"] == "https://www.aliexpress.com/item/1.html"
    assert request["promotion_link_type"] == "0"
    assert links[0].promotion_link == "https://s.click.aliexpress.com/e/_abc"


def test_hot_links_use_promotion_link_type_2(affiliate, transport):
    transport.queue({"resp_result": {"resp_code": 200, "result": {}}})
    affiliate.generate_links(["https://www.aliexpress.com/item/1.html"], promotion_link_type=2)
    assert transport.last_request["promotion_link_type"] == "2"


def test_generate_links_without_a_tracking_id_fails_before_the_call(config, top_client, transport):
    client = AffiliateClient(config, client=top_client)
    with pytest.raises(ConfigurationError, match="tracking_id"):
        client.generate_links(["https://www.aliexpress.com/item/1.html"])
    assert transport.requests == []


def test_batch_limits_are_enforced_client_side(affiliate, transport):
    with pytest.raises(ConfigurationError, match="at most 50"):
        affiliate.generate_links([f"https://example.com/{i}" for i in range(51)])
    with pytest.raises(ConfigurationError, match="at most 50"):
        affiliate.product_details([str(i) for i in range(51)])
    with pytest.raises(ConfigurationError, match="at least one"):
        affiliate.product_details([])
    assert transport.requests == []


def test_product_details_joins_ids_and_parses_products(affiliate, transport):
    transport.queue({"resp_result": {"resp_code": 200, "result": {"products": {"product": [PRODUCT]}}}})
    products = affiliate.product_details(["1005001", "1005002"])
    assert transport.last_request["product_ids"] == "1005001,1005002"
    assert products[0].title == "Wireless earbuds"


def test_categories_are_flagged_top_level_or_child(affiliate, transport):
    transport.queue(
        {
            "resp_result": {
                "resp_code": 200,
                "result": {
                    "categories": {
                        "category": [
                            {"category_id": 3, "category_name": "Apparel"},
                            {"category_id": 31, "category_name": "Shirts", "parent_category_id": 3},
                        ]
                    }
                },
            }
        }
    )
    top, child = affiliate.categories()
    assert top.is_top_level is True
    assert child.is_top_level is False
    assert child.parent_category_id == 3


def test_orders_are_queried_with_beijing_timestamps(affiliate, transport):
    transport.queue(
        {
            "resp_result": {
                "resp_code": 200,
                "result": {
                    "total_record_count": 1,
                    "current_page_no": 1,
                    "orders": {
                        "order": [
                            {
                                "order_id": "300001",
                                "product_title": "Wireless earbuds",
                                "order_status": "Payment Completed",
                                "estimated_paid_commission": "1.59",
                                "paid_amount_currency": "USD",
                            }
                        ]
                    },
                },
            }
        }
    )

    start = datetime(2024, 5, 1, 0, 0, tzinfo=timezone.utc)
    end = datetime(2024, 5, 2, 0, 0, tzinfo=timezone.utc)
    page = affiliate.orders(start, end, status="Payment Completed")

    request = transport.last_request
    assert request["method"] == "aliexpress.affiliate.order.list"
    assert request["start_time"] == "2024-05-01 08:00:00"
    assert request["end_time"] == "2024-05-02 08:00:00"
    assert request["status"] == "Payment Completed"
    assert page.orders[0].estimated_paid_commission == 1.59


def test_iter_orders_follows_the_cursor_until_it_runs_out(affiliate, transport):
    transport.queue(
        {
            "resp_result": {
                "resp_code": 200,
                "result": {
                    "orders": {"order": [{"order_id": "1"}, {"order_id": "2"}]},
                    "next_query_index_id": "cursor-2",
                },
            }
        }
    )
    transport.queue(
        {"resp_result": {"resp_code": 200, "result": {"orders": {"order": [{"order_id": "3"}]}}}}
    )

    orders = list(affiliate.iter_orders("2024-05-01 00:00:00", "2024-05-02 00:00:00"))

    assert [order.order_id for order in orders] == ["1", "2", "3"]
    assert "start_query_index_id" not in transport.requests[0]
    assert transport.requests[1]["start_query_index_id"] == "cursor-2"


def test_format_order_time_passes_strings_through():
    assert format_order_time("2024-05-01 00:00:00") == "2024-05-01 00:00:00"


def test_naive_datetimes_are_taken_at_face_value():
    assert format_order_time(datetime(2024, 5, 1, 12, 30)) == "2024-05-01 12:30:00"


def test_from_env_wires_tracking_id_and_credentials():
    client = AffiliateClient.from_env(
        {
            "ALIEXPRESS_APP_KEY": "k",
            "ALIEXPRESS_APP_SECRET": "s",
            "ALIEXPRESS_TRACKING_ID": "campaign-1",
        }
    )
    assert client.tracking_id == "campaign-1"
    assert client.config.app_key == "k"
