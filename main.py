import hashlib
import random
import secrets
from contextlib import asynccontextmanager
from datetime import date
from difflib import SequenceMatcher
from typing import Literal, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import Base, SessionLocal, engine, get_db
from models import Application, AuditLog, Officer

NID = r"^(\d{10}|\d{13}|\d{17})$"
REJECTED = ["REJECTED", "REJECTED_DUPLICATE"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:  # 3 officer to check 
        if db.query(Officer).count() == 0:
            for i in (1, 2, 3):
                db.add(Officer(name=f"Officer {i}", api_key=f"officer-key-{i}"))
            db.commit()
    yield


app = FastAPI(title="Birth Registry API", lifespan=lifespan)



class ApplicationIn(BaseModel):
    child_name: str = Field(min_length=2, examples=["Your name"])
    child_dob: date
    child_gender: Literal["male", "female", "other"]
    father_nid: str = Field(pattern=NID, examples=["1234567890"])
    mother_nid: str = Field(pattern=NID, examples=["9876543210"])
    applicant_nid: str = Field(pattern=NID, examples=["1234567890"])
    fingerprint_template: str = Field(min_length=8, examples=["fp-demo-001"])
    iris_template: str = Field(min_length=8, examples=["iris-demo-001"])


class DecisionIn(BaseModel):
    decision: Literal["APPROVE", "REJECT", "NEEDS_INFO"]
    reason: str = Field(min_length=10, description="Rejection details")
    next_step: Optional[str] = None



def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.strip().lower(), b.strip().lower()).ratio()


def log(db: Session, application_id: int, actor: str, action: str, detail: str = ""):
    db.add(AuditLog(application_id=application_id, actor=actor, action=action, detail=detail))


def current_officer(x_officer_key: str = Header(...), db: Session = Depends(get_db)) -> Officer:
    officer = db.query(Officer).filter(Officer.api_key == x_officer_key).first()
    if not officer:
        raise HTTPException(401, "Wrong or missing X-Officer-Key header")
    return officer


# duplicate check
def run_checks(db: Session, d: ApplicationIn, fp: str, iris: str):
    verdict, flags = "CLEAR", []

    # check for duplicate applications with same parents and child date of birth
    same = db.query(Application).filter(
        Application.father_nid == d.father_nid,
        Application.mother_nid == d.mother_nid,
        Application.child_dob == d.child_dob,
        Application.status.notin_(REJECTED),
    ).all()
    for old in same:
        if old.child_gender == d.child_gender and similarity(old.child_name, d.child_name) >= 0.85:
            verdict = "DUPLICATE"
            flags.append(f"Duplicate: Your application is similar to {old.tracking_id} ")
        elif verdict != "DUPLICATE":
            verdict = "SUSPICIOUS"
            flags.append(f"Suspicious: {old.tracking_id} has the same parents and birth date, but different name/gender (Could be a duplicate or re-registration?)")

    # Rule 3: Same biometrics but different NID = Possibility of identity fraud
    clash = db.query(Application).filter(
        ((Application.fingerprint_hash == fp) | (Application.iris_hash == iris)),
        Application.applicant_nid != d.applicant_nid,
    ).first()
    if clash:
        if verdict != "DUPLICATE":
            verdict = "SUSPICIOUS"
        flags.append(f"Identity fraud suspicion: {clash.tracking_id} has the same biometrics but a different NID")

    return verdict, flags


@app.post("/applications", status_code=201, summary="Submit a new birth registration application")
def submit_application(data: ApplicationIn, db: Session = Depends(get_db)):
    if data.child_dob > date.today():
        raise HTTPException(422, "Child date of birth cannot be in the future")

    fp, iris = sha(data.fingerprint_template), sha(data.iris_template)
    verdict, flags = run_checks(db, data, fp, iris)

    status = {"DUPLICATE": "REJECTED_DUPLICATE", "SUSPICIOUS": "FLAGGED", "CLEAR": "UNDER_REVIEW"}[verdict]
    officer = None if verdict == "DUPLICATE" else random.choice(db.query(Officer).all()) 

    row = Application(
        tracking_id="TRK-" + secrets.token_hex(4).upper(),
        child_name=data.child_name, child_dob=data.child_dob, child_gender=data.child_gender,
        father_nid=data.father_nid, mother_nid=data.mother_nid, applicant_nid=data.applicant_nid,
        fingerprint_hash=fp, iris_hash=iris,
        status=status, flags="; ".join(flags),
        assigned_officer_id=officer.id if officer else None,
        decision_reason="; ".join(flags) if verdict == "DUPLICATE" else None,
        next_step="Duplicate application. If correct, appeal at the nearest registration office." if verdict == "DUPLICATE" else None,
    )
    db.add(row)
    db.flush()
    log(db, row.id, "system", "SUBMITTED", f"verdict={verdict}")
    if officer:
        log(db, row.id, "system", "ASSIGNED", "Random assignment to " + officer.name)
    db.commit()

    return {"tracking_id": row.tracking_id, "status": status, "verdict": verdict, "flags": flags}


# ---------- Public Tracking ----------
@app.get("/track/{tracking_id}", summary="Application status and timeline")
def track(tracking_id: str, db: Session = Depends(get_db)):
    row = db.query(Application).filter(Application.tracking_id == tracking_id).first()
    if not row:
        raise HTTPException(404, "Tracking ID not found")
    timeline = db.query(AuditLog).filter(AuditLog.application_id == row.id).order_by(AuditLog.id).all()
    return {
        "tracking_id": row.tracking_id,
        "status": row.status,
        "reason": row.decision_reason,
        "next_step": row.next_step,
        "certificate_no": row.certificate_no,
        "timeline": [{"action": t.action, "at": t.created_at} for t in timeline],
    }


# ---------- Officer Queue and Decisions ----------
@app.get("/officer/queue", summary="My Assigned Applications (Flagged First)")
def queue(officer: Officer = Depends(current_officer), db: Session = Depends(get_db)):
    rows = db.query(Application).filter(
        Application.assigned_officer_id == officer.id,
        Application.status.in_(["FLAGGED", "UNDER_REVIEW"]),
    ).all()
    rows.sort(key=lambda r: r.status != "FLAGGED")
    return [
        {"id": r.id, "tracking_id": r.tracking_id, "child_name": r.child_name,
         "status": r.status, "flags": r.flags}
        for r in rows
    ]


@app.post("/officer/applications/{app_id}/decision", summary="Decision with reason")
def decide(app_id: int, body: DecisionIn,
           officer: Officer = Depends(current_officer), db: Session = Depends(get_db)):
    row = db.get(Application, app_id)
    if not row:
        raise HTTPException(404, "Application not found")
    if row.assigned_officer_id != officer.id:
        raise HTTPException(403, "This application is not assigned to you")
    if row.status not in ("FLAGGED", "UNDER_REVIEW"):
        raise HTTPException(409, f"Current status {row.status}, decision cannot be made")

    row.decision_reason, row.next_step = body.reason, body.next_step
    if body.decision == "APPROVE":
        row.status = "CERTIFICATE_ISSUED"
        row.certificate_no = f"BC-{date.today().year}-{secrets.token_hex(4).upper()}"
    elif body.decision == "REJECT":
        row.status = "REJECTED"
    else:
        row.status = "NEEDS_INFO"

    # ---------- Helper 3: Audit Log ----------
    log(db, row.id, officer.name, body.decision, body.reason)
    db.commit()
    return {"tracking_id": row.tracking_id, "status": row.status, "certificate_no": row.certificate_no}
