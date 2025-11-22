#!/usr/bin/env python3

# TODO:
# - Add playlists (like https://fm4.orf.at/radio/stories/3007157/ or https://fm4.orf.at/radio/stories/3007304/), maybe content or URL as comment? But: How to find the right link?

import sys
import urllib.parse
import os
import re
import time
from datetime import datetime
import argparse
import io
import signal

from mutagen.id3 import ID3,ID3NoHeaderError,TRSN,TRSO,TPE1,TALB,TRCK,TIT2,COMM,TYER,TDAT,TIME,TLEN,CTOC,CHAP,WOAS,WORS,APIC,CTOCFlags,PictureType
import requests

try:
    import av
    PYAV_AVAILABLE = True
except ImportError:
    PYAV_AVAILABLE = False


# Preferences
STATION_INFO = {
    'name': 'FM4',
    'website': 'https://fm4.orf.at',
    'player_search_url': "https://audioapi.orf.at/fm4/api/json/current/search?q=%s",
    'shoutcast_base_url': "https://loopstreamfm4.apa.at/?channel=fm4&id=%s",
}


def interrupt_handler(signum, frame):
    """
    Exit cleanly on CTRL-C
    """
    sys.exit()


def get_all_broadcasts(show_title):
    """
    Search for broadcasts of a show
    Return list with JSON data of each broadcast
    """

    response = requests.get(STATION_INFO['player_search_url'] % urllib.parse.quote_plus(show_title), timeout=5)
    results_json = response.json()

    # For each search result, sorted from newest to oldest: fetch linked broadcasts
    all_broadcast_jsons = []
    for hit in sorted(results_json['hits'], key=lambda x: x['data']['start'], reverse=True):

        # Only care about broadcasts of type "Broadcast" and skip everything else
        if hit['data']['entity'] != "Broadcast":
            continue

        # Download json of broadcast
        broadcast_json = requests.get(hit['data']['href'], timeout=5).json()

        # Remove station's name from show's title, so that user may search for 'fm4 house of pain' or 'house of pain'
        clean_show_title = re.sub(r'^' + STATION_INFO['name'] + r'[\-\s]*', '', show_title, flags=re.IGNORECASE)

        # Skip broadcast if title does not contain the wanted show's name, with or without the station's name in front
        if re.search(r'^\s*(?:' + STATION_INFO['name'] + r')?[\s\-]*' + clean_show_title + r'\s*$', broadcast_json['title'], flags=re.IGNORECASE):
            all_broadcast_jsons.append(broadcast_json)

    return all_broadcast_jsons


def create_filename(broadcast_json):
    """
    Construct a sensible filename for the broadcast
    """

    show_name = strip_html(broadcast_json['title'])
    station_name = STATION_INFO['name'] if not show_name.lower().startswith(STATION_INFO['name'].lower()) else None
    airdate_string = datetime.fromtimestamp(broadcast_json['start']/1000).strftime("%Y-%m-%d %H:%M")

    filename = ' '.join(filter(None, [station_name, show_name, airdate_string])) + '.mp3'

    return re.sub(r'[^\w\s\-\.\[\]]','_', filename)


def get_chapters(broadcast_json):
    """
    Retrieve list of chapters from broadcast_json
    """

    chapters = []

    # Chapters are "items" in broadcast_json.
    for item_num, item in enumerate(sorted(broadcast_json['items'], key=lambda x: (x['start'], 1/x['end']))):
        if item['entity'] != "BroadcastItem":
            continue

        chapter = {
            'id': f'chp{item_num+1}',
            'start': max(0, item['start'] - broadcast_json['start']),
            'end': min(item['end'], broadcast_json['end']) - broadcast_json['start'],
            'title': None,
            'hidden': False,
            'images': item.get('images'),
            # Each item/chapter has a "type": N=Nachrichten, J=Jingle, ...
            'type': item['type'],
        }

        # Set title
        # Try to stick with 'interpreter' and 'title'.
        # Use 'description' only as last resort as it mostly contains rubbish.
        title = ': '.join(filter(None, [ strip_html(item.get(i)) for i in ["interpreter", "title"] ])) \
                or strip_html(item.get('description'))
        if title:
            chapter['title'] = title

        # Override chapter titles for Werbung and Jingles and hide them in TOC (at least in some players)
        if item['type'] == "W":
            chapter['title'] = "* WERBUNG *"
            chapter['hidden'] = True
        elif item['type'] == "J":
            chapter['title'] = "* JINGLE *"
            chapter['hidden'] = True

        # Hide chapters having no title, like FM4 Player does
        # (unfortunately still visible in most MP3 players)
        if not chapter['title']:
            chapter['hidden'] = True

        chapters.append(chapter)

    return chapters


