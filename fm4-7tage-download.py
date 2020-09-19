#!/usr/bin/env python3

# TODO:
# - Add playlists (like https://fm4.orf.at/radio/stories/3007157/ or https://fm4.orf.at/radio/stories/3007304/), maybe content or URL as comment? But: How to find the right link?
# - pydub does not concat the MP3 files but reencodes them. This is slow and unnecessary.

import requests
import sys
import urllib.parse
import os
import re
import time
from datetime import datetime
from mutagen.id3 import ID3,ID3NoHeaderError,TRSN,TPE1,TALB,TRCK,TIT2,COMM,TYER,TDAT,TIME,TLEN,CTOC,CHAP,WOAS,WORS,APIC,CTOCFlags

try:
    from pydub import AudioSegment
    createSingleFile = True
except ImportError:
    createSingleFile = False


searchUrl = "https://audioapi.orf.at/fm4/api/json/current/search?q=%s"
shoutcastBaseUrl = "http://loopstream01.apa.at/?channel=fm4&id=%s"

stationInfo = {
   'name': 'FM4',
   'website': 'http://fm4.orf.at',
}

if len(sys.argv) != 3:
    print("Usage:", file=sys.stderr)
    print("%s <ShowTitle> <DownloadDir>\n" % sys.argv[0], file=sys.stderr)
    print("Example:", file=sys.stderr)
    print("%s 'Morning Show' 'Downloads/Morning Show Recordings'\n" % sys.argv[0], file=sys.stderr)
    sys.exit(1)

SHOW = sys.argv[1]
DESTDIR = sys.argv[2]

if not os.path.isdir(DESTDIR):
    print("Directory %s does not exist!" % DESTDIR, file=sys.stderr)
    sys.exit(1)

# remove html tags
def strip_html(text: str):
    if text is None:
        return None

    # add a | after <br/>
    text = re.sub('(<br/?>)', r'\1 | ', text, flags=re.IGNORECASE)

    # add a | between </p></p>
    text = re.sub('\s*(</p>)\s*(<p>)\s*', r'\1 | \2 ', text, flags=re.IGNORECASE)

    tag = False
    quote = False
    out = ""
    for c in text:
            if c == '<' and not quote:
                tag = True
            elif c == '>' and not quote:
                tag = False
            elif (c == '"' or c == "'") and tag:
                quote = not quote
            elif not tag:
                out = out + c

    # remove multiple consecutive spaces
    out = re.sub('\s\s+',' ',out)

    return out

# download in chunks
def download(url: str, filepath: str, attempts=4):
    for attempt in range(1, attempts+1):
        try:
            if attempt > 1:
                time.sleep(3)  # wait 3 seconds between download attempts
            with requests.get(url, stream=True) as response:
                response.raise_for_status()
                with open(filepath, 'wb') as out_file:
                    for chunk in response.iter_content(chunk_size=1024*1024):  # 1MB chunks
                        out_file.write(chunk)
                return True	# success
        except:
                return False
    return False


# search for show
response = requests.get(searchUrl % urllib.parse.quote_plus(SHOW), timeout=5)
result = response.json()

