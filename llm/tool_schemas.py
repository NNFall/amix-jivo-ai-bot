OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": (
                "Ищет товарные факты AMIX в локальной базе данных по коду товара, артикулу "
                "или нескольким значениям из сообщения клиента. Используется только для товарных "
                "вопросов: цена, наличие, остаток, код, артикул, вес, объем, единица измерения, "
                "сравнение, заказ, уточнение товара или проверка скидки по текущему товару. "
                "Функция не отвечает на общие вопросы о контактах, адресе, доставке и режиме работы."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "queries": {
                        "type": "array",
                        "description": (
                            "Товары из сообщения клиента в исходном порядке. Для каждого товара "
                            "передавай его код, артикул или поисковое значение и отдельно количество, "
                            "если клиент его указал."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "query": {
                                    "type": "string",
                                    "description": "Код, артикул или поисковое значение максимально близко к словам клиента.",
                                },
                                "requested_quantity": {
                                    "type": ["number", "null"],
                                    "description": "Положительное количество именно этого товара, если клиент его указал.",
                                },
                            },
                            "required": ["query"],
                        },
                    },
                    "intent": {
                        "type": "string",
                        "description": "Что клиент хочет узнать.",
                        "enum": [
                            "availability",
                            "price",
                            "stock",
                            "product_info",
                            "compare",
                            "order",
                            "discount_check",
                            "clarification",
                            "unknown",
                        ],
                    },
                    "use_dialog_context": {
                        "type": "boolean",
                        "description": (
                            "true, если запрос является продолжением обсуждения уже названного "
                            "товара или уточнением ранее найденного варианта."
                        ),
                    },
                    "context_note": {
                        "type": "string",
                        "description": "Короткое пояснение, как запрос связан с предыдущим диалогом.",
                    },
                },
                "required": ["queries", "intent", "use_dialog_context"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "handoff_to_manager",
            "description": (
                "Передает текущий диалог живому менеджеру AMIX через Jivo. Используется, когда "
                "клиент просит человека, подтвердил показанный итог заказа, недоволен ответом, спрашивает "
                "технический подбор, совместимость, аналоги, сложные отличия, индивидуальные "
                "скидки, акции, доставку или возврат по конкретной ситуации. Во время сбора заказа "
                "указанные клиентом доставка и оплата являются данными заказа, а не причиной передачи; "
                "товар с количеством, за которым следуют получение, оплата или контакты, также является сбором заказа; "
                "не вызывай эту функцию до показа и подтверждения полного итога, если клиент сам не просит человека."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Причина передачи менеджеру.",
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
                        "description": (
                            "Краткое резюме для менеджера: цель обращения, подтверждённые клиентом "
                            "сведения и результаты проверок без раскрытия точного свободного остатка."
                        ),
                    },
                    "customer_message": {
                        "type": "string",
                        "description": "Короткое сообщение клиенту перед передачей менеджеру.",
                    },
                },
                "required": ["reason", "summary"],
            },
        },
    },
]
