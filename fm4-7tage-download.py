#!/usr/bin/env python3

import sys
import urllib.parse
import os
import re
import time
from datetime import datetime
import argparse
import io
import signal

from mutagen.id3 import ID3,ID3NoHeaderError,TRSN,TRSO,TPE1,TALB,TRCK,TIT2,COMM,TYER,TDAT,TIME,TLEN,CTOC,CHAP,WOAS,WORS,TCON,APIC,CTOCFlags,PictureType
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
    'player_search_url': "https://audioapi-v2.orf.at/radiothek/api/2.0/search/?q={query}&station=fm4&excludeType=M&excludeType=ML&excludeType=DJ&entity=broadcast&limit={limit}&offset={offset}",
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

    # search results are paginated
    query = urllib.parse.quote_plus(show_title)
    limit = 20
    offset = 0
    search_results = []
    while True:
        results_json = requests.get(STATION_INFO['player_search_url'].format(query=query, limit=limit, offset=offset), timeout=5).json()
        if results_json['length'] == 0:
            break
        search_results += results_json['payload']
        offset += limit

    # loop through search results, for each result check if it's valid and get its broadcast json, with items
    all_broadcasts = []
    # For each search result, sorted from newest to oldest: fetch linked broadcasts
    for hit in sorted(search_results, key=lambda x: x['data']['start'], reverse=True):

        # Skip broadcasts that have not ended yet
        if datetime.fromisoformat(hit['data']['end']).timestamp() > datetime.now().timestamp():
            continue

        # Remove station's name from show's title, so that user may search for 'fm4 house of pain' or 'house of pain'
        clean_show_title = re.sub(r'^' + STATION_INFO['name'] + r'[\-\s]*', '', show_title, flags=re.IGNORECASE)
        # Skip broadcast if title does match the wanted show's name, with or without the station's name in front
        if not re.search(r'^\s*(?:' + STATION_INFO['name'] + r')?[\s\-]*' + clean_show_title + r'\s*$', hit['data']['title'], flags=re.IGNORECASE):
            continue

        # Download json of broadcast, including items (=chapters)
        broadcast = requests.get(hit['data']['href'] + '?items=true', timeout=5).json()
        all_broadcasts.append(broadcast['payload'])

    return all_broadcasts


def create_filename(broadcast):
    """
    Construct a sensible filename for the broadcast
    """

    show_name = strip_html(broadcast['title'])
    station_name = STATION_INFO['name'] if not show_name.lower().startswith(STATION_INFO['name'].lower()) else None
    airdate_string = datetime.fromisoformat(broadcast['start']).astimezone().strftime("%Y-%m-%d %H:%M")

    filename = ' '.join(filter(None, [station_name, show_name, airdate_string])) + '.mp3'

    return re.sub(r'[^\w\s\-\.\[\]]','_', filename)