def get_keepmarks(broadcast_json):
    """
    Get markers from broadcatJson, return list of audio segments to keep ([ startTime, endTime])
    In case of no markers, return empty list and keep all audio
    """

    keepmarks = []
    start = None
    end = None

    for mark in sorted(broadcast_json['marks'], key=lambda x: x['timestamp']):
        if mark['type'] == 'in':
            start = max(mark['timestamp'], broadcast_json['start'])
        elif mark['type'] == 'out':
            end = min(mark['timestamp'], broadcast_json['end'])

        if start is not None and end is not None:
            keepmarks.append([start - broadcast_json['start'], end - broadcast_json['start']])
            start = None
            end = None

    return keepmarks


def remove_chapters_from_keepmark(keepmark, chapters):
    """
    Remove list of chapters from a keepmark
    Return list of new keepmarks
    """

    for chapter_num, chapter in enumerate(chapters):

        # Chapter starts after keepmark. chapters are sorted by time, so we are done
        if chapter['start'] > keepmark[1]:
            return [ keepmark ]

        # Chapter has already ended before this keepmark -> head on with next chapter
        if chapter['end'] <= keepmark[0]:
            continue

        # Chapter spans whole keepmark -> ditch keepmark
        if chapter['start'] >= keepmark[0] and chapter['end'] >=  keepmark[1]:
            #return []
            break

        # Chapter starts before this keepmark and ends in this keepmark
        if chapter['start'] < keepmark[0]:
            return remove_chapters_from_keepmark([chapter['end'], keepmark[1]], chapters[chapter_num:])

        # Chapter starts and ends in this keepmark -> split it up into two, head on with right one
        if chapter['end'] <= keepmark[1]:
            left = [ keepmark[0], chapter['start'] ]
            right = remove_chapters_from_keepmark([ min(chapter['end'], keepmark[1]), keepmark[1]], chapters[chapter_num:])
            return [ left ] + right

    # keepmark not affected by any chapter, return unmodified
    return [ keepmark ]


def remove_chaptertypes_from_keepmarks(keepmarks, chapters, chapter_types):
    """
    Remove list of chapters from keepmarks
    Return updated list of keepmarks
    """

    unwanted_chapters = [ chapter for chapter in chapters if chapter['type'] in chapter_types ]

    if not unwanted_chapters:
        return keepmarks

    new_keepmarks = []
    for keepmark in keepmarks:
        new_keepmarks.extend(remove_chapters_from_keepmark(keepmark, unwanted_chapters))

    return new_keepmarks


def align_chapters_to_keepmarks(chapters, keepmarks):
    """
    If audio segments get cut out, chapter start & end markers may be in the removed parts of audio,
    or even completely gone.
    Ensure every chapter contains audio, and starts/ends at the proper time
    """
    chapters = sorted(chapters, key=lambda x: x['start'])
    keepmarks = sorted(keepmarks, key=lambda x: x[0])

    broadcast_duration = sum(end-start for start, end in keepmarks)

    # List with total duration of all gaps until each keepmark
    gaps = []
    gap = 0
    previous_end = 0
    for keepmark in keepmarks:
        gap = gap + keepmark[0] - previous_end
        previous_end = keepmark[1]
        gaps.append(gap)

    # Loop through chapters, subtract duration of all gaps until timestamp
    aligned_chapters = []

    for chapter in chapters:
        start = None
        end = None
        skip_chapter_flag = False
        # Walk through keepmarks from start to end, and set chapter start times
        for keepmark_num, keepmark in enumerate(keepmarks):
            if chapter['end'] < keepmark[0]:
                # Chapter ends before start of keepmark
                # -> Skip chapter
                skip_chapter_flag = True
                break
            if chapter['start'] <= keepmark[1]:
                # Chapter ends after start of keepmark (see if-clause above) and ends before end of keepmark
                # -> Fix chapter's start time
                start = max(chapter['start'], keepmark[0]) - gaps[keepmark_num]
                break

        if skip_chapter_flag:
            continue

        # Walk through keepmarks from end to start, and set chapter end times
        for keepmark_num, keepmark in reversed(list(enumerate(keepmarks))):
            if chapter['start'] > keepmark[1]:
                # Chapter starts after end of keepmark
                # -> Skip chapter
                skip_chapter_flag = True
                break
            if chapter['end'] >= keepmark[0]:
                # Chapter starts before end of keepmark (see if-clause above) and ends after start of keepmark
                # -> Fix chapter's end time
                end = min(chapter['end'], keepmark[1]) - gaps[keepmark_num]
                break

        if skip_chapter_flag:
            continue

        if start is not None and end is not None and start < end:
            aligned_chapter=chapter.copy()
            aligned_chapter['start'] = start
            aligned_chapter['end'] = min(end, broadcast_duration)
            aligned_chapters.append(aligned_chapter)

    return aligned_chapters


