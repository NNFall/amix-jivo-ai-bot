OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": (
                "Ищет товары AMIX в актуальной локальной базе. Возвращает все доступные товарные факты: "
                "код, артикул, цены, единицу измерения, вес, объём и свободный остаток. "
                "Если для товара передано requested_quantity, дополнительно возвращает, доступно ли это количество. "
                "Передавай каждый названный клиентом товар отдельным элементом и сохраняй исходный порядок."
            ),
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "queries": {
                        "type": "array",
                        "description": "Товары, которые нужно найти, в порядке сообщения клиента.",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "query": {
                                    "type": "string",
                                    "description": "Код, артикул или название максимально близко к словам клиента.",
                                },
                                "requested_quantity": {
                                    "type": ["number", "null"],
                                    "description": "Количество именно этого товара, если клиент его указал.",
                                },
                            },
                            "required": ["query"],
                        },
                    }
                },
                "required": ["queries"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "handoff_to_manager",
            "description": (
                "Передаёт текущий диалог живому менеджеру AMIX. Вызывай функцию только в случаях, "
                "описанных в системной инструкции, и передавай менеджеру понятное резюме всей нужной истории."
            ),
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Причина передачи.",
                        "enum": [
                            "client_requested_manager",
                            "order_creation",
                            "requested_quantity_exceeds_stock",
                            "technical_consultation",
                            "product_selection",
                            "compatibility_or_analogs",
                            "discount_or_individual_terms",
                            "delivery_or_return_specific_case",
                            "client_dissatisfied",
                            "bot_uncertain",
                            "error",
                        ],
                    },
                    "summary": {
                        "type": "string",
                        "description": "Краткое резюме для менеджера по полной истории диалога.",
                    },
                    "customer_message": {
                        "type": "string",
                        "description": "Короткое сообщение клиенту о фактической передаче менеджеру.",
                    },
                },
                "required": ["reason", "summary", "customer_message"],
            },
        },
    },
]
