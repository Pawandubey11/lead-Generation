"""
crm_service.py
--------------
SQLite-backed CRM Pipeline, Activity Timeline, and Persistent Audit/Opportunity
storage for LeadPulse.

Pipeline Stages:
  New -> Qualified -> Contacted -> Meeting Scheduled -> Proposal Sent -> Won | Lost
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import database.auth_db as db

CRM_STAGES = [
    "New",
    "Qualified",
    "Contacted",
    "Meeting Scheduled",
    "Proposal Sent",
    "Won",
    "Lost",
]

VALID_STAGES_SET = set(CRM_STAGES)


def _lead_key(business_name: str) -> str:
    return (business_name or "").strip().lower()


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_crm_record(business_name: str) -> Dict[str, Any]:
    key = _lead_key(business_name)
    if not key:
        return {}
    conn = db.get_db_connection()
    try:
        row = conn.execute("SELECT * FROM lead_crm WHERE lead_key = ?", (key,)).fetchone()
        acts = conn.execute(
            "SELECT id, activity_type, old_value, new_value, note, actor, created_at "
            "FROM lead_activities WHERE lead_key = ? ORDER BY id DESC LIMIT 50",
            (key,),
        ).fetchall()
    finally:
        conn.close()

    if row:
        rec = dict(row)
    else:
        rec = {
            "lead_key": key,
            "business_name": business_name,
            "stage": "New",
            "owner": "",
            "follow_up_date": "",
            "notes": "",
            "last_contacted_at": "",
            "estimated_value": 0,
            "created_at": "",
            "updated_at": "",
        }
    rec["activities"] = [dict(a) for a in acts]
    return rec


def get_all_crm_map() -> Dict[str, Dict[str, Any]]:
    """Return {lead_key: crm_dict} for fast dashboard/analytics joins."""
    conn = db.get_db_connection()
    try:
        rows = conn.execute("SELECT * FROM lead_crm").fetchall()
    finally:
        conn.close()
    return {r["lead_key"]: dict(r) for r in rows}


def update_crm_record(
    business_name: str,
    stage: Optional[str] = None,
    owner: Optional[str] = None,
    follow_up_date: Optional[str] = None,
    notes: Optional[str] = None,
    estimated_value: Optional[float] = None,
    mark_contacted: bool = False,
    actor: str = "User",
) -> Dict[str, Any]:
    """Create or update CRM fields and log any stage/owner/follow-up transitions."""
    key = _lead_key(business_name)
    if not key:
        raise ValueError("business_name is required")

    if stage is not None and stage not in VALID_STAGES_SET:
        raise ValueError(f"Invalid CRM stage '{stage}'. Valid stages: {', '.join(CRM_STAGES)}")

    now = _now_str()
    conn = db.get_db_connection()
    try:
        existing = conn.execute("SELECT * FROM lead_crm WHERE lead_key = ?", (key,)).fetchone()
        if existing:
            cur = dict(existing)
        else:
            cur = {
                "lead_key": key,
                "business_name": business_name.strip(),
                "stage": "New",
                "owner": "",
                "follow_up_date": "",
                "notes": "",
                "last_contacted_at": "",
                "estimated_value": 0.0,
                "created_at": now,
                "updated_at": now,
            }
            conn.execute(
                "INSERT INTO lead_crm (lead_key, business_name, stage, owner, follow_up_date, notes, last_contacted_at, estimated_value, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    cur["lead_key"], cur["business_name"], cur["stage"], cur["owner"],
                    cur["follow_up_date"], cur["notes"], cur["last_contacted_at"],
                    cur["estimated_value"], cur["created_at"], cur["updated_at"],
                ),
            )

        activities: List[tuple] = []
        new_stage = stage if stage is not None else cur["stage"]
        if stage is not None and stage != cur["stage"]:
            activities.append((key, business_name.strip(), "stage_change", cur["stage"], stage, f"Stage moved from {cur['stage']} to {stage}", actor, now))

        new_owner = owner.strip() if owner is not None else cur["owner"]
        if owner is not None and new_owner != cur["owner"]:
            activities.append((key, business_name.strip(), "owner_change", cur["owner"], new_owner, f"Owner set to {new_owner or 'Unassigned'}", actor, now))

        new_followup = follow_up_date.strip() if follow_up_date is not None else cur["follow_up_date"]
        if follow_up_date is not None and new_followup != cur["follow_up_date"]:
            activities.append((key, business_name.strip(), "follow_up", cur["follow_up_date"], new_followup, f"Follow-up scheduled for {new_followup or 'Cleared'}", actor, now))

        new_notes = notes.strip() if notes is not None else cur["notes"]
        if notes is not None and new_notes != cur["notes"] and new_notes:
            activities.append((key, business_name.strip(), "note", "", "", new_notes[:500], actor, now))

        new_val = float(estimated_value) if estimated_value is not None else float(cur.get("estimated_value") or 0)

        new_last_contacted = cur["last_contacted_at"]
        if mark_contacted or (stage in ("Contacted", "Meeting Scheduled", "Proposal Sent") and stage != cur["stage"]):
            new_last_contacted = now
            if mark_contacted:
                activities.append((key, business_name.strip(), "contact", "", now, "Logged prospect contact", actor, now))

        conn.execute(
            "UPDATE lead_crm SET business_name=?, stage=?, owner=?, follow_up_date=?, notes=?, last_contacted_at=?, estimated_value=?, updated_at=? WHERE lead_key=?",
            (business_name.strip(), new_stage, new_owner, new_followup, new_notes, new_last_contacted, new_val, now, key),
        )
        for act in activities:
            conn.execute(
                "INSERT INTO lead_activities (lead_key, business_name, activity_type, old_value, new_value, note, actor, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                act,
            )
        conn.commit()
    finally:
        conn.close()

    return get_crm_record(business_name)


def add_crm_activity(business_name: str, activity_type: str, note: str, actor: str = "User") -> Dict[str, Any]:
    key = _lead_key(business_name)
    if not key:
        raise ValueError("business_name is required")
    now = _now_str()
    # Ensure lead_crm parent row exists
    update_crm_record(business_name, actor=actor)
    conn = db.get_db_connection()
    try:
        conn.execute(
            "INSERT INTO lead_activities (lead_key, business_name, activity_type, old_value, new_value, note, actor, created_at) "
            "VALUES (?, ?, ?, '', '', ?, ?, ?)",
            (key, business_name.strip(), activity_type.strip() or "note", note.strip(), actor, now),
        )
        if activity_type == "contact":
            conn.execute("UPDATE lead_crm SET last_contacted_at=?, updated_at=? WHERE lead_key=?", (now, now, key))
        conn.commit()
    finally:
        conn.close()
    return get_crm_record(business_name)


def save_lead_audit(
    business_name: str,
    audit_data: Dict[str, Any],
    opportunity_data: Dict[str, Any],
    mx_data: Optional[Dict[str, Any]] = None,
) -> None:
    key = _lead_key(business_name)
    if not key:
        return
    now = _now_str()
    conn = db.get_db_connection()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO lead_audits (lead_key, business_name, audit_json, opportunity_json, mx_json, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                key,
                business_name.strip(),
                json.dumps(audit_data or {}),
                json.dumps(opportunity_data or {}),
                json.dumps(mx_data or {}),
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_lead_audit(business_name: str) -> Optional[Dict[str, Any]]:
    key = _lead_key(business_name)
    if not key:
        return None
    conn = db.get_db_connection()
    try:
        row = conn.execute("SELECT * FROM lead_audits WHERE lead_key = ?", (key,)).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return {
        "business_name": row["business_name"],
        "audit": json.loads(row["audit_json"] or "{}"),
        "opportunity": json.loads(row["opportunity_json"] or "{}"),
        "mx": json.loads(row["mx_json"] or "{}"),
        "updated_at": row["updated_at"],
    }


def get_all_audits_map() -> Dict[str, Dict[str, Any]]:
    conn = db.get_db_connection()
    try:
        rows = conn.execute("SELECT * FROM lead_audits").fetchall()
    finally:
        conn.close()
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        out[r["lead_key"]] = {
            "business_name": r["business_name"],
            "audit": json.loads(r["audit_json"] or "{}"),
            "opportunity": json.loads(r["opportunity_json"] or "{}"),
            "mx": json.loads(r["mx_json"] or "{}"),
            "updated_at": r["updated_at"],
        }
    return out
