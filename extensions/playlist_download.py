"""
playlist_download (Tidal version)
--------------------------------
Helper module for handling playlist download tasks.
Ensures required directories exist before starting downloads.

Functions:
- extract_playlist_items(source): split input string into IDs or URLs
- ensure_download_dirs(base, task_id): make sure directories exist
- prepare_playlist_task(source, task_id): return ready-to-use task dict
"""

import os
import re
from typing import List, Dict, Any


def extract_playlist_items(source: str) -> List[str]:
    """
    Parse playlist input string.

    Supports:
      - newline-separated IDs/URLs
      - comma-separated IDs/URLs
      - full Tidal playlist/album/track URLs (returns the ID part)
    """
    if not source:
        return []
    src = source.strip()

    # Detect Tidal playlist/album/track URL
    m = re.search(r"tidal\.com/(?:browse/)?(playlist|album|track)/([A-Za-z0-9]+)", src)
    if m:
        return [m.group(2)]

    # fallback: split by newline or comma
    tokens = [t.strip() for t in re.split(r"[\n,]+", src) if t.strip()]
    return tokens


def ensure_download_dirs(base: str, task_id: str):
    """
    Make sure both the main download dir and temp dir exist.
    Returns (main_path, temp_path).
    """
    main_path = os.path.join(base, task_id)
    temp_path = os.path.join(base, f"{task_id}-temp")
    os.makedirs(main_path, exist_ok=True)
    os.makedirs(temp_path, exist_ok=True)
    return main_path, temp_path


def prepare_playlist_task(playlist_source: str, task_id: str = "default") -> Dict[str, Any]:
    """
    Build a playlist download task dict that includes ensured directories.
    """
    items = extract_playlist_items(playlist_source)
    base_dir = "./bot/DOWNLOADS"
    main_path, temp_path = ensure_download_dirs(base_dir, task_id)
    return {
        "type": "playlist_download",
        "source": playlist_source,
        "items": items,
        "count": len(items),
        "download_dir": main_path,
        "temp_dir": temp_path,
    }


# Example usage
if __name__ == "__main__":
    # Example with Tidal playlist URL
    task = prepare_playlist_task("https://tidal.com/playlist/353", task_id="353")
    print("Prepared task:", task)
