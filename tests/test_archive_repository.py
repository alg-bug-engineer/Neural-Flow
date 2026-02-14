from datetime import datetime
from urllib.parse import urlparse

from libs.neural_flow.archive import ArchiveRepository


def test_write_markdown_uses_topic_and_draft_pool_structure(tmp_path) -> None:
    repo = ArchiveRepository(
        db_path=str(tmp_path / "archive.db"),
        archive_dir=str(tmp_path / "archive"),
    )
    day_label = datetime.now().strftime("%Y-%m-%d")

    topic_uri = repo.write_markdown(
        {
            "record_type": "topic",
            "trace_id": "topic1234",
            "title": "GLM-5 发布",
            "ai_summary": "这是选题摘要",
            "source_url": "https://example.com/topic",
            "channels": ["twitter", "zhihu"],
        }
    )
    topic_path = urlparse(topic_uri).path
    assert f"/{day_label}/topic_pool/" in topic_path
    assert topic_path.endswith(".md")

    draft_uri = repo.write_markdown(
        {
            "record_type": "draft",
            "trace_id": "topic1234-zhihu",
            "platform": "zhihu",
            "title": "GLM-5 发布",
            "ai_summary": "这是草稿摘要",
            "article_markdown": "# 正文",
            "source_url": "https://example.com/topic",
            "image_urls": ["https://img.example/a.jpg", "https://img.example/b.jpg"],
        }
    )
    draft_path = urlparse(draft_uri).path
    assert f"/{day_label}/draft_pool/" in draft_path
    assert "-zhihu-" in draft_path
    assert draft_path.endswith(".md")


def test_build_generation_context_reads_recent_drafts(tmp_path) -> None:
    repo = ArchiveRepository(
        db_path=str(tmp_path / "archive.db"),
        archive_dir=str(tmp_path / "archive"),
    )
    repo.write_markdown(
        {
            "record_type": "draft",
            "trace_id": "trace-a-twitter",
            "platform": "twitter",
            "title": "GLM-5 发布分析",
            "ai_summary": "模型发布信息",
            "twitter_draft": "GLM-5 已发布，性能对标。",
            "article_markdown": "避免重复表达测试",
            "source_url": "https://example.com/a",
        }
    )

    context = repo.build_generation_context(title="GLM-5 发布", platform="twitter", limit=3)
    assert "GLM-5" in context
