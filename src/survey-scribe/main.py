# Copyright (c) Microsoft. All rights reserved.

"""Survey-scribe hosted agent entrypoint.

Accepts an input file name from the user message, downloads the PDF from
Blob Storage, runs extraction, and uploads JSON output back to Blob.
"""

import asyncio
import logging
import re

from azure.ai.agentserver.responses import (
    CreateResponse,
    ResponseContext,
    ResponsesAgentServerHost,
    ResponsesServerOptions,
    TextResponse,
)
logger = logging.getLogger(__name__)

from foundry_blob_agent import run_from_blob

app = ResponsesAgentServerHost(
    options=ResponsesServerOptions(default_fetch_history_count=20),
)

_FILE_NAME_RE = re.compile(r"[^\s\\/]+\.pdf$", re.IGNORECASE)


def _extract_file_name(user_input: str) -> str | None:
    # Accept either a plain file name or natural language containing one.
    direct = user_input.strip().strip('"')
    if _FILE_NAME_RE.fullmatch(direct):
        return direct

    match = _FILE_NAME_RE.search(user_input)
    return match.group(0) if match else None


@app.response_handler
async def handler(
    request: CreateResponse,
    context: ResponseContext,
    _cancellation_signal: asyncio.Event,
):
    """Run survey extraction for one file name provided by the user."""
    user_input = (await context.get_input_text() or "").strip()
    file_name = _extract_file_name(user_input)

    if not file_name:
        return TextResponse(
            context,
            request,
            text=(
                "Please provide a PDF file name only, for example: "
                "BFA_EBCVM2009-10 Main questionnaire.pdf"
            ),
        )

    try:
        result = await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: run_from_blob(file_name),
        )
    except Exception as exc:  # pragma: no cover - runtime integration path
        logger.exception("Survey extraction failed for %s", file_name)
        return TextResponse(
            context,
            request,
            text=f"Failed to process {file_name}: {exc}",
        )

    status = result.get("status", "unknown")
    output_blob = result.get("output_blob", "")
    message = result.get("message", "")

    if status == "success":
        text = (
            f"Processed {file_name} successfully. "
            f"Output uploaded to {output_blob}."
        )
    elif status == "skipped":
        text = (
            f"Processing skipped for {file_name}. "
            f"{message}"
        )
    else:
        text = f"Processing finished with status '{status}' for {file_name}."

    return TextResponse(context, request, text=text)


app.run()