def download_audio(url: str, max_attempts=4):
    """
    Download audio data in chunks
    Return as bytearray
    """

    chunk_size = 128*1024  # 128 kByte

    for attempt in range(1, max_attempts+1):
        try:
            data = bytearray()
            with requests.get(url, stream=True, timeout=5) as response:
                content_length = int(response.headers['Content-Length'])
                response.raise_for_status()
                for chunk in response.iter_content(chunk_size=chunk_size):
                    data += chunk
                    print(f"\rDownloading {url} ... {len(data)/(1024*1024):.1f}/{content_length/(1024*1024):.1f} MByte", end=" ", flush=True)
            print("done")
            return data

        except:
            time.sleep(3)  # Wait 3 seconds between download attempts
            attempt += 1
            continue

    print(f"ERROR: Failed to download {url}", file=sys.stderr)
    return False


def cut_audio(audio, keepmarks):
    """
    Remove everything outside "keepmarks" sections from mp3 data
    """

    with av.open(io.BytesIO(audio), format='mp3') as input_container:
        input_stream = input_container.streams.audio[0]

        output_buffer = io.BytesIO()
        with av.open(output_buffer, 'w', format='mp3') as output_container:
            # set bit_rate to help mp3 players to calculate duration
            output_stream = output_container.add_stream('mp3', bit_rate=input_stream.bit_rate, rate=input_stream.rate)

            keepmarks_iter = iter(sorted(keepmarks, key=lambda x: x[0]))
            start, end = next(keepmarks_iter)

            for packet in input_container.demux(input_stream):
                if packet.dts is None:
                    # Skip "flushing" packets created by demux
                    continue

                timestamp = int(packet.pts * input_stream.time_base * 1000)

                if timestamp < start:
                    continue
                elif timestamp >= end:
                    try:
                        start, end = next(keepmarks_iter)
                    except StopIteration:
                        break
                else:
                    output_container.mux(packet)

            return output_buffer.getvalue()


def strip_html(text: str):
    """
    Remove HTML tags
    """

    if text is None:
        return None

    # Add a | after <br/>
    text = re.sub(r'(<br/?>)', r'\1 | ', text, flags=re.IGNORECASE)

    # Add a | between </p></p>
    text = re.sub(r'\s*(</p>)\s*(<p>)\s*', r'\1 | \2 ', text, flags=re.IGNORECASE)

    tag = False
    quote = False
    out = ""
    for c in text:
        if c == '<' and not quote:
            tag = True
        elif c == '>' and not quote:
            tag = False
        elif (c in ('"', "'")) and tag:
            quote = not quote
        elif not tag:
            out = out + c

    # Remove multiple consecutive spaces
    out = re.sub(r'\s\s+', ' ', out)

    return out.strip()


def get_image(images_list):
    """
    Try to download biggest image using JSON's "images" entry
    Return dict {'data': binary image data, 'mime': image mime type }
    """

    if not images_list:
        return None

    # get biggest (usually 600px width) image
    for image_version in sorted(images_list[0]['versions'], key=lambda x: x['width']):
        try:
            response = requests.get(image_version['path'], timeout=5)
            if response.status_code == 200:
                return {
                    'data': response.content,
                    'mime': response.headers['content-type']
                }
        except:
            continue
    return None


