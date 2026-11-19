"""A tiny inventory module used as the demo codebase."""


class Inventory:
    def __init__(self):
        self.items = {}

    def add(self, sku, qty):
        self.items[sku] = self.items.get(sku, 0) + qty

    def remove(self, sku, qty):
        if self.items.get(sku, 0) < qty:
            raise ValueError("insufficient stock")
        self.items[sku] -= qty

    def total(self):
        return sum(self.items.values())
