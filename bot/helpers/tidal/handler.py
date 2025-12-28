import os
import json
import base64

from pathvalidate import sanitize_filepath

from .tidal_api import tidalapi
from .utils import *
from .metadata import *

from ..utils import *
from ..metadata import set_metadata, get_audio_extension
from ..uploder import *
from ..message import send_message

from ...settings import bot_set
import bot.helpers.translations as lang

from bot.logger import LOGGER
from config import Config


async def start_tidal(url:str, user:dict):
    item_id, type_ = await parse_url(url)

    if type_ == 'track':
        await start_track(item_id, user, None)
    elif type_ == 'artist':
        await start_artist(item_id, user)
    elif type_ == 'album':
        await start_album(item_id, user)
    elif type_ == 'playlist':
        await start_playlist(item_id, user)
    else:
        await send_message(user, "Invalid Tidal URL")
        

async def start_track(track_id:int, user:dict, track_meta:dict | None, \
    upload=True, basefolder=None, session=None, quality=None, disable_link=False, disable_msg=False):
    if not track_meta:
        try:
            track_data = await tidalapi.get_track(track_id)
        except Exception as e:
            return await send_message(user, e)

        track_meta = await get_track_metadata(track_id, track_data, user['r_id'])
        filepath = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{track_meta['provider']}/{track_meta['albumartist']}/{track_meta['album']}"
        # Ensure destination folder exists
        filepath = sanitize_filepath(filepath)
        os.makedirs(filepath, exist_ok=True)
        # mostly session and quality will not be present
        session, quality = await get_stream_session(track_data)
    else:
        # When called from playlist/album, basefolder is provided
        filepath = basefolder
        # Ensure destination folder exists
        filepath = sanitize_filepath(filepath)
        os.makedirs(filepath, exist_ok=True)
        # If session/quality not provided, determine per-track now
        if session is None or quality is None:
            try:
                track_data = await tidalapi.get_track(track_id)
                session, quality = await get_stream_session(track_data)
            except Exception as e:
                return await send_message(user, e)

    try:
        stream_data = await tidalapi.get_stream_url(track_id, quality, session)
    except Exception as e:
        error = e
        # definitely region locked
        if 'Asset is not ready for playback' in str(e):
            error = f'Track [{track_id}] is not available in your region'
        LOGGER.error(error)
        return await send_message(user, error)
    

    if stream_data is not None:

        track_meta['quality'] = await get_quality(stream_data)

        if stream_data['manifestMimeType'] == 'application/dash+xml':
            manifest = base64.b64decode(stream_data['manifest'])
            urls, track_codec = parse_mpd(manifest)
        else:
            manifest = json.loads(base64.b64decode(stream_data['manifest']))
            track_codec = 'AAC' if 'mp4a' in manifest['codecs'] else manifest['codecs'].upper()
            urls = manifest['urls'][0]

        
        track_meta['folderpath'] = filepath
        filename = await format_string(Config.TRACK_NAME_FORMAT, track_meta, user)
        # not adding file extention now
        filepath += f"/{filename}"
        filepath = sanitize_filepath(filepath)
        # Ensure parent folder exists (safety)
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        track_meta['filepath'] = filepath


        if type(urls) == list:
            i = 0   # flawless
            temp_files = []
            for url in urls[0]:
                temp_path = f"{filepath}.{i}"
                err = await download_file(url, temp_path)
                if err:
                    return await send_message(user, err)
                i+=1
                temp_files.append(temp_path)
            await merge_tracks(temp_files, filepath)
        else:
            err = await download_file(urls, filepath)
            if err:
                return await send_message(user, err)

        track_meta['extension'] = await get_audio_extension(filepath)
        
        if quality == 'HI_RES_LOSSLESS' and Config.TIDAL_CONVERT_M4A:
            await ffmpeg_convert(filepath)
            track_meta['filepath'] = track_meta['filepath'] + '.flac'
            os.remove(filepath)
        else:
            track_meta['filepath'] = track_meta['filepath'] + f".{track_meta['extension']}"
            # local filepath var is not updated so it contains old path before extention update
            os.rename(filepath, track_meta['filepath'])

        await set_metadata(track_meta)

        if upload:
            await track_upload(track_meta, user, False)

    return True

        

