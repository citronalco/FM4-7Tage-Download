#!/usr/bin/env python3

# TODO:
# - Gibt's in den Infos was wann welches Lied gespielt wurde? -> chapters!!
# - retries bei requests
# - https://gist.github.com/Foolson/1db5620023675e55594e3af44f69a70d
# - https://id3.org/id3v2.3.0
# - chapters in rss: https://gist.github.com/gglnx/5233635
# - argparser

import requests
import sys
import urllib.parse
import os
import re
from datetime import datetime
from mutagen.id3 import ID3,ID3NoHeaderError,TRSN,TPE1,TALB,TRCK,TIT2,COMM,TYER,TDAT,TIME,TLEN,TDRL,CTOC,CHAP,WOAS,WORS,APIC,CTOCFlags

searchUrl = "https://audioapi.orf.at/fm4/api/json/current/search?q=%s";
shoutcastBaseUrl = "http://loopstream01.apa.at/?channel=fm4&id=%s";

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

    # add a comma after <br/>
    text = re.sub('(<br/?>)', r'\1, ', text, flags=re.IGNORECASE)

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
def download(url: str, file_path: str, attempts=4):
    for attempt in range(1, attempts+1):
        try:
            if attempt > 1:
                time.sleep(3)  # wait 3 seconds between download attempts
            with requests.get(url, stream=True) as response:
                response.raise_for_status()
                with open(file_path, 'wb') as out_file:
                    for chunk in response.iter_content(chunk_size=1024*1024):  # 1MB chunks
                        out_file.write(chunk)
                return True	# success
        except Exception as ex:
                return False
    return None


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

    # extract show name. skip if results not containing the show's name in the title
    match = re.search('^\s*(.*?'+SHOW+'.*?)\s*$',broadcastJson['title'],flags=re.IGNORECASE)
    if not match:
        continue
    showName = match.group(1)

    # extract start and end datetime
    showStart = datetime.fromtimestamp(broadcastJson['start']/1000)
    showEnd = datetime.fromtimestamp(broadcastJson['end']/1000)

    # build show description
    showDescription = strip_html(broadcastJson['description'])
    if showDescription is None:
        showDescription = strip_html(broadcastJson['subtitle'])
        if showDescription is None:
            showDescription = strip_html(broadcastJson['pressRelease'])
            if showDescription is None:
                showDescription = showStart.strftime("%Y-%m-%d %H:%M")


    # most shows have one part in the stream, some shows (e.g. Morning Show) are split into multiple stream parts
    # download them, sorted by start time
    streams = sorted(broadcastJson['streams'], key=lambda x: x['start'])

    for streamNr in range(0, len(streams)):
        tagTitle = showStart.strftime("%Y-%m-%d %H:%M")
        if len(streams)>1:
            tagTitle += " [" + str(streamNr+1) + "/" + str(len(streams)) + "]"

        filename = re.sub('[^\w\s\-\.\[\]]','_', showName + " " + tagTitle)
        match = re.search('^FM4 ',filename)
        if not match:
            filename = "FM4 "+filename
        filename+=".mp3"

        filepath = os.path.join(DESTDIR, filename)

        if os.path.isfile(filepath) and os.path.getsize(filepath)>0:
            print("%s already exists, skipping." % filepath, flush=True)
            continue

        print("%s downloading..." % filepath, end=" ", flush=True)
        if not download(shoutcastBaseUrl % broadcastJson['streams'][streamNr]['loopStreamId'], filepath+".part"):
            print("failed.", flush=True)
            continue

        # set ID3 tag
        try:
            tags = ID3(filepath+".part")
            tags.delete()
        except ID3NoHeaderError:
            tags = ID3()

        tags.add(TRSN(text=["FM4"]))
        tags.add(TPE1(text=["FM4"]))
        tags.add(TALB(text=[showName]))
        tags.add(TRCK(text=[str(streamNr+1) + "/" + str(len(streams))]))
        tags.add(TIT2(text=[tagTitle]))
        tags.add(COMM(lang="deu", desc="desc", text=[showDescription]))
        tags.add(TYER(text=[showStart.strftime("%Y")]))
        tags.add(TDAT(text=[showStart.strftime("%d%m")]))
        tags.add(TIME(text=[showStart.strftime("%H%M")]))
        tags.add(TLEN(text=[broadcastJson['streams'][streamNr]['end'] - broadcastJson['streams'][streamNr]['start']]))
        tags.add(WOAS(url=broadcastJson['url']))
        tags.add(WORS(url="http://fm4.orf.at"))

        # set chapter information according to show's "items"
        # https://mutagen.readthedocs.io/en/latest/user/id3.html
        chapters = []
        chapterNr = 0
        for item in sorted(broadcastJson['items'], key=lambda x: x['start']):
            if item['entity'] == "BroadcastItem":
                if item['end'] <= broadcastJson['streams'][streamNr]['start']:
                    continue
                if item['start'] >= broadcastJson['streams'][streamNr]['end']:
                    break

                chapterNr+=1

                chapterTitle = []
                for key in [ "interpreter", "title", "description" ]:
                    if key in item.keys():
                        if item[key] is not None:
                            chapterTitle.append(strip_html(item[key]))

                chapters.append({
                    "id": "ch"+str(chapterNr),
                    "title": " / ".join(chapterTitle),
                    "startTime": item['start']-broadcastJson['streams'][streamNr]['start'],
                    "endTime": item['end']-broadcastJson['streams'][streamNr]['start']	# FIXME: chapters (and shows?) seem to be 1s too long
                })

        for c in chapters:
            tags.add(CHAP(
                element_id = c["id"],
                start_time = c["startTime"],
                end_time = c["endTime"],
                sub_frames = [TIT2(text=[c["title"]])]
            ))


        tocList = ",".join([ c["id"] for c in chapters ])
        tags.add(CTOC(
            element_id = "toc",
            flags = CTOCFlags.TOP_LEVEL | CTOCFlags.ORDERED,
            child_element_ids = [tocList],
            sub_frames = [TIT2(text=["Table Of Contents"])]
        ))


        # cover image
        for i in range(2,-1,-1):
            try:
                response = requests.get(broadcastJson['images'][0]['versions'][i]['path'])
                if response.status_code == 200:
                    tags.add(APIC(mime=response.headers['content-type'], desc="Front Cover", data=response.content))
                    break
            except:
                continue


        # save ID3 tags
        tags.save(filepath+".part",v2_version=3)


        # done
        os.rename(filepath+".part", filepath)
        print("done.", flush=True)
