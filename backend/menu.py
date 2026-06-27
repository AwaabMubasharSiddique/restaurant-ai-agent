from __future__ import annotations

import difflib

MENU: list[dict] = [

    {"name": "Hummus & Warm Pita", "price": 8.50, "category": "Starters"},
    {"name": "Falafel Plate", "price": 9.00, "category": "Starters"},
    {"name": "Grilled Halloumi", "price": 10.50, "category": "Starters"},
    {"name": "Spanakopita", "price": 9.50, "category": "Starters"},
    {"name": "Calamari Fritti", "price": 13.00, "category": "Starters"},
    {"name": "Mezze Sampler for Two", "price": 19.00, "category": "Starters"},

    {"name": "Classic Greek Salad", "price": 11.00, "category": "Salads"},
    {"name": "Fattoush", "price": 10.50, "category": "Salads"},

    {"name": "Chicken Souvlaki", "price": 19.00, "category": "Mains"},
    {"name": "Lamb Kofta", "price": 22.00, "category": "Mains"},
    {"name": "Grilled Branzino", "price": 26.00, "category": "Mains"},
    {"name": "Eggplant Moussaka", "price": 18.00, "category": "Mains"},
    {"name": "Margherita Pizza", "price": 15.00, "category": "Mains"},
    {"name": "Seafood Linguine", "price": 24.00, "category": "Mains"},
    {"name": "Vegan Buddha Bowl", "price": 16.00, "category": "Mains"},

    {"name": "Baklava", "price": 7.00, "category": "Desserts"},
    {"name": "Tiramisu", "price": 8.00, "category": "Desserts"},
    {"name": "Lemon Olive Oil Cake", "price": 7.50, "category": "Desserts"},
    {"name": "Seasonal Fruit Sorbet", "price": 6.00, "category": "Desserts"},

    {"name": "House Wine", "price": 9.00, "category": "Drinks"},
    {"name": "Local Craft Beer", "price": 7.00, "category": "Drinks"},
    {"name": "Mint Lemonade", "price": 5.00, "category": "Drinks"},
    {"name": "Turkish Coffee", "price": 4.00, "category": "Drinks"},
    {"name": "Espresso", "price": 3.50, "category": "Drinks"},
    {"name": "Cappuccino", "price": 4.50, "category": "Drinks"},
    {"name": "Soft Drink", "price": 3.00, "category": "Drinks"},

    {"name": "Mini Margherita Pizza", "price": 8.00, "category": "Kids"},
    {"name": "Chicken Tenders & Fries", "price": 8.00, "category": "Kids"},
    {"name": "Buttered Pasta", "price": 8.00, "category": "Kids"},
]

_BY_NAME = {item["name"].lower(): item for item in MENU}


def find_menu_item(name: str) -> dict | None:
    return match_menu_item(name)[0]


def match_menu_item(name: str) -> tuple[dict | None, bool]:
    """Return (item, was_fuzzy). ``was_fuzzy`` is True when the match came from a
    near-miss rather than an exact name, so callers can confirm it with the guest."""
    key = (name or "").strip().lower()
    if not key:
        return None, False
    if key in _BY_NAME:
        return _BY_NAME[key], False
    close = difflib.get_close_matches(key, _BY_NAME.keys(), n=1, cutoff=0.82)
    return (_BY_NAME[close[0]], True) if close else (None, False)


def price_items(items: list) -> tuple[list, list, list]:
    """Returns (priced, unknown, corrections). ``corrections`` holds
    (what_they_said, matched_name) pairs for fuzzy matches worth confirming."""
    priced: list[dict] = []
    unknown: list[str] = []
    corrections: list[tuple[str, str]] = []
    for item in items:
        found, was_fuzzy = match_menu_item(item.name)
        if found:
            priced.append(
                {"name": found["name"], "quantity": item.quantity, "price": found["price"]}
            )
            if was_fuzzy:
                corrections.append((item.name, found["name"]))
        else:
            unknown.append(item.name)
    return priced, unknown, corrections


def order_total(priced: list) -> float:
    return round(sum(i["price"] * i["quantity"] for i in priced), 2)


def format_menu_for_prompt() -> str:
    return "\n".join(f"- {item['name']} — ${item['price']:.2f}" for item in MENU)
