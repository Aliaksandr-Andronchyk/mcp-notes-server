from mcp_notes.__main__ import main


def test_main_uses_given_db_and_serves_stdin(tmp_path, monkeypatch, capsys):
    import io

    db_path = tmp_path / "notes.db"
    request = '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}\n'
    monkeypatch.setattr("sys.stdin", io.StringIO(request))
    stdout = io.StringIO()
    monkeypatch.setattr("sys.stdout", stdout)

    code = main(["--db", str(db_path)])

    assert code == 0
    assert db_path.exists()
    assert '"tools"' in stdout.getvalue()

    err = capsys.readouterr().err
    assert str(db_path) in err


def test_main_defaults_db_path(tmp_path, monkeypatch):
    import io

    default_db = tmp_path / "default.db"
    monkeypatch.setattr("mcp_notes.__main__.DEFAULT_DB", default_db)
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    monkeypatch.setattr("sys.stdout", io.StringIO())

    code = main([])

    assert code == 0
    assert default_db.exists()
