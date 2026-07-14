OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "update_order_draft",
            "description": (
                "Создаёт или обновляет черновик заказа по данным из текущего сообщения клиента. "
                "Вызывай при намерении оформить заказ и после каждого уточнения состава, количества, "
                "получения, оплаты или контактов. Передавай только явно сообщённые клиентом данные."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "description": "Полный актуальный список позиций, если клиент назвал или изменил товары.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "identifier": {
                                    "type": "string",
                                    "description": "Код или артикул, только если клиент его назвал.",
                                },
                                "description": {
                                    "type": "string",
                                    "description": "Свободное описание товара, если кода или артикула нет.",
                                },
                                "quantity": {"type": "number", "description": "Требуемое количество."},
                            },
                        },
                    },
                    "needed_by": {
                        "type": "string",
                        "description": "Когда клиенту нужен заказ, в его формулировке, без обещания срока поставки.",
                    },
                    "fulfillment": {
                        "type": "object",
                        "properties": {
                            "method": {"type": "string", "enum": ["pickup", "delivery"]},
                            "city": {"type": "string"},
                            "address": {"type": "string"},
                        },
                    },
                    "payment": {
                        "type": "object",
                        "properties": {
                            "method": {
                                "type": "string",
                                "enum": ["cash", "card", "online", "bank_transfer"],
                            },
                            "customer_type": {
                                "type": "string",
                                "enum": ["individual", "legal_entity", "individual_entrepreneur"],
                                "description": "Необязательное поле: передавай только если клиент сам назвал тип плательщика.",
                            },
                            "company_name": {
                                "type": "string",
                                "description": "Необязательное название компании или ИП, если клиент сообщил его сам.",
                            },
                            "inn": {
                                "type": "string",
                                "description": "ИНН клиента; обязателен для оплаты по счёту.",
                            },
                            "kpp": {
                                "type": "string",
                                "description": "Необязательный КПП, только если клиент сообщил его сам.",
                            },
                        },
                    },
                    "contact": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Имя клиента; обязательно для заказа."},
                            "phone": {"type": "string", "description": "Телефон клиента; обязателен для заказа."},
                            "email": {
                                "type": "string",
                                "description": "Необязательный email, только если клиент сообщил его сам.",
                            },
                        },
                    },
                    "notes": {"type": "string"},
                },
            },
        },
    },
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
                            "Артикулы, коды товаров или поисковые значения из сообщения клиента. "
                            "Передавай значения максимально близко к тексту клиента. Если клиент "
                            "уточняет ранее найденный товар по цене или коду, передай это значение "
                            "и укажи use_dialog_context=true."
                        ),
                        "items": {"type": "string"},
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
                            "true, если запрос клиента является продолжением предыдущего обсуждения "
                            "товара. Например: 'цена 132', 'та что за 132', 'код 26168', "
                            "'скидки есть?', 'а наличие?'."
                        ),
                    },
                    "context_note": {
                        "type": "string",
                        "description": (
                            "Короткое пояснение, как запрос связан с диалогом. Например: "
                            "'Клиент уточняет предыдущий артикул МП 28ск по цене 132'."
                        ),
                    },
                    "requested_quantity": {
                        "type": ["number", "null"],
                        "description": "Количество, которое хочет клиент, если он хочет заказать товар.",
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
                "клиент просит человека, подтвердил собранный черновик заказа, недоволен ответом, спрашивает "
                "технический подбор, совместимость, аналоги, сложные отличия, индивидуальные "
                "скидки, акции, доставку или возврат по конкретной ситуации."
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
                            "Краткое резюме для менеджера: что спросил клиент, какие товары/коды "
                            "обсуждались, что уже было проверено, какие остатки/цены найдены."
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