def set_id3_tags(filepath, chapters, keepmarks, broadcast_json):
    """
    Set id3 tags on mp3 file
    """

    # Calculate audio duration
    broadcast_duration = sum(end-start for start, end in keepmarks)

    # Create datetime object from broadcast's start time
    broadcast_datetime = datetime.fromtimestamp(broadcast_json['start']/1000)

    # Create sensible broadcast description
    broadcast_description = "\n".join(filter(None, map(strip_html, [
        broadcast_json.get('subtitle'),
        broadcast_json.get('description'),
        broadcast_json.get('pressRelease')
    ])))
    if not broadcast_description:
        broadcast_description = broadcast_datetime.strftime("%Y-%m-%d %H:%M")

    # Remove (potentially) existing id3 tags
    try:
        tags = ID3(filepath)
        tags.delete()
    except ID3NoHeaderError:
        tags = ID3()

    # Add new id3 tags
    tags.add(TRSN(text=[STATION_INFO['name']]))                      # Internet radio station name
    tags.add(TRSO(text=['ORF']))                                    # Internet radio station owner
    tags.add(WOAS(url=broadcast_json['url']))                        # Official audio source webpage
    tags.add(WORS(url=STATION_INFO['website']))                      # Official Internet radio station homepage

    tags.add(TPE1(text=[strip_html(STATION_INFO['name'])]))          # Lead performer(s)/Soloist(s) -> "FM4"
    tags.add(TALB(text=[strip_html(broadcast_json['title'])]))       # Album/Movie/Show title
    tags.add(TRCK(text=["1/1"]))                                    # Track number/Position in set
    tags.add(TIT2(text=[strip_html(broadcast_json['title'])]))       # Title/songname/content description

    tags.add(COMM(lang="deu", desc="desc", text=[broadcast_description]))    # Comments

    tags.add(TYER(text=[broadcast_datetime.strftime("%Y")]))         # Year of broadcast
    tags.add(TDAT(text=[broadcast_datetime.strftime("%Y-%m-%d")]))   # Date of broadcast
    tags.add(TIME(text=[broadcast_datetime.strftime("%H%M")]))       # Time of broadcast

    tags.add(TLEN(text=[broadcast_duration]))                        # Duration in ms

    # Try to download and add cover Image
    image = get_image(broadcast_json.get('images'))
    if image:
        tags.add(APIC(
            type=PictureType.COVER_FRONT,
            mime=image['mime'],
            data=image['data']
        ))

    # Chapters
    # ID3 forbids multiple chapters having the same start time
    #  -> If multiple chapters start at the same time, start with the longest one and add 1ms to each following
    previous_start_time = -1
    for chapter in sorted(chapters, key=lambda x: (x['start'], 1/x['end'])):
        sub_frames = []
        
        chapter_title = chapter.get('title')
        if chapter_title:
            sub_frames.append(TIT2(text=[chapter_title]))

        chapter_image = get_image(chapter.get('images'))
        if chapter_image:
            sub_frames.append(APIC(
                type=PictureType.OTHER,
                mime=chapter_image['mime'],
                data=chapter_image['data']
            ))

        chapter_start_time = max(chapter['start'], previous_start_time + 1)
        tags.add(CHAP(
            element_id = chapter['id'],
            start_time = max(0, chapter_start_time),
            end_time = min(chapter['end'], broadcast_duration),
            sub_frames = sub_frames,
        ))
        previous_start_time = chapter_start_time

    tags.add(CTOC(
        element_id = "toc",
        flags = CTOCFlags.TOP_LEVEL | CTOCFlags.ORDERED,
        child_element_ids = [ chapter['id'] for chapter in chapters if not chapter['hidden'] ],
        sub_frames = [TIT2(text=["Table Of Contents"])],
    ))

    # Save ID3 tags.
    # Microsoft Windows Explorer is said to handle only up to ID3v2.3, let's be friendly
    tags.save(filepath, v2_version=3)