# for each search result fetch linked data
for hit in result['hits']:
    # only care about "Broadcast" and skip everything else
    if hit['data']['entity'] != "Broadcast":
        continue

    # get json of matching broadcast
    broadcastJson = requests.get(hit['data']['href'], timeout=5).json()

    # dictionary to collect show data
    showInfo = {
        'name': None,
        'description': None,
        'website': None,

        'start_dt': None,
        'end_dt': None,

        'image_data': None,
        'image_mime': None,

        'parts': [],

        'title': None,

        'filename': None,
        'filepath': None,
    }

    # extract show name. skip if result does not contain the show's name in the title
    match = re.search('^\s*(.*?'+SHOW+'.*?)\s*$',broadcastJson['title'],flags=re.IGNORECASE)
    if match:
        showInfo['name'] = match.group(1)
    else:
        continue

    # extract start and end datetime
    showInfo['start_dt'] = datetime.fromtimestamp(broadcastJson['start']/1000)
    showInfo['end_dt'] = datetime.fromtimestamp(broadcastJson['end']/1000)

    # build show description
    showInfo['description'] = strip_html(broadcastJson['description']) or \
                              strip_html(broadcastJson['subtitle']) or \
                              strip_html(broadcastJson['pressRelease']) or \
                              showInfo['start_dt'].strftime("%Y-%m-%d %H:%M")

    # link to show's website
    showInfo['website'] = broadcastJson['url']

    # get show's cover image
    for i in range(2,-1,-1):
        try:
            response = requests.get(broadcastJson['images'][0]['versions'][i]['path'])
            if response.status_code == 200:
                showInfo['image_data'] = response.content
                showInfo['image_mime'] = response.headers['content-type']
                break
        except:
            continue

    # title (used as ID3 TIT2 and in filename. human readable date/time)
    showInfo['title'] = showInfo['start_dt'].strftime("%Y-%m-%d %H:%M")

    # filename
    showInfo['filename'] = re.sub('[^\w\s\-\.\[\]]','_', showInfo['name'] + " " + showInfo['title'])
    # prepend station name to filename
    match = re.search('^'+stationInfo['name']+' ', showInfo['filename'])
    if not match:
        showInfo['filename'] = stationInfo['name'] + ' ' + showInfo['filename']
    showInfo['filename'] += ".mp3"

    # filepath
    showInfo['filepath'] = os.path.join(DESTDIR, showInfo['filename'])

    # skip if file already exists
    if os.path.isfile(showInfo['filepath']) and os.path.getsize(showInfo['filepath'])>0:
        print("%s already exists, skipping." % showInfo['filepath'], flush=True)
        continue


    # most shows consist of a single file, but some shows (e.g. Morning Show) are split into multiple parts
    # download them, sorted by start time
    streamParts = sorted(broadcastJson['streams'], key=lambda x: x['start'])

    for streamPartNr in range(0, len(streamParts)):
        partInfo = {
            'url': broadcastJson['streams'][streamPartNr]['loopStreamId'],

            'start_ts': broadcastJson['streams'][streamPartNr]['start'],
            'end_ts': broadcastJson['streams'][streamPartNr]['end'],
            'duration_ms': broadcastJson['streams'][streamPartNr]['end'] - broadcastJson['streams'][streamPartNr]['start'],

            'title': showInfo['title'],

            'filename': None,
            'filepath': None,

            'chapters': [],
        }

        # if show has more than 1 part: append current_part/total_parts to title
        if len(streamParts)>1:
            partInfo['title'] += " [" + str(streamPartNr+1) + "/" + str(len(streamParts)) + "]"

        # build filename
        partInfo['filename'] = re.sub('[^\w\s\-\.\[\]]','_', showInfo['name'] + " " + partInfo['title'])

        # prepend station name to filename
        match = re.search('^'+stationInfo['name']+' ', partInfo['filename'])
        if not match:
            partInfo['filename'] = stationInfo['name'] + ' ' + partInfo['filename']
        partInfo['filename'] += ".mp3"

        # filepath
        partInfo['filepath'] = os.path.join(DESTDIR, partInfo['filename'])


        # skip file if it already exists
        if os.path.isfile(partInfo['filepath']) and os.path.getsize(partInfo['filepath'])>0:
            print("%s already exists, skipping." % partInfo['filepath'], flush=True)
            continue

        # download file
        print("Downloading %s ..." % partInfo['filepath'], end=" ", flush=True)
        if download(shoutcastBaseUrl % partInfo['url'], partInfo['filepath']+".part"):
            print("done.", flush=True)
        else:
            print("failed.", flush=True)
            continue

        # set chapter information according to show's "items"
        chapterNr = 0
        for item in sorted(broadcastJson['items'], key=lambda x: x['start']):
            if item['entity'] == "BroadcastItem":
                # skip items that end too early or start too soon for the current stream part
                if item['end'] <= partInfo['start_ts']:
                    continue
                if item['start'] >= partInfo['end_ts']:
                    break

                chapterNr+=1

                chapterInfo = {
                    "id": "ch"+str(chapterNr),
                    "title": None,
                    "start_ms": None,
                    "end_ms": None,
                }

                # build chapter title
                chapterTitles = []
                for key in [ "interpreter", "title", "description" ]:
                    if key in item.keys():
                        if item[key] is not None:
                            chapterTitles.append(strip_html(item[key]))
                chapterInfo['title'] = " / ".join(chapterTitles)

                # for multipart shows sometimes chapters start in the previous part, so the start time is negative
                # In ID3 chapter start times must be >=0, so we set chapter start to 0 in that case
                chapterInfo['start_ms'] = item['start'] - partInfo['start_ts']
                if chapterInfo['start_ms'] < 0:
                    chapterInfo['start_ms'] = 0

                chapterInfo['end_ms'] = item['end'] - partInfo['start_ts']	# FIXME: chapters (and shows?) seem to be 1s too long
                if chapterInfo['end_ms'] > partInfo['duration_ms']:
                    chapterInfo['end_ms'] = partInfo['duration_ms']

                partInfo['chapters'].append(chapterInfo)


        showInfo['parts'].append(partInfo)


    # merge parts?
    if len(showInfo['parts']) > 1 and createSingleFile == True:
        print("Merging parts to %s..." % showInfo['filepath'], end=" ", flush=True)

        # concat parts (pydub creates a wav file and re-encodes it afterwards...)
        showAudio = sum( (AudioSegment.from_mp3(part['filepath']+".part") for part in showInfo['parts']) )
        showAudio.export(showInfo['filepath']+'.part', format="mp3")

        # remove part files
        for part in showInfo['parts']:
            os.remove(part['filepath']+".part")

        print("done.", flush=True)

        # create partInfo for newly merged single part
        mergedPartInfo = {
            'url': None,

            'start_ts': broadcastJson['start'],
            'end_ts': broadcastJson['end'],
            'duration_ms': sum(list(part['end_ts'] - part['start_ts'] for part in showInfo['parts'])),

            'title': showInfo['title'],

            'filename': showInfo['filename'],
            'filepath': showInfo['filepath'],

            'chapters': [],
        }

        # recalculate chapter marks and reassign chapter ids
        prevPartEnd_ts = showInfo['parts'][0]['start_ts']
        offset_ms = 0
        prevDuration = 0
        chapterNr = 0
        for part in sorted(showInfo['parts'], key=lambda x: x['start_ts']):
            offset_ms += prevDuration
            for chapter in part['chapters']:
                chapterNr += 1
                newChapterInfo = {
                    "id": "ch" + str(chapterNr),
                    "title": chapter['title'],
                    "start_ms": chapter['start_ms'] + offset_ms,
                    "end_ms": chapter['end_ms'] + offset_ms,
                }
                #print("GAP: "+ str(offset_ms/1000) + " " + time.strftime("%H:%M:%S", time.gmtime(newChapterInfo['start_ms']/1000)) + " - " + newChapterInfo['title'])
                mergedPartInfo['chapters'].append(newChapterInfo)
            prevDuration = part['end_ts'] - part['start_ts']

        # replace old parts with new merged part
        showInfo['parts'] = [ mergedPartInfo ]


    # write ID3 Tag
    for partNo in range(len(showInfo['parts'])):
        # set ID3 tags
        try:
            tags = ID3(showInfo['parts'][partNo]['filepath']+".part")
            tags.delete()
        except ID3NoHeaderError:
            tags = ID3()

        tags.add(TRSN(text=[stationInfo['name']]))
        tags.add(TPE1(text=[stationInfo['name']]))
        tags.add(TALB(text=[showInfo['name']]))
        tags.add(TRCK(text=[str(partNo+1) + "/" + str(len(showInfo['parts']))]))
        tags.add(TIT2(text=[showInfo['parts'][partNo]['title']]))
        tags.add(COMM(lang="deu", desc="desc", text=[showInfo['description']]))
        tags.add(TYER(text=[showInfo['start_dt'].strftime("%Y")]))
        tags.add(TDAT(text=[showInfo['start_dt'].strftime("%d%m")]))
        tags.add(TIME(text=[showInfo['start_dt'].strftime("%H%M")]))
        tags.add(TLEN(text=[showInfo['parts'][partNo]['duration_ms']]))
        tags.add(WOAS(url=showInfo['website']))
        tags.add(WORS(url=stationInfo['website']))

        for chapter in showInfo['parts'][partNo]['chapters']:
            tags.add(CHAP(
                element_id = chapter["id"],
                start_time = chapter["start_ms"],
                end_time = chapter["end_ms"],
                sub_frames = [TIT2(text=[chapter["title"]])]
            ))

        tocList = ",".join([ chapter["id"] for chapter in showInfo['parts'][partNo]['chapters'] ])
        tags.add(CTOC(
            element_id = "toc",
            flags = CTOCFlags.TOP_LEVEL | CTOCFlags.ORDERED,
            child_element_ids = [tocList],
            sub_frames = [TIT2(text=["Table Of Contents"])]
        ))

        if showInfo['image_mime'] is not None and showInfo['image_data'] is not None:
            tags.add(APIC(mime=showInfo['image_mime'], desc="Front Cover", data=showInfo['image_data']))

        # save ID3 tags
        tags.save(showInfo['parts'][partNo]['filepath']+".part",v2_version=3)


        # done!
        os.rename(showInfo['parts'][partNo]['filepath']+".part", showInfo['parts'][partNo]['filepath'])
        os.chmod(showInfo['parts'][partNo]['filepath'], 0o644)
