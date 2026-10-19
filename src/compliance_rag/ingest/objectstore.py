"""ObjectStore abstraction over S3 (MinIO locally, moto in unit tests)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, Protocol

from botocore.exceptions import BotoCoreError, ClientError

NOT_FOUND = {"404", "NoSuchKey", "NotFound"}


class ObjectStore(Protocol):
    bucket: str

    async def ensure_bucket(self) -> None: ...
    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None: ...
    async def get(self, key: str) -> bytes: ...
    async def exists(self, key: str) -> bool: ...
    async def size(self, key: str) -> int: ...
    async def list(self, prefix: str) -> list[str]: ...
    async def delete(self, key: str) -> None: ...


class ObjectNotFound(KeyError):
    pass


class StorageUnavailable(OSError):
    """S3/MinIO cannot be reached or refused the request (BUILD.md §4.7: uploads answer 503)."""


def _not_found(exc: ClientError) -> bool:
    return exc.response.get("Error", {}).get("Code") in NOT_FOUND


async def _call[T](fn: Callable[[], T]) -> T:
    """Run a boto3 call off the event loop; botocore's own errors become StorageUnavailable."""

    def run() -> T:
        try:
            return fn()
        except ObjectNotFound:
            raise
        except ClientError as exc:
            if _not_found(exc):
                raise ObjectNotFound(str(exc.operation_name)) from exc
            raise StorageUnavailable(type(exc).__name__) from exc
        except BotoCoreError as exc:  # EndpointConnectionError, ConnectTimeoutError, ...
            raise StorageUnavailable(type(exc).__name__) from exc

    return await asyncio.to_thread(run)


class S3ObjectStore:
    """boto3-backed store; calls run in a worker thread so the event loop never blocks."""

    def __init__(
        self,
        endpoint_url: str | None,
        access_key: str,
        secret_key: str,
        bucket: str,
        region: str = "us-east-1",
        client: Any | None = None,
    ) -> None:
        if client is None:
            import boto3
            from botocore.config import Config

            client = boto3.client(
                "s3",
                endpoint_url=endpoint_url,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region,
                config=Config(
                    s3={"addressing_style": "path"},
                    retries={"max_attempts": 3},
                    connect_timeout=3,
                    read_timeout=30,
                ),
            )
        self.client = client
        self.bucket = bucket

    async def ensure_bucket(self) -> None:
        def _ensure() -> None:
            existing = {b["Name"] for b in self.client.list_buckets().get("Buckets", [])}
            if self.bucket not in existing:
                self.client.create_bucket(Bucket=self.bucket)

        await _call(_ensure)

    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        await _call(
            lambda: self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)
        )

    async def get(self, key: str) -> bytes:
        def _get() -> bytes:
            try:
                return bytes(self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read())
            except ClientError as exc:
                if _not_found(exc):
                    raise ObjectNotFound(key) from exc
                raise

        return await _call(_get)

    async def size(self, key: str) -> int:
        """Object size from a HEAD request (no download); ObjectNotFound when missing."""

        def _size() -> int:
            try:
                return int(self.client.head_object(Bucket=self.bucket, Key=key)["ContentLength"])
            except ClientError as exc:
                if _not_found(exc):
                    raise ObjectNotFound(key) from exc
                raise

        return await _call(_size)

    async def exists(self, key: str) -> bool:
        def _head() -> bool:
            try:
                self.client.head_object(Bucket=self.bucket, Key=key)
                return True
            except ClientError as exc:
                if _not_found(exc):
                    return False
                raise  # an outage is not "missing": StorageUnavailable

        return await _call(_head)

    async def list(self, prefix: str) -> list[str]:
        def _list() -> list[str]:
            keys: list[str] = []
            paginator = self.client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                keys += [o["Key"] for o in page.get("Contents", [])]
            return keys

        return await _call(_list)

    async def delete(self, key: str) -> None:
        await _call(lambda: self.client.delete_object(Bucket=self.bucket, Key=key))
