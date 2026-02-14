from libs.neural_flow.memory import MemoryRepository
from libs.neural_flow.models import RememberRequest


def test_memory_repository_duplicate_and_context(tmp_path) -> None:
    db_path = tmp_path / "memory.db"
    repo = MemoryRepository(str(db_path))

    req = RememberRequest(
        source_id="source-a",
        url_hash="hash-1",
        title="GLM-5 发布",
        url="https://example.com/1",
        summary="新模型上线",
        keywords=["glm", "模型"],
        raw_text="详情",
        archive_url="file:///tmp/doc.md",
        image_url="https://picsum.photos/1",
    )

    assert repo.is_duplicate("hash-1") is False
    repo.remember(req)
    assert repo.is_duplicate("hash-1") is True

    context, count = repo.retrieve_context(["glm"], limit=3)
    assert count == 1
    assert "GLM-5" in context
