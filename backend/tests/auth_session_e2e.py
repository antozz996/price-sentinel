"""Seven-day session, logout and token separation on disposable PostgreSQL.

Only run via run_ci_disposable_e2e.py or another throwaway database.
All accounts are synthetic.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone

import httpx
import psycopg2
from jose import jwt

from app.config import settings
from app.main import app
from app.services.auth import REFRESH_TOKEN_TYPE, create_access_token, decode_access_token, hash_password

DSN = os.environ["TEST_DATABASE_DSN"]
EMAIL = "session@example.com"
PASSWORD = "synthetic-password-1"


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print(f"PASS: {name}", flush=True)


def execute(sql: str, *params) -> None:
    with psycopg2.connect(DSN) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)


def seed() -> None:
    execute(
        "insert into utenti(id,email,password_hash,ruolo,location_id,attivo,refresh_token_version)"
        " values (1,%s,%s,'admin',null,true,1)",
        EMAIL,
        hash_password(PASSWORD),
    )


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def login(client: httpx.AsyncClient, password: str = PASSWORD) -> dict:
    response = await client.post("/api/v1/auth/login", json={"email": EMAIL, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


async def run() -> None:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://testserver") as client:
        session = await login(client)
        claims = decode_access_token(session["refresh_token"])
        lifetime = datetime.fromtimestamp(claims["exp"], timezone.utc) - datetime.now(timezone.utc)
        check("login returns a refresh token lasting 7 days", timedelta(days=6, hours=23) < lifetime <= timedelta(days=7))

        me = await client.get("/api/v1/auth/me", headers=bearer(session["access_token"]))
        check("access token works", me.status_code == 200)

        me = await client.get("/api/v1/auth/me", headers=bearer(session["refresh_token"]))
        check("refresh token is refused as an access token", me.status_code == 401)

        refreshed = await client.post("/api/v1/auth/refresh", json={"refresh_token": session["access_token"]})
        check("access token is refused as a refresh token", refreshed.status_code == 401)

        expired_access = create_access_token(1, "admin", expires_delta=timedelta(minutes=-1), session_version=1)
        me = await client.get("/api/v1/auth/me", headers=bearer(expired_access))
        check("expired access token is refused", me.status_code == 401)

        refreshed = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": session["refresh_token"]},
            headers=bearer(expired_access),
        )
        check("session survives an expired access token", refreshed.status_code == 200)
        renewed = refreshed.json()
        me = await client.get("/api/v1/auth/me", headers=bearer(renewed["access_token"]))
        check("renewed access token works", me.status_code == 200)
        check(
            "renewal moves the 7-day limit forward",
            decode_access_token(renewed["refresh_token"])["exp"] >= claims["exp"],
        )

        expired_refresh = jwt.encode(
            {
                "sub": "1",
                "typ": REFRESH_TOKEN_TYPE,
                "rv": 1,
                "exp": datetime.now(timezone.utc) - timedelta(seconds=1),
            },
            settings.SECRET_KEY,
            algorithm=settings.ALGORITHM,
        )
        refreshed = await client.post("/api/v1/auth/refresh", json={"refresh_token": expired_refresh})
        check("session ends after 7 days without activity", refreshed.status_code == 401)

        legacy = create_access_token(1, "admin")
        refreshed = await client.post("/api/v1/auth/refresh", headers=bearer(legacy))
        check(
            "sessions opened before this version keep working without gaining a refresh token",
            refreshed.status_code == 200 and refreshed.json()["refresh_token"] is None,
        )

        refreshed = await client.post("/api/v1/auth/refresh")
        check("refresh without credentials is refused", refreshed.status_code == 401)

        logout = await client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": renewed["refresh_token"]},
            headers=bearer(renewed["access_token"]),
        )
        check("logout succeeds", logout.status_code == 200)
        me = await client.get("/api/v1/auth/me", headers=bearer(renewed["access_token"]))
        check("logout revokes the access token immediately", me.status_code == 401)
        refreshed = await client.post("/api/v1/auth/refresh", json={"refresh_token": renewed["refresh_token"]})
        check("logout revokes the refresh token", refreshed.status_code == 401)
        repeated = await client.post("/api/v1/auth/logout", json={"refresh_token": renewed["refresh_token"]})
        check("repeating logout is harmless", repeated.status_code == 200)

        first_device = await login(client)
        second_device = await login(client)
        changed = await client.post(
            "/api/v1/auth/change-password",
            json={"current_password": PASSWORD, "new_password": "synthetic-password-2"},
            headers=bearer(first_device["access_token"]),
        )
        check("password change succeeds", changed.status_code == 200)
        me = await client.get("/api/v1/auth/me", headers=bearer(changed.json()["access_token"]))
        check("password change keeps this device signed in", me.status_code == 200)
        refreshed = await client.post("/api/v1/auth/refresh", json={"refresh_token": second_device["refresh_token"]})
        check("password change ends other sessions", refreshed.status_code == 401)

        session = await login(client, "synthetic-password-2")
        execute("update utenti set attivo=false where id=1")
        refreshed = await client.post("/api/v1/auth/refresh", json={"refresh_token": session["refresh_token"]})
        check("a disabled account cannot renew its session", refreshed.status_code == 401)


if __name__ == "__main__":
    seed()
    asyncio.run(run())
    print("PASS: auth session E2E", flush=True)
