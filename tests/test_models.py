"""The response shapes AliExpress actually returns, and how they are unpacked."""

from aliexpress_affiliate.models import Product, ProductPage, unpack_list


def test_wrapped_collection_is_unpacked():
    assert unpack_list({"products": {"product": [{"id": 1}, {"id": 2}]}}, "product") == [
        {"id": 1},
        {"id": 2},
    ]


def test_simplified_collection_is_unpacked():
    assert unpack_list({"products": [{"id": 1}]}, "product") == [{"id": 1}]


def test_bare_list_is_unpacked():
    assert unpack_list([{"id": 1}], "product") == [{"id": 1}]


def test_single_unwrapped_element_becomes_a_one_item_list():
    assert unpack_list({"product": {"id": 1}}, "product") == [{"id": 1}]


def test_irregular_plural_wrappers_are_recognised():
    assert unpack_list({"categories": {"category": [{"id": 3}]}}, "category") == [{"id": 3}]


def test_missing_and_empty_collections_yield_no_items():
    assert unpack_list(None, "product") == []
    assert unpack_list([], "product") == []
    assert unpack_list({}, "product") == []


def test_product_falls_back_across_price_field_names():
    # Older responses carry ``app_sale_price`` instead of ``target_sale_price``.
    product = Product.from_api({"app_sale_price": "5.00", "sale_price_currency": "EUR"})
    assert product.sale_price == 5.00
    assert product.currency == "EUR"


def test_unparseable_numbers_do_not_break_parsing():
    product = Product.from_api({"target_sale_price": "n/a", "lastest_volume": ""})
    assert product.sale_price is None
    assert product.orders is None


def test_empty_page_is_falsy_and_has_no_next_page():
    page = ProductPage.from_api({"current_page_no": 1, "total_page_no": 1})
    assert len(page) == 0
    assert page.has_next_page is False
    assert list(page) == []


def test_raw_payload_is_preserved_for_fields_the_model_skips():
    product = Product.from_api({"product_id": "1", "some_new_field": "value"})
    assert product.raw["some_new_field"] == "value"
