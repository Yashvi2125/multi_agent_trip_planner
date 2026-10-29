"""Group votes on a proposed compromise. Used by the REST API and the Telegram inline buttons,
so both channels vote on the same record. Rule: a strict majority of trip members decides."""
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, NotFound
from app.models import (Channel, Conflict, ConflictStatus, ConflictVote, Message, SenderType, TripMember, User, Vote)
from app.schemas.trip import MessageOut
from app.services.event_hub import hub


def tallies(db: Session, conflict_ids: list[int], user_id: int | None) -> dict[int, dict]:
    out = {cid: {"accept": 0, "reject": 0, "mine": None} for cid in conflict_ids}
    if not conflict_ids:
        return out
    for cid, v, n in db.execute(select(ConflictVote.conflict_id, ConflictVote.vote, func.count())
                                .where(ConflictVote.conflict_id.in_(conflict_ids))
                                .group_by(ConflictVote.conflict_id, ConflictVote.vote)):
        out[cid][v.value] = n
    if user_id:
        for cv in db.scalars(select(ConflictVote).where(ConflictVote.conflict_id.in_(conflict_ids),
                                                        ConflictVote.user_id == user_id)):
            out[cv.conflict_id]["mine"] = cv.vote.value
    return out


def cast_vote(db: Session, trip_id: int, conflict_id: int, user: User, vote: Vote) -> tuple[Conflict, dict]:
    conflict = db.get(Conflict, conflict_id)
    if not conflict or conflict.trip_id != trip_id:
        raise NotFound("We couldn't find that disagreement.")
    if conflict.status is not ConflictStatus.open:
        raise AppError("conflict_closed", "The group has already settled this one.", 409)
    row = db.get(ConflictVote, (conflict_id, user.id))
    if row:
        row.vote = vote          # changing your mind is allowed while it's open
    else:
        db.add(ConflictVote(conflict_id=conflict_id, user_id=user.id, vote=vote))
    db.flush()
    members = db.scalar(select(func.count()).select_from(TripMember).where(TripMember.trip_id == trip_id)) or 1
    t = tallies(db, [conflict_id], user.id)[conflict_id]
    closed_msg = None
    if t["accept"] * 2 > members:
        conflict.status, conflict.resolved_at = ConflictStatus.accepted, datetime.now(timezone.utc)
        closed_msg = (f"The group accepted this compromise: {conflict.proposed_compromise} "
                      f"Say “@planner update the plan” to build it in.")
    elif t["reject"] * 2 > members:
        conflict.status, conflict.resolved_at = ConflictStatus.dismissed, datetime.now(timezone.utc)
        closed_msg = "The group passed on that compromise, so I'll leave the plan as it is."
    note = None
    if closed_msg:
        note = Message(trip_id=trip_id, sender_type=SenderType.system, source=Channel.system, text=closed_msg)
        db.add(note)
    db.commit()
    hub.publish_threadsafe(trip_id, {"type": "conflict.updated", "data": {
        "id": conflict_id, "status": conflict.status.value, "accept_votes": t["accept"], "reject_votes": t["reject"]}})
    if note:
        hub.publish_threadsafe(trip_id, {"type": "message.new",
                                         "data": MessageOut.model_validate(note).model_dump(mode="json")})
    return conflict, t