def main():
    parser = argparse.ArgumentParser(
        description = "Find all availabe recordings of a show on FM4's website, download them as MP3 files and save the shows' metadata in the ID3 tags.",
    )
    parser.add_argument("-c", "--cut", help='Cut all chapters of given types from recording, comma separated. Known types: B = Feature ("Beitrag"), J = Jingle, M = Music ("Musik"), N = News ("Nachrichten"), SO = Feature, W = Advertisement ("Werbung") (default: %(default)s)', default=None,  metavar='TYPE')
    parser.add_argument("-i", "--ignore", help='Ignore recommended audio section removals. Typically News are removed/skipped this way (default: %(default)s)', action='store_true')
    parser.add_argument("-n", "--newest", help='Download newest broadcast only (default: %(default)s)', default=False, action='store_true')
    parser.add_argument("ShowTitle", help='The show\'s title (e.g. "Morning Show")')
    parser.add_argument("TargetDirectory", help='Directory to save the files in (default: %(default)s)', nargs='?', default=os.getcwd())

    args = parser.parse_args()

    CUT_CHAPTER_TYPES = [ x.strip().upper() for x in args.cut.split(',') ] if args.cut else []
    IGNORE_KEEPMARKS = args.ignore
    ONLY_NEWEST = args.newest
    SHOW = args.ShowTitle.strip()
    DESTDIR = args.TargetDirectory

    # If PyAV is not available do not try to cut anything
    if not PYAV_AVAILABLE and (CUT_CHAPTER_TYPES or not IGNORE_KEEPMARKS):
        print("PyAV not found, cutting audio not supported. Will continue to download complete broadcasts.")
        CUT_CHAPTER_TYPES = []
        IGNORE_KEEPMARKS = True

    if not os.path.isdir(DESTDIR):
        print(f"Directory {DESTDIR} does not exist!", file=sys.stderr)
        sys.exit(1)

    # Search for all broadcasts of show
    all_broadcast_jsons = get_all_broadcasts(SHOW)

    if not all_broadcast_jsons:
        print(f"No broadcasts for '{SHOW}' found.", file=sys.stderr)
        sys.exit()

    if ONLY_NEWEST:
        all_broadcast_jsons = [ all_broadcast_jsons[0] ]

    # Process all matching broadcasts
    for broadcast_json in all_broadcast_jsons:

        # Create final filename
        filepath = os.path.join(DESTDIR, create_filename(broadcast_json))

        # Skip this broadcast if file already exists
        if os.path.isfile(filepath) and os.path.getsize(filepath)>0:
            print(f"{filepath} already exists, skipping.", flush=True)
            continue

        # Get chapters
        chapters = get_chapters(broadcast_json)

        # Get markers with recommended audio sections to keep
        if IGNORE_KEEPMARKS:
            keepmarks = [ [0, broadcast_json['end'] - broadcast_json['start']] ]
        else:
            keepmarks = get_keepmarks(broadcast_json)

        # Remove unwanted chapters from keepmarks and from list of chapters
        if CUT_CHAPTER_TYPES:
            keepmarks = remove_chaptertypes_from_keepmarks(
                keepmarks,
                chapters,
                CUT_CHAPTER_TYPES)
            chapters = [ c for c in chapters if c['type'] not in CUT_CHAPTER_TYPES ]

        # Realign chapters with keepmarks unless there's only a single keepmark spanning the whole broadcast
        if not keepmarks == [ [0, broadcast_json['end'] - broadcast_json['start']] ]:
            chapters = align_chapters_to_keepmarks(chapters, keepmarks)

        # Download broadcast's audio
        # Note: Downloading only the required audio parts (and merging them)
        #       works, but ORF's server does not deliver perfectly cut parts
        #       leading to inaccurate chapter marks, and sometimes even hangs.
        #       So let's download the whole brodcast and remove the parts
        #       that are not needed afterwards.
        loopStreamId = broadcast_json['streams'][0]['loopStreamId']
        url = STATION_INFO['shoutcast_base_url'] % loopStreamId
        broadcast_audio = download_audio(url)
        if not broadcast_audio:
            # download failed. try next broadcast
            continue

        # Cut audio data with PyAV unless there's only one keepmark, spanning whole broadcast
        if keepmarks != [ [0, broadcast_json['end'] - broadcast_json['start']] ]:
            broadcast_audio = cut_audio(broadcast_audio, keepmarks)

        # Save audio data to file
        with open(filepath + '.temp', 'wb') as output_file:
            output_file.write(broadcast_audio)

        # Set id3 tags
        set_id3_tags(filepath + '.temp', chapters, keepmarks, broadcast_json)

        # Rename temporary mp3 file to final filename
        os.rename(filepath + '.temp', filepath)

        print(f"Saved as {filepath}")

    return True


if __name__ == "__main__":
    # Register SIGINT handler
    signal.signal(signal.SIGINT, interrupt_handler)

    main()
