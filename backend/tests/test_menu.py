from menu import find_menu_item, order_total, price_items
from models.schemas import OrderItem


def test_find_menu_item_exact_and_caseless():
    assert find_menu_item("Chicken Souvlaki")["price"] == 19.00
    assert find_menu_item("chicken souvlaki")["price"] == 19.00


def test_find_menu_item_fuzzy_and_miss():
    assert find_menu_item("baklavaa") is not None
    assert find_menu_item("zinger burger") is None
    assert find_menu_item("") is None


def test_price_items_splits_known_and_unknown():
    priced, unknown = price_items(
        [OrderItem(name="Baklava", quantity=2), OrderItem(name="Zinger Burger", quantity=1)]
    )
    assert len(priced) == 1
    assert priced[0]["name"] == "Baklava"
    assert priced[0]["price"] == 7.00
    assert priced[0]["quantity"] == 2
    assert unknown == ["Zinger Burger"]


def test_order_total():
    priced = [
        {"name": "Baklava", "quantity": 2, "price": 7.00},
        {"name": "Chicken Souvlaki", "quantity": 1, "price": 19.00},
    ]
    assert order_total(priced) == 33.00
