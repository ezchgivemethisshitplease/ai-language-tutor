#!/usr/bin/env python3
"""Parse every inline/shared browser script with Node; no browser dependencies."""

from html.parser import HTMLParser
from pathlib import Path
import subprocess


class Scripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.current = None
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        if tag == "script" and not dict(attrs).get("src"):
            self.current = ""

    def handle_data(self, data):
        if self.current is not None:
            self.current += data

    def handle_endtag(self, tag):
        if tag == "script" and self.current is not None:
            self.scripts.append(self.current)
            self.current = None


def main():
    apps = Path(__file__).resolve().parents[1] / "apps"
    for path in apps.glob("*.html"):
        parser = Scripts()
        parser.feed(path.read_text(encoding="utf-8"))
        for script in parser.scripts:
            subprocess.run(
                ["node", "--check"], input=script, text=True, encoding="utf-8", check=True
            )
    for path in apps.glob("*.js"):
        subprocess.run(["node", "--check", str(path)], check=True)
    print("All browser scripts parse")


if __name__ == "__main__":
    main()
