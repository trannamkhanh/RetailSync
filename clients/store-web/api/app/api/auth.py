"""Customer accounts: register, log in, log out, and the current profile.

The session lives in an httpOnly cookie; the SPA only learns *who* is signed in
through ``GET /api/auth/me``.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.customer_db import get_customer_db
from app.customer_models import Customer
from app.errors import ApiError
from app.schemas import AuthSession, CustomerProfile, LoginRequest, RegisterRequest
from app.security import (
    COOKIE_NAME,
    clear_session_cookie,
    create_session,
    current_customer,
    delete_session,
    hash_password,
    purge_expired_sessions,
    set_session_cookie,
    verify_password,
)

router = APIRouter()

GENERIC_LOGIN_ERROR = "Email hoặc mật khẩu không đúng."


def _profile(customer: Customer) -> CustomerProfile:
    return CustomerProfile(
        customer_id=customer.customer_id,
        email=customer.email,
        full_name=customer.full_name,
    )


@router.post("/auth/register", response_model=AuthSession, status_code=201)
def register(
    payload: RegisterRequest,
    response: Response,
    session: Session = Depends(get_customer_db),
) -> AuthSession:
    """Create an account and sign the customer in immediately."""
    email = payload.email.strip().casefold()
    if "@" not in email:
        raise ApiError(422, "VALIDATION_ERROR", "Email không hợp lệ.")

    existing = session.execute(
        select(Customer.customer_id).where(Customer.email == email)
    ).scalar_one_or_none()
    if existing is not None:
        raise ApiError(409, "EMAIL_TAKEN", "Email này đã được đăng ký.")

    customer = Customer(
        email=email,
        full_name=payload.full_name.strip(),
        password_hash=hash_password(payload.password),
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    session.add(customer)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        raise ApiError(409, "EMAIL_TAKEN", "Email này đã được đăng ký.") from None

    purge_expired_sessions(session)
    token = create_session(session, customer.customer_id)
    session.commit()

    set_session_cookie(response, token)
    return AuthSession(customer=_profile(customer))


@router.post("/auth/login", response_model=AuthSession)
def login(
    payload: LoginRequest,
    response: Response,
    session: Session = Depends(get_customer_db),
) -> AuthSession:
    """Start a session for a known email and password."""
    email = payload.email.strip().casefold()
    customer = session.execute(
        select(Customer).where(Customer.email == email)
    ).scalar_one_or_none()

    # Same message for an unknown email and a wrong password, so the reply does
    # not reveal which accounts exist.
    if customer is None or not verify_password(payload.password, customer.password_hash):
        raise ApiError(401, "INVALID_CREDENTIALS", GENERIC_LOGIN_ERROR)

    purge_expired_sessions(session)
    token = create_session(session, customer.customer_id)
    session.commit()

    set_session_cookie(response, token)
    return AuthSession(customer=_profile(customer))


@router.post("/auth/logout", status_code=204)
def logout(
    request: Request,
    response: Response,
    session: Session = Depends(get_customer_db),
) -> Response:
    """Delete the session row and clear the cookie.

    Always 204: logging out twice, or with an expired session, is not an error.
    """
    delete_session(session, request.cookies.get(COOKIE_NAME))
    session.commit()
    clear_session_cookie(response)
    response.status_code = 204
    return response


@router.get("/auth/me", response_model=AuthSession)
def me(customer: Customer = Depends(current_customer)) -> AuthSession:
    """The signed-in customer, or 401 when there is no valid session."""
    return AuthSession(customer=_profile(customer))
