import copy
import os

from datetime import datetime

from ..metadata import metadata as base_meta
from ..metadata import create_cover_file


def get_artists_name(meta: dict) -> str:
    """
    Return a human-readable artists string from TIDAL metadata.
    Prefers 'artists' list; falls back to single 'artist'.
    """
    try:
        artists = meta.get("artists")
        if isinstance(artists, list) and artists:
            names = [a.get("name") for a in artists if isinstance(a, dict) and a.get("name")]
            return ", ".join([n for n in names if n])
        artist = meta.get("artist")
        if isinstance(artist, dict):
            return artist.get("name") or ""
    except Exception:
        pass
    return ""


async def get_cover(cover_id: str | None, metadata: dict, thumbnail: bool = False):
    """
    Build a TIDAL cover URL and delegate to create_cover_file to fetch it.
    - TIDAL image URL pattern: https://resources.tidal.com/images/{cover_path}/{size}x{size}.jpg
    - cover_id sometimes needs '-' replaced with '/' to form the path component.
    Returns a local file path (or None on failure).
    """
    if not cover_id:
        return None

    try:
        # TIDAL uses a nested path form for images.
        cover_path = cover_id.replace("-", "/")
        size = 320 if thumbnail else 1280
        url = f"https://resources.tidal.com/images/{cover_path}/{size}x{size}.jpg"
        # Ensure temp folder exists for artwork writes
        tempfolder = metadata.get("tempfolder")
        if tempfolder:
            os.makedirs(tempfolder, exist_ok=True)
        return await create_cover_file(url, metadata, thumbnail)
    except Exception:
        return None


async def get_track_metadata(track_id, t_meta, r_id, cover=None, thumbnail=False):
    """
    Args:
        item_id : track id
        t_meta : raw metadata from tidal (pre-fetched)
    Returns:
        metadata: dict
    """

    metadata = copy.deepcopy(base_meta)

    metadata['tempfolder'] += f"{r_id}-temp/"
    os.makedirs(metadata['tempfolder'], exist_ok=True)

    metadata['itemid'] = track_id
    metadata['copyright'] = t_meta['copyright']
    metadata['albumartist'] = t_meta['artist']['name']
    metadata['artist'] = get_artists_name(t_meta)
    metadata['album'] = t_meta['album']['title']
    metadata['isrc'] = t_meta['isrc']

    metadata['title'] = t_meta['title']
    if t_meta.get('version'):
        metadata['title'] += f' ({t_meta["version"]})'

    # title might have '/' in it
    metadata['title'] = metadata['title'].replace('/', ' ')

    metadata['duration'] = t_meta['duration']
    metadata['explicit'] = t_meta['explicit']
    metadata['tracknumber'] = t_meta['trackNumber']

    parsed_date = datetime.strptime(t_meta['streamStartDate'], '%Y-%m-%dT%H:%M:%S.%f%z')
    metadata['date'] = str(parsed_date.date())

    metadata['provider'] = 'Tidal'
    metadata['type'] = 'track'

    # reuse albumart if possible
    metadata['cover'] = cover if cover else await get_cover(t_meta['album'].get('cover'), metadata)
    metadata['thumbnail'] = thumbnail if thumbnail else await get_cover(t_meta['album'].get('cover'), metadata, True)

    return metadata


async def get_album_metadata(album_id, a_meta, t_meta, r_id):
    metadata = copy.deepcopy(base_meta)

    metadata['tempfolder'] += f"{r_id}-temp/"
    os.makedirs(metadata['tempfolder'], exist_ok=True)

    metadata['itemid'] = album_id
    metadata['albumartist'] = a_meta['artist']['name']
    metadata['upc'] = a_meta['upc']
    metadata['title'] = a_meta['title']
    if a_meta.get('version'):
        metadata['title'] += f' ({a_meta["version"]})'
    metadata['album'] = a_meta['title']
    metadata['artist'] = get_artists_name(a_meta)
    metadata['date'] = a_meta['releaseDate']
    metadata['totaltracks'] = a_meta['numberOfTracks']
    metadata['duration'] = a_meta['duration']
    metadata['copyright'] = a_meta['copyright']
    metadata['explicit'] = a_meta['explicit']
    metadata['totalvolume'] = a_meta['numberOfVolumes']
    metadata['provider'] = 'Tidal'
    metadata['type'] = 'album'

    metadata['cover'] = await get_cover(a_meta.get('cover'), metadata)
    metadata['thumbnail'] = await get_cover(a_meta.get('cover'), metadata, True)


    metadata['tracks'] = []
    for track in t_meta['items']:
        track_meta = await get_track_metadata(track['id'], track, r_id, metadata['cover'], metadata['thumbnail'])
        metadata['tracks'].append(track_meta)
    
    return metadata


async def get_playlist_metadata(playlist_id, p_meta, t_meta, r_id):
    """
    Build playlist-level metadata and per-track metadata for a Tidal playlist
    """
    metadata = copy.deepcopy(base_meta)

    metadata['tempfolder'] += f"{r_id}-temp/"
    os.makedirs(metadata['tempfolder'], exist_ok=True)

    metadata['itemid'] = playlist_id
    metadata['title'] = p_meta.get('title', f'Playlist-{playlist_id}')
    metadata['provider'] = 'Tidal'
    metadata['type'] = 'playlist'
    metadata['totaltracks'] = t_meta.get('totalNumberOfItems', len(t_meta.get('items', [])))

    # Playlist cover (Tidal often uses 'squareImage' for playlists)
    cover_id = p_meta.get('squareImage') or p_meta.get('image') or None
    metadata['cover'] = await get_cover(cover_id, metadata) if cover_id else None
    metadata['thumbnail'] = await get_cover(cover_id, metadata, True) if cover_id else None

    # Tracks
    metadata['tracks'] = []
    for item in t_meta.get('items', []):
        tr = item.get('track') or item.get('item') or item
        if not tr or not tr.get('id'):
            continue
        # Reuse playlist cover for speed; fall back to track album cover inside get_track_metadata if None
        track_meta = await get_track_metadata(tr['id'], tr, r_id, metadata['cover'], metadata['thumbnail'])
        metadata['tracks'].append(track_meta)

    return metadata


async def get_artist_metadata(a_meta:dict, r_id):
    metadata = copy.deepcopy(base_meta)

    metadata['tempfolder'] += f"{r_id}-temp/"
    os.makedirs(metadata['tempfolder'], exist_ok=True)

    return metadata
