import type { TemplateField } from "../../api/types";

// Какое действие с карточкой соответствует полю (порядок первого касания проверяется в режиме card_actions)
export const ACTION_BY_FIELD: Record<string, string> = {
  phone_aon: "fill_phones", phone_provided: "fill_phones", phone_place: "fill_phones",
  applicant_name: "fill_applicant", incident_type: "select_incident_type",
  incident_details: "fill_incident_details",
  address_street: "fill_address", address_house: "fill_address", address_flat: "fill_address",
  address_entrance: "fill_address", address_floor: "fill_address",
  victims: "fill_victims", services: "add_services", description: "fill_description",
};

export const SERVICES = [
  "Служба 101", "Служба 102", "Служба 103", "Служба 104", "Мосводоканал", "Мосгаз",
  "Мосэнерго", "Мослифт", "ЦЭМП", "ЦОДД", "Дежурная служба ЖКХ", "Мосгортранс",
];

export const QUICK_TYPES = ["ДТП", "Пожар в квартире", "Ошибочно набран номер", "Консультация", "Передача дежурству", "Справка-101", "Тестовый вызов"];
export const QUICK_VICTIMS = ["Нет", "Один", "Двое", "Несколько", "Нет данных"];

export const FALLBACK_FIELDS: TemplateField[] = [
  { key: "phone_aon", label: "Телефон АОН", type: "phone", required: false, weight: 1 },
  { key: "incident_type", label: "Тип происшествия", type: "select", required: true, weight: 3 },
  { key: "incident_details", label: "Подробности происшествия", type: "textarea", required: true, weight: 2 },
  { key: "address_street", label: "Улица", type: "text", required: true, weight: 2 },
  { key: "address_house", label: "Дом", type: "text", required: true, weight: 2 },
  { key: "victims", label: "Пострадавшие", type: "text", required: true, weight: 2 },
  { key: "services", label: "Службы на вызов", type: "multiselect", required: true, weight: 2 },
  { key: "description", label: "Описание со слов заявителя", type: "textarea", required: true, weight: 2 },
];

export const ADDRESS_KEYS = ["address_street", "address_house", "address_flat", "address_entrance", "address_floor"];
export const PHONE_KEYS = ["phone_aon", "phone_provided", "phone_place"];
