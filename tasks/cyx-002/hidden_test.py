from cyberintel.sources.awesome_hacking import parse_readme

MD = """## Tools

| Name | Description |
|---|---|
| [Wiki](https://en.wikipedia.org/wiki/Metasploit_(software)) | Wikipedia page |
| [Nmap](https://github.com/nmap/nmap) | Network scanner |
"""


def test_url_with_parentheses_is_kept():
    entries = parse_readme(MD)
    urls = {e.name: e.url for e in entries}
    assert urls["Wiki"] == "https://en.wikipedia.org/wiki/Metasploit_(software)"
    assert urls["Nmap"] == "https://github.com/nmap/nmap"
    wiki = [e for e in entries if e.name == "Wiki"][0]
    assert wiki.description == "Wikipedia page"
