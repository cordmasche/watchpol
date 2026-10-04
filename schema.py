"""
Event schema — the ONE place to change what an incident contains.

Fixed core columns (always present, do not remove):
    event_id    auto-assigned
    event_type  one of EVENT_TYPES (the stored value is the "value" slug)
    verified    yes/no
    simulated   yes/no
    lat, lon    set by clicking the map
    reported_at UTC timestamp, set by the server

Everything in FIELDS can be renamed, added or removed. New entries are added to the
database automatically on the next start. Removed/renamed entries leave the old
column untouched.

Field keys:
    name      database column (lowercase letters, digits, underscore)
    label     shown in the form, popups and cards
    type      text | textarea | select | number | integer | boolean | date | datetime
    required  optional, True/False
    options   for select: list of {"value": stored, "label": shown}  (plain strings also work)
    group     optional, "extra" puts the field under "Weitere Angaben" in the form
"""

# value = what is stored in the database, label = what people see, color = map/list colour
EVENT_TYPES = [
    {"value": "koerperverletzung", "label": "Körperverletzung",  "color": "#E91E92"},
    {"value": "festnahme",         "label": "Festnahme",         "color": "#FF8800"},
    {"value": "personenkontrolle", "label": "Personenkontrolle", "color": "#FFD600"},
    {"value": "verbale_gewalt",    "label": "Verbale Gewalt",    "color": "#5DCAA5"},
    {"value": "ki_ueberwachung",   "label": "KI/Überwachung",    "color": "#378ADD"},
    {"value": "sonstiges",         "label": "Sonstiges",         "color": "#AAAAAA"},
]

FIELDS = [
    {"name": "reporter_role", "label": "Rolle der meldenden Person", "type": "select", "required": True,
     "options": [
         {"value": "affected",      "label": "Selbst betroffen"},
         {"value": "bystander",     "label": "Zeug:in / Unterstützer:in"},
         {"value": "friend_family", "label": "Freund:in / Familie der betroffenen Person"},
     ]},
    {"name": "taken_into_custody", "label": "Person in Gewahrsam genommen", "type": "boolean"},

    # --- placeholders, shown under "Weitere Angaben" ---
    {"name": "var_1", "label": "Platzhalter Titel", "type": "text", "group": "extra"},
    {"name": "var_2", "label": "Platzhalter Beschreibung", "type": "textarea", "group": "extra"},
    {"name": "var_3", "label": "Platzhalter Zahl", "type": "number", "group": "extra"},
    {"name": "var_4", "label": "Platzhalter Kategorie", "type": "select", "group": "extra",
     "options": ["option_1", "option_2", "option_3"]},
    {"name": "var_5", "label": "Platzhalter Zeitpunkt", "type": "datetime", "group": "extra"},
    {"name": "var_6", "label": "Platzhalter Merkmal", "type": "boolean", "group": "extra"},
]


def option_values(options):
    """Stored values of a list of options (dicts with "value" or plain strings)."""
    return [o["value"] if isinstance(o, dict) else o for o in options]


EVENT_TYPE_VALUES = option_values(EVENT_TYPES)
