"""ObjectStore abstraction over S3 (MinIO locally, moto in unit tests)."""

from __future__ import annotations

import asyncio
from typing import Any, Protocol


class ObjectStore(Protocol):
    bucket: str

    async def ensure_bucket(self) -> None: ...
    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None: ...
    async def get(self, key: str) -> bytes: ...
    async def exists(self, key: str) -> bool: ...
    async def list(self, prefix: str) -> list[str]: ...
    async def delete(self, key: str) -> None: ...


class ObjectNotFound(KeyError):
    pass


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

        await asyncio.to_thread(_ensure)

    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        await asyncio.to_thread(
            self.client.put_object, Bucket=self.bucket, Key=key, Body=data, ContentType=content_type
        )

    async def get(self, key: str) -> bytes:
        def _get() -> bytes:
            try:
                return bytes(self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read())
            except self.client.exceptions.NoSuchKey as exc:
                raise ObjectNotFound(key) from exc

        return await asyncio.to_thread(_get)

    async def exists(self, key: str) -> bool:
        def _head() -> bool:
            try:
                self.client.head_object(Bucket=self.bucket, Key=key)
                return True
            except Exception:
                return False

        return await asyncio.to_thread(_head)

    async def list(self, prefix: str) -> list[str]:
        def _list() -> list[str]:
            keys: list[str] = []
            paginator = self.client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                keys += [o["Key"] for o in page.get("Contents", [])]
            return keys

        return await asyncio.to_thread(_list)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self.client.delete_object, Bucket=self.bucket, Key=key)
