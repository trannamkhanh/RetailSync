"""Per-job SQL Server locks shared by manual runners and scheduler workers."""

from collections.abc import Iterator
from contextlib import contextmanager
import logging

from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from app.core.db import database_url


logger = logging.getLogger(__name__)


@contextmanager
def job_lock(name: str) -> Iterator[bool]:
    """Yield whether the session acquired this job; never pool a locked session."""
    engine = create_engine(database_url(), poolclass=NullPool,
                           connect_args={"timeout": 5}, hide_parameters=True)
    connection = None
    acquired = False
    resource = f"retailsync-job-{name}"
    try:
        connection = engine.connect()
        connection = connection.execution_options(isolation_level="AUTOCOMMIT")
        result = connection.exec_driver_sql(
            "SET NOCOUNT ON; DECLARE @result int; "
            "EXEC @result = sp_getapplock @Resource = ?, @LockMode = 'Exclusive', "
            "@LockOwner = 'Session', @LockTimeout = 0; SELECT @result", (resource,),
        ).scalar()
        if result == -1:
            yield False
        elif result is not None and result >= 0:
            acquired = True
            yield True
        else:
            raise RuntimeError(f"Job lock acquisition failed with result {result}")
    finally:
        try:
            if connection is not None:
                try:
                    if acquired:
                        connection.exec_driver_sql(
                            "EXEC sp_releaseapplock @Resource = ?, @LockOwner = 'Session'",
                            (resource,),
                        )
                except Exception:
                    logger.warning("Releasing job lock %s failed; closing its session", name,
                                   exc_info=True)
                finally:
                    connection.close()
        finally:
            engine.dispose()