def get_chapters(broadcast):
    """
    Get list of chapters ("items") from broadcast
    """

    broadcast_duration = broadcast['duration']
    chapters = []
    for item_num, item in enumerate(sorted(broadcast['items'], key=lambda x: (x['start'], 1/x['duration']))):
        # do not take start/end from item's stream - in rare cases items do not have a stream element at all
        broadcast_start_ts = datetime.fromisoformat(broadcast['start']).timestamp()
        item_start_ts = datetime.fromisoformat(item['start']).timestamp()

        offset_start = (item_start_ts - broadcast_start_ts) * 1000
        offset_end = offset_start + item['duration']

        if item['entity'] != "BroadcastItem":
            continue

        chapter = {
            'id': f'chp{item_num+1}',
            'offset_start': int(max(0, offset_start)),
            'offset_end': int(min(offset_end, broadcast_duration)),
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


def get_keepmarks(broadcast):
    """
    In its player, ORF often does not play the whole broadcast as it got aired, but leaves some parts out (e.g. news)
    The parts that are played are listed as "streams" in broadcast. Each stream has a start and end time. It seems like streams do never overlap.

    Return a list [startTime, endTime] of all "streams" and use them as suggestion which parts of the broadcast to keep (and which to remove)
    Times are seconds from broadcast start.
    In case of no markers, return empty list and keep all audio
    """

    keepmarks = []
    broadcast_duration = broadcast['duration']

    for stream in sorted(broadcast['streams'], key=lambda x: x['offsetStart']):
        # Assure keepmark does neither start before nor end after broadcast
        offset_start = max(stream['offsetStart'], 0)
        offset_end = min(stream['offsetEnd'], broadcast_duration)

        keepmarks.append([offset_start, offset_end])

    return keepmarks


def remove_chapters_from_keepmark(keepmark, chapters):
    """
    Remove list of chapters from a keepmark
    Return list of new keepmarks

    This is used by remove_chaptertypes_from_keepmarks() to get rid of unwanted audio.
    """
    for chapter_num, chapter in enumerate(chapters):

        # Chaper starts after this keepmark. chapters are sorted by time, so we are done
        if chapter['offset_start'] > keepmark[1]:
            return [ keepmark ]

        # Chapter has already ended before this keepmark -> head on with next chapter
        if chapter['offset_end'] <= keepmark[0]:
            continue

        # Chapter spans whole keepmark -> ditch keepmark
        if chapter['offset_start'] >= keepmark[0] and chapter['offset_end'] >=  keepmark[1]:
            #return []
            break

        # Chapter starts before this keepmark and ends in this keepmark
        if chapter['offset_start'] < keepmark[0]:
            return remove_chapters_from_keepmark([chapter['offset_end'], keepmark[1]], chapters[chapter_num:])

        # Chapter starts and ends in this keepmark -> split it up into two, head on with right one
        if chapter['offset_end'] <= keepmark[1]:
            left = [ keepmark[0], chapter['offset_start'] ]
            right = remove_chapters_from_keepmark([ min(chapter['offset_end'], keepmark[1]), keepmark[1]], chapters[chapter_num:])
            return [ left ] + right

    # keepmark not affected by any chapter, return unmodified
    return [ keepmark ]


def remove_chaptertypes_from_keepmarks(keepmarks, chapters, chapter_types):
    """
    Remove chapters of given types from keepmarks so that they get cut out.
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
    If audio segments get cut out, chapter start & end markers (or even both) may be in the removed parts of audio.
    Ensure every chapter contains audio (if not: drop it), and starts/ends at the proper time
    """

    chapters = sorted(chapters, key=lambda x: x['offset_start'])
    keepmarks = sorted(keepmarks, key=lambda x: x[0])

    broadcast_duration = sum(offset_end - offset_start for offset_start, offset_end in keepmarks)

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
        new_offset_start = None
        new_offset_end = None
        skip_chapter_flag = False
        # Walk through keepmarks from start to end, and set chapter start times
        for keepmark_num, keepmark in enumerate(keepmarks):
            if chapter['offset_end'] < keepmark[0]:
                # Chapter ends before start of keepmark
                # -> Skip chapter
                skip_chapter_flag = True
                break
            if chapter['offset_start'] <= keepmark[1]:
                # Chapter ends after start of keepmark (see if-clause above) and ends before end of keepmark
                # -> Fix chapter's start time
                new_offset_start = max(chapter['offset_start'], keepmark[0]) - gaps[keepmark_num]
                break

        if skip_chapter_flag:
            continue

        # Walk through keepmarks from end to start, and set chapter end times
        for keepmark_num, keepmark in reversed(list(enumerate(keepmarks))):
            if chapter['offset_start'] > keepmark[1]:
                # Chapter starts after end of keepmark
                # -> Skip chapter
                skip_chapter_flag = True
                break
            if chapter['offset_end'] >= keepmark[0]:
                # Chapter starts before end of keepmark (see if-clause above) and ends after start of keepmark
                # -> Fix chapter's end time
                new_offset_end = min(chapter['offset_end'], keepmark[1]) - gaps[keepmark_num]
                break

        if skip_chapter_flag:
            continue

        if new_offset_start is not None and new_offset_end is not None and new_offset_start < new_offset_end:
            aligned_chapter=chapter.copy()
            aligned_chapter['offset_start'] = new_offset_start
            aligned_chapter['offset_end'] = min(new_offset_end, broadcast_duration)
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
            output_container.add_stream('mp3', bit_rate=input_stream.bit_rate, rate=input_stream.rate)

            keepmarks_iter = iter(sorted(keepmarks, key=lambda x: x[0]))
            start, end = next(keepmarks_iter)

            for packet in input_container.demux(input_stream):
                if packet.dts is None:
                    # Skip "flushing" packets created by demux
                    continue

                timestamp = int(packet.pts * input_stream.time_base)

                if timestamp * 1000 < start:
                    continue
                elif timestamp * 1000 >= end:
                    try:
                        start, end = next(keepmarks_iter)
                    except StopIteration:
                        break
                else:
                    output_container.mux(packet)

            return output_buffer.getvalue()


def strip_html(text: str):
    """
    Remove HTML tags from a string
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
    Try to download biggest image using broadcast JSON's "images" entry
    Return dict {'data': binary image data, 'mime': image mime type }
    """

    if not images_list:
        return None

    # get biggest (usually 600px width) image
    for image_version in sorted(images_list[0]['versions'], key=lambda x: x['width'], reverse=True):
        try:
            response = requests.get(image_version['path'], timeout=5)
            if response.status_code == 200:
                return {
                    'data': response.content,
                    'mime': response.headers['content-type'],
                    'description': images_list[0].get('alt') or images_list[0].get('text'),
                }
        except:
            # Try to get lower resolution image
            continue
    return None


def set_id3_tags(filepath, chapters, keepmarks, broadcast):
    """
    Set id3 tags on mp3 file
    """

    # Calculate audio duration
    broadcast_duration = sum(end-start for start, end in keepmarks)

    # Create datetime object from broadcast's start time
    broadcast_datetime = datetime.fromisoformat(broadcast['start'])

    # Create sensible broadcast description
    broadcast_description = "\n".join(filter(None, map(strip_html, [
        broadcast.get('subtitle'),
        broadcast.get('description'),
        broadcast.get('pressRelease')
    ])))
    if not broadcast_description:
        broadcast_description = broadcast_datetime.astimezone().strftime("%Y-%m-%d %H:%M")

    # Remove (potentially) existing id3 tags
    try:
        tags = ID3(filepath)
        tags.delete()
    except ID3NoHeaderError:
        tags = ID3()

    # Add new id3 tags
    tags.add(TRSN(text=[STATION_INFO['name']]))                           # Internet radio station name
    tags.add(TRSO(text=['ORF']))                                          # Internet radio station owner
    try:
        tags.add(WOAS(url=broadcast['link']['url']))                      # Official audio source webpage
    except (KeyError, TypeError):
        pass
    tags.add(WORS(url=STATION_INFO['website']))                           # Official Internet radio station homepage
    tags.add(TCON(text=["Radio Recording"]))                              # Content Description

    tags.add(TPE1(text=[strip_html(STATION_INFO['name'])]))               # Lead performer(s)/Soloist(s) -> "FM4"
    tags.add(TALB(text=[strip_html(broadcast['title'])]))                 # Album/Movie/Show title
    tags.add(TRCK(text=["1/1"]))                                          # Track number/Position in set
    tags.add(TIT2(text=[broadcast_datetime.astimezone().strftime("%Y-%m-%d %H:%M")]))   # Title/songname/content description

    tags.add(COMM(lang="deu", desc="desc", text=[broadcast_description])) # Comments

    tags.add(TYER(text=[broadcast_datetime.astimezone().strftime("%Y")]))              # Year of broadcast
    tags.add(TDAT(text=[broadcast_datetime.astimezone().strftime("%d%m")]))            # Day and month of broadcast
    tags.add(TIME(text=[broadcast_datetime.astimezone().strftime("%H%M")]))            # Time of broadcast

    tags.add(TLEN(text=[int(broadcast_duration)]))                        # Duration in ms

    # Try to download and add cover image
    image = get_image(broadcast.get('images'))
    if image:
        tags.add(APIC(
            type=PictureType.COVER_FRONT,
            desc=image['description'],
            mime=image['mime'],
            data=image['data']
        ))

    # Chapters
    # ID3 forbids multiple chapters having the same start time
    #  -> If multiple chapters start at the same time, start with the longest one and add 1ms to each following
    previous_offset_start = -1
    for chapter in sorted(chapters, key=lambda x: (x['offset_start'], 1/x['offset_end'])):
        sub_frames = []

        chapter_title = chapter.get('title')
        if chapter_title:
            sub_frames.append(TIT2(text=[chapter_title]))

        chapter_image = get_image(chapter.get('images'))
        if chapter_image:
            sub_frames.append(APIC(
                type=PictureType.OTHER,
                desc=chapter_image['description'],
                mime=chapter_image['mime'],
                data=chapter_image['data']
            ))

        offset_start = max(chapter['offset_start'], previous_offset_start + 1)
        tags.add(CHAP(
            element_id = chapter['id'],
            start_time = int(max(0, offset_start)),
            end_time = int(min(chapter['offset_end'], broadcast_duration)),
            sub_frames = sub_frames,
        ))
        previous_offset_start = offset_start

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
        print("PyAV not found, cutting audio not supported. Will download complete broadcasts.")
        CUT_CHAPTER_TYPES = []
        IGNORE_KEEPMARKS = True

    if not os.path.isdir(DESTDIR):
        print(f"Directory {DESTDIR} does not exist!", file=sys.stderr)
        sys.exit(1)

    # Search for all broadcasts of show
    all_broadcasts = get_all_broadcasts(SHOW)

    if not all_broadcasts:
        print(f"No broadcasts for '{SHOW}' found.", file=sys.stderr)
        sys.exit()

    if ONLY_NEWEST:
        all_broadcasts = [ all_broadcasts[0] ]

    # Process all matching broadcasts
    for broadcast in all_broadcasts:

        broadcast_duration = broadcast['duration']

        # Create final filename
        filepath = os.path.join(DESTDIR, create_filename(broadcast))

        # Skip this broadcast if file already exists
        if os.path.isfile(filepath) and os.path.getsize(filepath)>0:
            print(f"{filepath} already exists, skipping.", flush=True)
            continue

        # Get chapters
        chapters = get_chapters(broadcast)

        # Get markers with recommended audio sections to keep
        if IGNORE_KEEPMARKS:
            keepmarks = [ [0, broadcast_duration] ]
        else:
            keepmarks = get_keepmarks(broadcast)

        # Remove unwanted chapters from keepmarks and from list of chapters
        if CUT_CHAPTER_TYPES:
            keepmarks = remove_chaptertypes_from_keepmarks(
                keepmarks,
                chapters,
                CUT_CHAPTER_TYPES)
            chapters = [ c for c in chapters if c['type'] not in CUT_CHAPTER_TYPES ]

        # Realign chapters with keepmarks unless there's only a single keepmark spanning the whole broadcast
        if not keepmarks == [ [0, broadcast['duration']] ]:
            chapters = align_chapters_to_keepmarks(chapters, keepmarks)

        # Download broadcast's audio
        # Note: Downloading only the required audio parts (and merging them)
        #       works, but ORF's server does not deliver perfectly cut parts
        #       leading to inaccurate chapter marks, and sometimes even hang during downloads.
        #       So let's download the whole brodcast and remove the parts
        #       that are not needed afterwards.
        url = re.sub(r'{.*$', '', broadcast['streams'][0]['uriTemplates']['progressive'])
        broadcast_audio = download_audio(url)
        if not broadcast_audio:
            # Download failed. Try next broadcast
            continue

        # Cut audio data with PyAV unless there's only one keepmark, spanning whole broadcast
        if keepmarks != [ [0, broadcast_duration] ]:
            broadcast_audio = cut_audio(broadcast_audio, keepmarks)

        # Save audio data to file
        with open(filepath + '.temp', 'wb') as output_file:
            output_file.write(broadcast_audio)

        # Set id3 tags
        set_id3_tags(filepath + '.temp', chapters, keepmarks, broadcast)

        # Rename temporary mp3 file to final filename
        os.rename(filepath + '.temp', filepath)

        print(f"Saved as {filepath}")

    return True


if __name__ == "__main__":
    # Register SIGINT handler
    signal.signal(signal.SIGINT, interrupt_handler)

    main()
