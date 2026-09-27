from web2md.dom import parse
from web2md.metadata import extract_metadata


def meta(html: str, base_url: str | None = None):
    return extract_metadata(parse(html), base_url=base_url)


def test_opengraph_and_article_tags_win():
    m = meta(
        "<html lang='de'><head><title>Ignored | Site</title>"
        "<meta property='og:title' content='Real headline'>"
        "<meta property='og:site_name' content='Site'>"
        "<meta property='article:published_time' content='2024-01-02T03:04:05Z'>"
        "<meta name='author' content='A. Writer'>"
        "<meta property='og:description' content='Desc'></head></html>"
    )
    assert (m.title, m.author, m.date, m.site_name, m.description, m.language) == (
        "Real headline",
        "A. Writer",
        "2024-01-02T03:04:05Z",
        "Site",
        "Desc",
        "de",
    )


def test_json_ld_graph_with_author_list():
    html = """<script type="application/ld+json">
    {"@context": "https://schema.org", "@graph": [
      {"@type": "WebSite", "name": "Site"},
      {"@type": "NewsArticle", "headline": "From JSON-LD", "datePublished": "2023-05-06",
       "author": [{"@type": "Person", "name": "Ann"}, {"@type": "Person", "name": "Bo"}]}]}
    </script>"""
    m = meta(html)
    assert (m.title, m.author, m.date) == ("From JSON-LD", "Ann, Bo", "2023-05-06")


def test_broken_json_ld_is_ignored():
    m = meta("<script type='application/ld+json'>{not json</script><title>Fine</title>")
    assert m.title == "Fine"


def test_author_url_in_meta_is_not_an_author():
    m = meta(
        "<meta property='article:author' content='https://facebook.com/x'>"
        "<span class='byline'>By Sam Lee</span>"
    )
    assert m.author == "Sam Lee"


def test_time_element_and_itemprop_dates():
    assert meta("<p><time datetime='2022-02-02'>2 Feb</time></p>").date == "2022-02-02"
    assert meta("<span itemprop='datePublished' content='2021-01-01'>x</span>").date == "2021-01-01"


def test_canonical_resolves_against_base_url_and_falls_back_to_og_url():
    html = "<link rel='canonical' href='/a/b'>"
    assert meta(html, base_url="https://ex.org/x/y").canonical_url == "https://ex.org/a/b"
    assert meta(html).canonical_url == "/a/b"
    assert meta("<meta property='og:url' content='https://ex.org/og'>").canonical_url == (
        "https://ex.org/og"
    )


def test_title_suffix_stripping():
    assert meta("<title>A Long Enough Headline Here - The Daily</title>").title == (
        "A Long Enough Headline Here"
    )
    assert meta("<title>Short - Site</title>").title == "Short - Site"
    assert meta(
        "<title>News | Site</title><meta property='og:site_name' content='Site'>"
    ).title == ("News")
    assert meta("<title>Retries — docs</title><h1>Retries</h1>").title == "Retries"


def test_empty_document_has_empty_metadata():
    assert all(v == "" for v in meta("").as_dict().values())
