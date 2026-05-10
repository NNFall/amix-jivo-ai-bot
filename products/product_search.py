from decimal import Decimal


class ProductSearchService:
    def build_product_reply(self, product) -> str:
        stock_value = self._format_decimal(product.free_stock)
        retail_price = self._format_decimal(product.retail_price)
        corporate_price = self._format_decimal(product.corporate_price)

        parts = [f"Артикул {product.article} найден."]

        if stock_value is not None:
            if product.free_stock and product.free_stock > 0:
                parts.append(f"Свободный остаток: {stock_value} {product.unit or 'шт.'}.")
            else:
                parts.append("Сейчас свободного остатка нет.")

        if retail_price is not None:
            parts.append(f"Розничная цена: {retail_price} руб.")

        if corporate_price is not None:
            parts.append(f"Корпоративная цена: {corporate_price} руб.")

        if product.weight is not None:
            parts.append(f"Вес: {product.weight}.")

        if product.volume is not None:
            parts.append(f"Объём: {product.volume}.")

        return " ".join(parts)

    def build_similar_products_reply(self, requested_article: str, products: list) -> str:
        article_list = ", ".join(product.article for product in products[:5])
        return (
            f"Точный артикул {requested_article} не найден. "
            f"Нашёл похожие позиции: {article_list}. "
            "Если нужен точный подбор, лучше передать вопрос менеджеру."
        )

    @staticmethod
    def _format_decimal(value: Decimal | None) -> str | None:
        if value is None:
            return None
        normalized = value.normalize()
        return format(normalized, "f").rstrip("0").rstrip(".") or "0"
