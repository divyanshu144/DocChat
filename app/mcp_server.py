import json
import logging
import sys
from pathlib import Path
from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

logging.basicConfig(stream=sys.stderr, level=logging.INFO, force=True)
logger = logging.getLogger(__name__)

mcp = FastMCP("docchat")


@mcp.tool()
async def query_documents(
    query: Annotated[str, Field(description="Natural language question to ask the knowledge base")],
    source_ids: Annotated[
        list[str] | None,
        Field(description="Restrict retrieval to specific source IDs. Omit to search all."),
    ] = None,
) -> str:
    """Run the DocChat pipeline and return an answer with inline citations."""
    from app.agent.graph import agent_graph
    from app.agent.state import AgentState

    state: AgentState = {
        "query": query,
        "conversation_id": "",
        "sources_to_use": ["pdf", "youtube", "web"],
        "source_ids": source_ids or [],
        "retrieved_chunks": [],
        "answer": "",
        "critic_feedback": "",
        "needs_replan": False,
        "grounding_passed": False,
        "iteration": 0,
    }
    result = await agent_graph.ainvoke(state)
    return result["answer"]


@mcp.tool()
async def ingest_document(
    source_type: Annotated[
        Literal["pdf", "youtube", "web"],
        Field(description="Type of source: pdf, youtube, or web"),
    ],
    location: Annotated[
        str,
        Field(description="File path for pdf, YouTube URL for youtube, web URL for web"),
    ],
    name: Annotated[
        str | None,
        Field(description="Human-readable label. Defaults: pdf → file basename, youtube/web → URL"),
    ] = None,
) -> str:
    """Ingest a document into the knowledge base. Returns JSON: {source_id, source_type, name}."""
    if source_type == "pdf":
        from app.services.ingestion.pdf import ingest_pdf
        resolved_name = name or Path(location).name
        ext = Path(location).suffix.lower()
        content_type = {
            ".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".txt": "text/plain",
        }.get(ext, "application/pdf")
        source_id = await ingest_pdf(
            file_path=location, filename=resolved_name, content_type=content_type
        )
        return json.dumps({"source_id": source_id, "source_type": source_type, "name": resolved_name})

    if source_type == "youtube":
        from app.services.ingestion.youtube import ingest_youtube
        resolved_name = name or location
        source_id = await ingest_youtube(url=location)
        return json.dumps({"source_id": source_id, "source_type": source_type, "name": resolved_name})

    if source_type == "web":
        from app.services.ingestion.web import ingest_web
        resolved_name = name or location
        source_id = await ingest_web(url=location)
        return json.dumps({"source_id": source_id, "source_type": source_type, "name": resolved_name})

    raise ValueError(f"Unknown source_type: {source_type!r}")


@mcp.tool()
async def list_documents() -> str:
    """List all ingested documents across all source types.

    Returns JSON array: [{"source_id": "...", "type": "pdf|youtube|web", "name": "..."}, ...]
    Name field per type: pdf → filename payload field, youtube/web → title payload field.
    """
    from app.core.qdrant import get_qdrant_client
    from qdrant_client.http.exceptions import UnexpectedResponse

    _COLLECTIONS = {
        "pdf_chunks": ("pdf", "filename"),
        "youtube_chunks": ("youtube", "title"),
        "web_chunks": ("web", "title"),
    }

    client = get_qdrant_client()
    seen: dict[str, dict] = {}

    for collection_name, (source_type, name_field) in _COLLECTIONS.items():
        offset = None
        try:
            while True:
                results, next_offset = client.scroll(
                    collection_name=collection_name,
                    limit=100,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                for point in results:
                    payload = point.payload or {}
                    source_id = payload.get("source_id")
                    if source_id and source_id not in seen:
                        seen[source_id] = {
                            "source_id": source_id,
                            "type": source_type,
                            "name": payload.get(name_field, ""),
                        }
                if next_offset is None:
                    break
                offset = next_offset
        except UnexpectedResponse as exc:
            if getattr(exc, "status_code", None) == 404:
                logger.debug("Collection %s does not exist yet, skipping", collection_name)
            else:
                raise

    return json.dumps(list(seen.values()))


if __name__ == "__main__":
    mcp.run(transport="stdio")
