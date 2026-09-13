import pytest

from mcp_notes.store import BadInput, NoteNotFound, Store, normalize_tags


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "notes.db")
    yield s
    s.close()


def test_add_and_get(store):
    note = store.add("Deploy checklist", "run migrations first", ["#Ops", "release"])
    assert note.id > 0
    assert note.tags == ["ops", "release"]
    assert store.get(note.id).body == "run migrations first"


def test_title_is_required(store):
    with pytest.raises(BadInput):
        store.add("   ")


def test_bad_tag_is_rejected(store):
    with pytest.raises(BadInput):
        store.add("note", tags=["two words"])


def test_tags_normalize_and_dedupe():
    assert normalize_tags(["#Ops", "ops", "OPS"]) == ["ops"]
    assert normalize_tags("ops, release") == ["ops", "release"]


def test_search_finds_by_prefix(store):
    store.add("Deploy checklist", "run migrations first", ["ops"])
    store.add("Grocery list", "milk and bread")

    found = store.search("migra")
    assert [n.title for n in found] == ["Deploy checklist"]
    assert found[0].snippet is not None


def test_search_requires_all_words(store):
    store.add("Deploy checklist", "run migrations first")
    assert store.search("deploy checklist") != []
    assert store.search("deploy groceries") == []


def test_search_can_filter_by_tag(store):
    store.add("Deploy staging", "", ["ops"])
    store.add("Deploy notes app", "", ["personal"])

    assert [n.title for n in store.search("deploy", tag="ops")] == ["Deploy staging"]


def test_search_handles_operators_as_plain_words(store):
    store.add("Release OR rollback", "NEAR the end")
    assert store.search("rollback") != []
    assert store.search("rollback OR nothing") == []  # 'OR' is a word, not an operator


def test_search_is_unicode_aware(store):
    store.add("Заметка", "текст про деплой", ["заметки"])
    assert [n.title for n in store.search("деплой")] == ["Заметка"]
    assert [n.title for n in store.list(tag="заметки")] == ["Заметка"]


def test_empty_query_is_rejected(store):
    with pytest.raises(BadInput):
        store.search("   ...   ")


def test_list_is_newest_first(store):
    first = store.add("one")
    store.add("two")
    store.update(first.id, body="touched")

    assert [n.title for n in store.list()] == ["one", "two"]


def test_list_paginates(store):
    for i in range(5):
        store.add(f"note {i}")
    assert len(store.list(limit=2)) == 2
    assert len(store.list(limit=2, offset=4)) == 1


def test_update_keeps_omitted_fields(store):
    note = store.add("title", "body", ["a"])
    updated = store.update(note.id, title="new title")

    assert updated.title == "new title"
    assert updated.body == "body"
    assert updated.tags == ["a"]
    assert updated.updated >= note.updated


def test_update_replaces_tags_and_reindexes(store):
    note = store.add("findme", "old body", ["a"])
    store.update(note.id, body="new body", tags=["b"])

    assert store.get(note.id).tags == ["b"]
    assert store.search("new") != []
    assert store.search("old") == []


def test_update_cannot_empty_the_title(store):
    note = store.add("title")
    with pytest.raises(BadInput):
        store.update(note.id, title="  ")


def test_delete_removes_note_tags_and_index(store):
    note = store.add("throwaway", "body", ["temp"])
    store.delete(note.id)

    with pytest.raises(NoteNotFound):
        store.get(note.id)
    assert store.search("throwaway") == []
    assert store.tags() == []


def test_missing_note_raises(store):
    with pytest.raises(NoteNotFound):
        store.get(404)


def test_tags_are_counted(store):
    store.add("a", tags=["ops", "release"])
    store.add("b", tags=["ops"])

    assert store.tags() == [{"tag": "ops", "count": 2}, {"tag": "release", "count": 1}]


def test_notes_survive_reopen(tmp_path):
    path = tmp_path / "notes.db"
    first = Store(path)
    first.add("persisted", "body", ["keep"])
    first.close()

    second = Store(path)
    assert [n.title for n in second.search("persisted")] == ["persisted"]
    second.close()
