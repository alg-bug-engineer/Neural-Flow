from libs.neural_flow.rss import parse_rss_items


def test_parse_wechat_rss_items() -> None:
    xml = """
    <rss version="2.0">
      <channel>
        <item>
          <title>GLM-5 发布</title>
          <link>https://example.com/post/1</link>
          <description><![CDATA[这是内容摘要。]]></description>
          <pubDate>Sat, 14 Feb 2026 08:00:00 GMT</pubDate>
        </item>
      </channel>
    </rss>
    """
    items = parse_rss_items(xml, source_id="wechat", max_items=5)

    assert len(items) > 0
    assert items[0].source_id == "wechat"
    assert items[0].url_hash
    assert items[0].title


def test_filter_url_only_tweets() -> None:
    xml = """
    <rss version="2.0">
      <channel>
        <item>
          <title>https://x.com/i/article/123</title>
          <link>https://x.com/u/status/1</link>
          <description>https://x.com/i/article/123</description>
          <pubDate>Sat, 14 Feb 2026 09:00:00 GMT</pubDate>
        </item>
        <item>
          <title>真正的技术内容</title>
          <link>https://x.com/u/status/2</link>
          <description><![CDATA[模型发布与评测结果]]></description>
          <pubDate>Sat, 14 Feb 2026 09:10:00 GMT</pubDate>
        </item>
      </channel>
    </rss>
    """
    items = parse_rss_items(xml, source_id="twitter", max_items=10)

    assert len(items) > 0
    assert all(not item.title.startswith("http") for item in items)