async def start_album(album_id:int, user:dict, upload=True, basefolder=None):
    try:
        album_data = await tidalapi.get_album(album_id)
    except Exception as e:
        return await send_message(user, e)
        
    tracks_data = await tidalapi.get_album_tracks(album_id)
    
    album_meta = await get_album_metadata(album_id, album_data, tracks_data, user['r_id'])

    if basefolder:
        album_folder = basefolder + f"/{album_meta['title']}"
    else:
        album_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{album_meta['provider']}/{album_meta['artist']}/{album_meta['title']}"
    
    album_folder = sanitize_filepath(album_folder)
    os.makedirs(album_folder, exist_ok=True)
    album_meta['folderpath'] = album_folder

    # get a track to get quality
    track_id = tracks_data['items'][0]['id']
    track_data = await tidalapi.get_track(track_id)
    session, quality = await get_stream_session(track_data)
    stream_data = await tidalapi.get_stream_url(track_id, quality, session)

    album_meta['quality'] = await get_quality(stream_data)

    if upload:
        album_meta['poster_msg'] = await post_art_poster(user, album_meta)

    # concurrent
    tasks = []
    for track in album_meta['tracks']:
        tasks.append(start_track(track['itemid'], user, track, False, album_folder, session, quality))

    update_details = {
        'text': lang.s.DOWNLOAD_PROGRESS,
        'msg': user['bot_msg'],
        'title': album_meta['title'],
        'type': album_meta['type']
    }
    await run_concurrent_tasks(tasks, update_details)

    if bot_set.album_zip:
        await edit_message(user['bot_msg'], lang.s.ZIPPING)
        album_meta['folderpath'] = await zip_handler(album_meta['folderpath'])

    # Upload
    if upload:
        await edit_message(user['bot_msg'], lang.s.UPLOADING)
        await album_upload(album_meta, user)



async def start_playlist(playlist_id:int, user:dict, upload=True):
    """
    Tidal playlist downloader:
    - Creates a playlist folder
    - Uses first track to determine session/quality
    - Downloads each track into the playlist folder
    """
    try:
        raw_data = await tidalapi.get_playlist(playlist_id)
        tracks_data = await tidalapi.get_playlist_tracks(playlist_id)
    except Exception as e:
        return await send_message(user, e)

    items = tracks_data.get('items', []) or []
    if not items:
        return await send_message(user, "TIDAL : Empty playlist or no tracks found")

    # Build playlist metadata (includes cover/thumbnail)
    play_meta = await get_playlist_metadata(playlist_id, raw_data, tracks_data, user['r_id'])

    # Playlist folder
    playlist_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{play_meta['provider']}/{play_meta['title']}"
    playlist_folder = sanitize_filepath(playlist_folder)
    os.makedirs(playlist_folder, exist_ok=True)
    play_meta['folderpath'] = playlist_folder

    # Determine session/quality using first track
    session = quality = None
    try:
        first_track_id = play_meta['tracks'][0]['itemid']
        first_track_data = await tidalapi.get_track(first_track_id)
        session, quality = await get_stream_session(first_track_data)
        stream_data = await tidalapi.get_stream_url(first_track_id, quality, session)
        play_meta['quality'] = await get_quality(stream_data)
    except Exception as e:
        LOGGER.warning(f"TIDAL: Could not prefetch session/quality for playlist: {e}")

    # Poster
    try:
        play_meta['poster_msg'] = await post_art_poster(user, play_meta)
    except Exception:
        pass

    # Download tracks concurrently (each track uploads by itself)
    update_details = {
        'text': lang.s.DOWNLOAD_PROGRESS,
        'msg': user['bot_msg'],
        'title': play_meta['title'],
        'type': play_meta['type']
    }

    tasks = []
    for tr in play_meta['tracks']:
        tasks.append(start_track(tr['itemid'], user, tr, True, playlist_folder, session, quality))

    await run_concurrent_tasks(tasks, update_details)

    return True



async def start_artist(artist_id:int, user:dict):
    pass
