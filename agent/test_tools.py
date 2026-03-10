#!/usr/bin/env python3
"""Quick test of tools.py — run with VODLIX credentials set."""

import json
import os
import sys

# Add parent to path
sys.path.insert(0, os.path.dirname(__file__))

os.environ.setdefault("VODLIX_API_BASE", "https://stirr.com/api")
# Set VODLIX_USERNAME, VODLIX_PASSWORD in env

from tools import get_breaking_news, get_chapters, search_content


class Ctx:
    state = {}


def main():
    ctx = Ctx()
    queries = [
        ("Breaking news from Dallas", get_breaking_news, "Dallas"),
        ("Something to watch tonight", search_content, "tonight"),
        ("Show me chapters", get_chapters, "Documentary"),
    ]
    for name, fn, arg in queries:
        print(f"\n--- {name} ---")
        try:
            if fn == get_chapters:
                raw = fn(arg, ctx)
            elif fn == get_breaking_news:
                raw = fn(arg, ctx, 5)
            else:
                raw = fn(arg, ctx, 10)
            data = json.loads(raw)
            if "items" in data:
                print(f"  Items: {len(data['items'])}")
                for i, item in enumerate(data["items"][:3]):
                    print(f"    {i+1}. {item.get('title', '?')}")
            elif "chapters" in data:
                print(f"  Chapters: {len(data['chapters'])}")
                for ch in data["chapters"]:
                    print(f"    - {ch['title']} @ {ch['timestamp']}s")
            else:
                print(f"  {json.dumps(data, indent=2)[:300]}...")
        except Exception as e:
            print(f"  ERROR: {e}")


if __name__ == "__main__":
    main()
