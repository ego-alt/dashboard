"""API tokens: long-lived credentials for native apps (the scanner), which can't
hold a session cookie. Only a token's hash is stored."""
from fastapi import APIRouter, Depends, Form, HTTPException
from sqlalchemy.orm import Session as DbSession

from app.auth import current_user, mint_api_token
from app.db import get_db
from app.models import ApiToken, User

router = APIRouter(prefix="/auth/tokens", tags=["tokens"])


@router.get("")
def list_api_tokens(user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    toks = (
        db.query(ApiToken)
        .filter(ApiToken.user_id == user.id)
        .order_by(ApiToken.created_at.desc())
        .all()
    )
    return [
        {
            "id": t.id,
            "name": t.name,
            "prefix": t.prefix,
            "created_at": t.created_at.isoformat(),
            "last_used_at": t.last_used_at.isoformat() if t.last_used_at else None,
        }
        for t in toks
    ]


@router.post("")
def create_api_token(
    name: str = Form(...),
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    """Mint a token for the current user. The raw value is returned exactly
    once (only its hash is persisted) — the client must store it now."""
    raw = mint_api_token(db, user, name=name)
    return {"ok": True, "token": raw}


@router.delete("/{token_id}")
def delete_api_token(
    token_id: int,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    tok = (
        db.query(ApiToken)
        .filter(ApiToken.id == token_id, ApiToken.user_id == user.id)
        .one_or_none()
    )
    if tok is None:
        raise HTTPException(status_code=404, detail="not found")
    db.delete(tok)
    db.commit()
    return {"ok": True}
