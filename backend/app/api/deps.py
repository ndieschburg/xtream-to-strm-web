from typing import AsyncGenerator, Callable, Generator, List, Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from pydantic import ValidationError
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core import security
from app.db.session import SessionLocal

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/login/access-token")

def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_current_user(token: str = Depends(oauth2_scheme)) -> str:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        token_data = payload.get("sub")
        if token_data is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Could not validate credentials",
            )
    except (JWTError, ValidationError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
        )
    return token_data


async def xtream_clients() -> AsyncGenerator[Callable[..., "XtreamClient"], None]:
    """Hand out XtreamClients and close them once the response has been sent.

    Each XtreamClient owns an httpx connection pool. Endpoints that built one
    inline never closed it, so every request leaked a pool (and its sockets) for
    the lifetime of the process.
    """
    from app.services.xtream import XtreamClient

    created: List["XtreamClient"] = []

    def factory(*args, **kwargs) -> "XtreamClient":
        client = XtreamClient(*args, **kwargs)
        created.append(client)
        return client

    try:
        yield factory
    finally:
        for client in created:
            try:
                await client.aclose()
            except Exception:
                pass
            try:
                client.close()
            except Exception:
                pass
