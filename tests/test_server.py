from typing import Any

import pytest

from scholar_search_mcp import server

from tests.helpers import RecordingSemanticClient, _streamable_http_event_payload


def test_build_http_app_uses_requested_path() -> None:
    app = server.build_http_app(path="/custom-mcp", transport="streamable-http")
    route_paths = [route.path for route in app.routes]

    assert "/custom-mcp" in route_paths


def test_run_server_uses_http_transport_settings() -> None:
    from scholar_search_mcp.runtime import run_server
    from scholar_search_mcp.settings import AppSettings

    calls: list[dict[str, Any]] = []

    class DummyApp:
        def run(self, **kwargs: Any) -> None:
            calls.append(kwargs)

    class DummyLogger:
        def info(self, *args: Any, **kwargs: Any) -> None:
            return None

        def warning(self, *args: Any, **kwargs: Any) -> None:
            return None

    run_server(
        app=DummyApp(),
        logger=DummyLogger(),
        settings=AppSettings.from_env(
            {
                "SCHOLAR_SEARCH_TRANSPORT": "streamable-http",
                "SCHOLAR_SEARCH_HTTP_HOST": "0.0.0.0",
                "SCHOLAR_SEARCH_HTTP_PORT": "9000",
                "SCHOLAR_SEARCH_HTTP_PATH": "/custom-mcp",
            }
        ),
    )

    assert calls == [
        {
            "transport": "streamable-http",
            "host": "0.0.0.0",
            "port": 9000,
            "path": "/custom-mcp",
        }
    ]


def test_streamable_http_app_handles_initialize_and_tool_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from starlette.testclient import TestClient

    semantic = RecordingSemanticClient()
    monkeypatch.setattr(server, "client", semantic)

    headers = {"accept": "application/json, text/event-stream"}
    with TestClient(server.http_app) as client:
        initialize = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0"},
            },
        }
        init_response = client.post("/mcp", json=initialize, headers=headers)
        session_id = init_response.headers["mcp-session-id"]
        init_payload = _streamable_http_event_payload(init_response.text)

        initialized = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        initialized_response = client.post(
            "/mcp",
            json=initialized,
            headers={**headers, "mcp-session-id": session_id},
        )

        call = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "search_papers_match",
                "arguments": {"query": "transformers"},
            },
        }
        call_response = client.post(
            "/mcp",
            json=call,
            headers={**headers, "mcp-session-id": session_id},
        )
        call_payload = _streamable_http_event_payload(call_response.text)

    assert init_response.status_code == 200
    assert initialized_response.status_code == 202
    instructions = init_payload["result"]["instructions"]
    assert "pagination.nextCursor" in instructions
    assert "opaque" in instructions
    assert "do not derive, edit, or fabricate" in instructions
    assert call_response.status_code == 200
    assert call_payload["result"]["structuredContent"] == {
        "paperId": "match-1",
        "title": "Best match",
    }
    assert call_payload["result"]["isError"] is False


@pytest.mark.asyncio
async def test_fastmcp_client_returns_structured_tool_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastmcp import Client

    semantic = RecordingSemanticClient()
    monkeypatch.setattr(server, "client", semantic)

    async with Client(server.app) as client:
        tools = await client.list_tools()
        tool_map = {tool.name: tool for tool in tools}
        result = await client.call_tool(
            "search_papers_match",
            {"query": "transformers"},
        )

    assert result.data == {"paperId": "match-1", "title": "Best match"}
    assert tool_map["search_papers"].annotations.readOnlyHint is True
    assert tool_map["search_papers"].annotations.idempotentHint is True
    assert tool_map["search_papers"].annotations.openWorldHint is True


@pytest.mark.asyncio
async def test_fastmcp_resource_and_prompt_support_agent_onboarding() -> None:
    from fastmcp import Client

    async with Client(server.app) as client:
        resources = await client.list_resources()
        prompts = await client.list_prompts()
        guide = await client.read_resource("guide://scholar-search/agent-workflows")
        plan = await client.get_prompt(
            "plan_scholar_search",
            {"topic": "transformers"},
        )

    assert any(
        str(resource.uri) == "guide://scholar-search/agent-workflows"
        for resource in resources
    )
    assert any(prompt.name == "plan_scholar_search" for prompt in prompts)
    assert "search_papers_bulk" in guide[0].text
    assert "pagination.nextCursor" in plan.messages[0].content.text
