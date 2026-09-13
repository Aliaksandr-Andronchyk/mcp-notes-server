import io
import json

import pytest

from mcp_notes.server import PROTOCOL_VERSION, Server, serve
from mcp_notes.store import Store


@pytest.fixture
def server(tmp_path):
    store = Store(tmp_path / "notes.db")
    yield Server(store)
    store.close()


def call(server, name, **arguments):
    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
    )
    return response["result"]


def payload(result):
    return json.loads(result["content"][0]["text"])


def test_initialize_answers_with_server_info(server):
    result = server.handle(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}}
    )["result"]

    assert result["protocolVersion"] == "2025-06-18"
    assert result["serverInfo"]["name"] == "mcp-notes-server"
    assert "tools" in result["capabilities"]


def test_initialize_falls_back_on_unknown_protocol(server):
    result = server.handle(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "1999-01-01"}}
    )["result"]

    assert result["protocolVersion"] == PROTOCOL_VERSION


def test_tools_list_schemas_are_well_formed(server):
    tools = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]

    assert {t["name"] for t in tools} == {
        "add_note",
        "search_notes",
        "list_notes",
        "get_note",
        "update_note",
        "delete_note",
        "list_tags",
    }
    for tool in tools:
        assert tool["description"]
        assert tool["inputSchema"]["type"] == "object"


def test_add_search_and_get_round_trip(server):
    added = payload(call(server, "add_note", title="Deploy", body="migrations", tags=["ops"]))
    note_id = added["note"]["id"]

    found = payload(call(server, "search_notes", query="migra"))
    assert found["count"] == 1
    assert found["notes"][0]["id"] == note_id

    assert payload(call(server, "get_note", id=note_id))["note"]["tags"] == ["ops"]


def test_update_and_delete_through_tools(server):
    note_id = payload(call(server, "add_note", title="draft"))["note"]["id"]

    updated = payload(call(server, "update_note", id=note_id, title="final", tags=["done"]))
    assert updated["note"]["title"] == "final"

    assert payload(call(server, "delete_note", id=note_id))["deleted"] == note_id
    assert payload(call(server, "list_notes"))["count"] == 0


def test_list_tags_counts(server):
    call(server, "add_note", title="a", tags=["ops"])
    call(server, "add_note", title="b", tags=["ops", "release"])

    assert payload(call(server, "list_tags"))["tags"][0] == {"tag": "ops", "count": 2}


def test_tool_failure_comes_back_as_is_error(server):
    result = call(server, "get_note", id=404)

    assert result["isError"] is True
    assert "404" in result["content"][0]["text"]


def test_bad_arguments_come_back_as_is_error(server):
    assert call(server, "add_note", title="")["isError"] is True
    assert call(server, "get_note", id="seven")["isError"] is True
    assert call(server, "add_note", title="x", tags=["two words"])["isError"] is True


def test_unknown_tool_is_a_protocol_error(server):
    # The spec separates the two: a name that does not exist is invalid params,
    # while a tool that ran and failed comes back as a result with isError.
    response = server.handle(
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "nope"}}
    )

    assert response["error"]["code"] == -32602


def test_unknown_method_is_a_protocol_error(server):
    response = server.handle({"jsonrpc": "2.0", "id": 9, "method": "tools/nope"})

    assert response["error"]["code"] == -32601
    assert response["id"] == 9


def test_notifications_get_no_answer(server):
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_serve_reads_lines_and_survives_bad_json(tmp_path):
    store = Store(tmp_path / "notes.db")
    lines = [
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
        "{ not json",
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "add_note", "arguments": {"title": "from stdio"}},
            }
        ),
    ]
    out = io.StringIO()
    serve(store, io.StringIO("\n".join(lines) + "\n"), out)
    store.close()

    answers = [json.loads(line) for line in out.getvalue().splitlines()]
    assert [a.get("id") for a in answers] == [1, None, 2]
    assert answers[1]["error"]["code"] == -32700  # the bad line, session kept going
    assert "from stdio" in answers[2]["result"]["content"][0]["text"]
