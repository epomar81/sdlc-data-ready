"""Bounded local file reads without blocking the event loop."""

import asyncio

from story_slicer.ports.errors import InputError
from story_slicer.ports.filesystem import FileReadRequest


class LocalFileSystem:
    async def read(self, request: FileReadRequest) -> bytes:
        return await asyncio.to_thread(self._read, request)

    def _read(self, request: FileReadRequest) -> bytes:
        try:
            with open(request.path, "rb") as source:
                content = source.read(request.max_bytes + 1)
        except OSError, ValueError:
            raise InputError("Requirement file cannot be read") from None
        if len(content) > request.max_bytes:
            raise InputError("Requirement file exceeds the configured size limit")
        return content
