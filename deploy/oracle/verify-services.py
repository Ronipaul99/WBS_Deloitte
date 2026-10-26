"""Run inside the worker container after its dependencies are ready.

docker compose -f compose.services.yml exec -T worker python - < verify-services.py
"""

import asyncio
import base64
import json
import socket
import tempfile
from pathlib import Path

from redis.asyncio import Redis
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import engine
from app.services.ingestion.scanning import ClamAVScanner, MalwareScanStatus
from app.services.storage import get_upload_storage
from app.worker import celery_app


async def verify_dependencies() -> None:
    settings = get_settings()
    assert not settings.tasks_eager
    redis = Redis.from_url(settings.redis_url, socket_connect_timeout=5, socket_timeout=5)
    try:
        assert await redis.ping()
    finally:
        await redis.aclose()
    print(json.dumps({"redis_authenticated_ping": "passed"}), flush=True)

    with socket.create_connection(("redis", 6379), timeout=5) as connection:
        connection.sendall(b"*1\r\n$4\r\nPING\r\n")
        assert b"NOAUTH" in connection.recv(256)
    print(json.dumps({"redis_rejects_unauthenticated_clients": "passed"}), flush=True)

    try:
        async with engine.connect() as connection:
            await connection.execute(text("SET TRANSACTION READ ONLY"))
            assert await connection.scalar(text("SELECT 1")) == 1
            role = (await connection.execute(text(
                "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
            ))).one()
            assert not role.rolsuper and not role.rolbypassrls
            assert not await connection.scalar(text(
                "SELECT pg_has_role(current_user, datdba, 'MEMBER') "
                "FROM pg_database WHERE datname = current_database()"
            ))
    finally:
        await engine.dispose()
    print(json.dumps({"runtime_database_connection": "passed"}), flush=True)

    await get_upload_storage().check()
    print(json.dumps({"object_storage_connection": "passed"}), flush=True)

    scanner = ClamAVScanner(settings)
    await scanner.check()
    with tempfile.TemporaryDirectory(prefix="wbs-scanner-check-") as directory:
        clean = Path(directory) / "clean.txt"
        clean.write_text("Harmless WBS scanner connectivity check.", encoding="utf-8")
        assert (await scanner.scan(clean)).status == MalwareScanStatus.CLEAN
        eicar = Path(directory) / "scanner-test.txt"
        # Standard harmless EICAR antivirus test string, not executable malware.
        eicar.write_bytes(base64.b64decode(
            "WDVPIVAlQEFQWzRcUFpYNTQoUF4pN0NDKTd9JEVJQ0FSLVNUQU5EQVJELUFOVElWSVJVUy1URVNULUZJTEUhJEgrSCo="
        ))
        assert (await scanner.scan(eicar)).status == MalwareScanStatus.INFECTED
    print(json.dumps({"clamav_clean_file": "passed", "clamav_eicar_detection": "passed"}),
          flush=True)


if __name__ == "__main__":
    try:
        asyncio.run(verify_dependencies())
        assert celery_app.control.ping(timeout=10)
        # With ingestion disabled this registered task is a safe no-op. The test
        # still verifies Redis publication, worker execution, and result storage.
        if not get_settings().document_ingestion_enabled:
            task = celery_app.send_task("wbs.reconcile_document_ingestion")
            task.get(timeout=30)
            assert task.successful()
            task.forget()
            print(json.dumps({"celery_task_round_trip": "passed"}), flush=True)
        else:
            print(json.dumps({"celery_worker_ping": "passed"}), flush=True)
    except Exception as error:
        # Do not disclose connection strings in database/Redis exception messages.
        print(json.dumps({"verification_error_type": type(error).__name__}), flush=True)
        raise SystemExit(1) from None
