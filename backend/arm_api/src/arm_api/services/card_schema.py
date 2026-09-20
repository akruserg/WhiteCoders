"""Карточка происшествия АРМ-112: поля шаблона и словарь действий.

Поля повторяют реальную карточку оператора (блоки «Телефоны заявителя»,
«Что случилось?», «Адрес», «Подробности», «Описание со слов заявителя»).
Ключи полей и названия действий - контракт с фронтендом: ответ обучающегося
приходит в answer по этим ключам, а выполненные шаги - в actions по этим типам.
"""

TEMPLATE_CODE = "arm112_card"
TEMPLATE_NAME = "Карточка происшествия АРМ-112"

TEMPLATE_FIELDS = [
    {"key": "phone_aon", "label": "Телефон АОН", "type": "phone", "required": False, "weight": 1},
    {"key": "phone_provided", "label": "Предоставленный номер", "type": "phone", "required": False, "weight": 1},
    {"key": "phone_place", "label": "Телефон на место", "type": "phone", "required": False, "weight": 1},
    {"key": "applicant_name", "label": "Фамилия и имя заявителя", "type": "text", "required": False, "weight": 1},
    {"key": "incident_type", "label": "Тип происшествия", "type": "text", "required": True, "weight": 3},
    {"key": "incident_details", "label": "Подробности происшествия", "type": "textarea", "required": True, "weight": 2},
    {"key": "address_street", "label": "Улица", "type": "text", "required": True, "weight": 2},
    {"key": "address_house", "label": "Дом", "type": "text", "required": True, "weight": 2},
    {"key": "address_flat", "label": "Квартира/офис", "type": "text", "required": False, "weight": 1},
    {"key": "address_entrance", "label": "Подъезд", "type": "text", "required": False, "weight": 1},
    {"key": "address_floor", "label": "Этаж", "type": "text", "required": False, "weight": 1},
    {"key": "victims", "label": "Пострадавшие", "type": "text", "required": True, "weight": 2},
    {"key": "services", "label": "Службы на вызов", "type": "multiselect", "required": True, "weight": 2},
    {"key": "description", "label": "Описание со слов заявителя", "type": "textarea", "required": True, "weight": 2},
]  # fmt: skip

# Типы действий с карточкой. Порядок в эталоне важен: он проверяется.
ACTION_TYPES = [
    "fill_phones",
    "fill_applicant",
    "select_incident_type",
    "fill_incident_details",
    "fill_address",
    "fill_victims",
    "add_services",
    "fill_description",
    "save_card",
]

DEFAULT_ACTIONS = [
    "select_incident_type",
    "fill_incident_details",
    "fill_address",
    "fill_victims",
    "add_services",
    "fill_description",
    "save_card",
]

# Служебные настройки, которые видит и меняет администратор (см. /system/settings)
DEFAULT_SETTINGS = [
    ("voip.enabled", "voip", True, "Принудительно включить или выключить VoIP-звонки", False, False),
    ("voip.max_latency_ms", "voip", 150, "Допустимая задержка голоса, мс (норма ТЗ)", False, False),
    ("backup.keep_count", "backup", 30, "Сколько последних резервных копий хранить", False, False),
    ("audit.retention_days", "logging", 190, "Сколько дней хранить журнал аудита (не менее 6 месяцев)", False, False),
    ("ai.enabled", "ai", False, "Включить ИИ-модуль (генерация сценариев, инсайты)", False, True),
    ("ai.scoring_enabled", "ai", False, "Смысловая проверка текстовых полей нейросетью", False, True),
    ("security.max_failed_logins", "security", 5, "Неудачных входов до блокировки", False, True),
]  # fmt: skip
