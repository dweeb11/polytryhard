from core.api.middleware import new_request_id


def test_new_request_id_is_unique_and_prefixed() -> None:
    first = new_request_id()
    second = new_request_id()

    assert first.startswith("req_")
    assert second.startswith("req_")
    assert first != second
