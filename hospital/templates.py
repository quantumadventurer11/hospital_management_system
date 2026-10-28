"""Text formatting and synthetic UI form templates."""
from __future__ import annotations
from typing import List

def format_section(title: str, items: List[str]) -> str:
    return f"{title}:\n" + "\n".join(f"- {item}" for item in items)

NOTE_TEMPLATES = [
    {
        "id": "routine_followup",
        "name": "Routine follow-up",
        "text": "Subjective: Patient reports stable symptoms.\nObjective: Vitals within normal limits.\nAssessment: Condition stable.\nPlan: Continue current therapy and reassess at next visit.",
    },
    {
        "id": "post_op_check",
        "name": "Post-op check",
        "text": "Subjective: Post-operative day 7, pain well controlled.\nObjective: Incision clean, dry, intact.\nAssessment: Healing appropriately.\nPlan: Remove sutures next visit, reinforce wound care instructions.",
    },
]
NOTE_TEMPLATE_LOOKUP = {tpl["id"]: tpl for tpl in NOTE_TEMPLATES}

BILLING_TEMPLATES = [
    {
        "id": "office_visit_established",
        "name": "Office Visit (99213)",
        "code": "99213",
        "amount": 150.0,
        "description": "Established patient office visit, moderate complexity.",
    },
    {
        "id": "telehealth_consult",
        "name": "Telehealth Consult (Q0506)",
        "code": "Q0506",
        "amount": 200.0,
        "description": "Telehealth rehabilitation consult.",
    },
]
BILLING_TEMPLATE_LOOKUP = {tpl["id"]: tpl for tpl in BILLING_TEMPLATES}

REMINDER_TEMPLATES = [
    {
        "id": "follow_up_two_weeks",
        "name": "Follow-up in 2 weeks",
        "text": "Reminder: schedule a follow-up appointment in two weeks.",
    },
    {
        "id": "lab_results_review",
        "name": "Review lab results",
        "text": "Reminder: review pending lab results and contact patient with findings.",
    },
]
REMINDER_TEMPLATE_LOOKUP = {tpl["id"]: tpl for tpl in REMINDER_TEMPLATES}
