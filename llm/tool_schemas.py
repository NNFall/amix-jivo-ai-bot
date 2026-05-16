OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": (
                "Поиск товаров AMIX в локальной базе данных по артикулу, коду товара "
                "или нескольким значениям. Используется для проверки наличия, цены, остатка, "
                "единицы измерения, веса, объёма."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "queries": {
                        "type": "array",
                        "description": (
                            "Список артикулов, кодов или поисковых строк, которые нужно найти. "
                            "Передавай значения максимально близко к тому, как их написал клиент."
                        ),
                        "items": {"type": "string"},
                    },
                    "reason": {
                        "type": "string",
                        "description": "Зачем выполняется поиск.",
                        "enum": ["availability", "price", "stock", "product_info", "compare", "unknown"],
                    },
                },
                "required": ["queries", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "handoff_to_manager",
            "description": (
                "Передать диалог живому менеджеру AMIX через Jivo, если бот не может "
                "безопасно ответить сам или клиент просит человека."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Причина передачи менеджеру.",
                    },
                    "summary": {
                        "type": "string",
                        "description": (
                            "Краткое резюме для менеджера: что спросил клиент, "
                            "какие артикулы/коды упоминались, что уже ответил бот."
                        ),
                    },
                },
                "required": ["reason", "summary"],
            },
        },
    },
]
