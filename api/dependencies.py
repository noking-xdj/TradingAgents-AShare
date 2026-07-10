"""Shared FastAPI authentication dependencies.

This module intentionally has no dependency on ``api.main`` so routers can
reuse authentication without creating an import cycle.
"""

from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from api.database import UserDB, get_db_ctx
from api.services import auth_service, token_service


auth_scheme = HTTPBearer(auto_error=False)


class RequireUser:
    def __init__(self, allow_api_token: bool = True):
        self.allow_api_token = allow_api_token

    def __call__(
        self,
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(auth_scheme),
    ) -> UserDB:
        if not credentials:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")

        token = credentials.credentials

        with get_db_ctx() as db:
            # Web JWT remains the first authentication method attempted.
            try:
                payload = auth_service.decode_access_token(token)
                user_id = str(payload.get("sub") or "")
                user = auth_service.get_user_by_id(db, user_id)
                if user and user.is_active:
                    db.expunge(user)
                    return user
            except Exception:
                pass

            # API tokens remain available only on dependencies that opt in.
            if self.allow_api_token and token.startswith(token_service.TOKEN_PREFIX):
                user = token_service.verify_token(db, token)
                if user and user.is_active:
                    db.expunge(user)
                    return user

        detail = (
            "身份验证失败或该接口不支持 API Token 访问"
            if self.allow_api_token
            else "该接口仅限网页端登录访问"
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


require_api_user = RequireUser(allow_api_token=True)
require_web_user = RequireUser(allow_api_token=False)


def optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(auth_scheme),
) -> Optional[UserDB]:
    if not credentials:
        return None
    try:
        payload = auth_service.decode_access_token(credentials.credentials)
    except Exception:
        return None
    user_id = str(payload.get("sub") or "")
    if not user_id:
        return None
    with get_db_ctx() as db:
        user = auth_service.get_user_by_id(db, user_id)
        if user:
            db.expunge(user)
        return user
