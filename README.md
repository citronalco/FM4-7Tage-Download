# FM4 7-Tage Download
The Austrian radio station FM4 publishes recordings of all of their shows during the last 7 days on its website.

This Python 3 script is a simple command line tool to download all currently available recordings for a specific show as MP3 files.
The show's metadata gets stored in the downloaded files' ID3 tags (see below).

Files aready present are skipped, so it is well suited for cron jobs.

### Requirements
Python 3 with modules "mutagen", "requests" and optionally "pydub".
(On Debian/Ubuntu/Mint: `sudo apt install python3 python3-mutagen python3-requests pydub`)

FM4 splits some shows (e.g. "Morning Show") into multiple files, probably to cut out advertisements.
This script will download all those files and, with installed **"pydub"** Python module, merge them into a single MP3 file.
If "pydub" is not installed the parts are saved as seperate MP3 files and named accordingy (e.g. "FM4 Morning Show 2020-09-03 06_00 **[1_5]**.mp3, FM4 Morning Show 2020-09-03 06_00 **[2_5]**.mp3, ...).

### Usage
```./fm4-7tage-download.py <ShowTitle> <TargetDirectory>```

**Example:**

```./fm4-7tage-download.py "morning show" Downloads/Morning-Show-Recordings```

This would download all available recordings of "Morning Show" and save them with correct ID3 tags in the "Downloads/Morning-Show-Recordings" directory.

Be patient, FM4 throttles downloads.

## ID3 Tags
The metadata provided by FM4 is used **extensively** to set the ID3v2.3 tags for downloaded recordings.

**Example:**

The downloaded file `Downloads/Morning-Show-Recordings/FM4 Morning Show 2020-09-18 06_00.mp3` gets this ID3 tag:
```
TRSN (Internet radio station name): FM4
WORS (Official internet radio station homepage): http://fm4.orf.at
WOAS (Official audio source webpage): http://fm4.orf.at/radio/stories/fm4morningshow
TPE1 (Lead performer(s)/Soloist(s)): FM4
TDAT (Date): 1809
TIME (Time): 0600
TYER (Year): 2020
TALB (Album/Movie/Show title): Morning Show
TIT2 (Title/songname/content description): 2020-09-18 06:00
TRCK (Track number/Position in set): 1/1
TLEN (Length): 13663000
COMM (Comments): (desc)[deu]: With Julie McCarthy and Daniel Grabner | We kept two Fm4 Kalender to
                              give away to you and also we've got tickets for the Horror Classic
                              From Beyond. In exchange we want your songs and bands with plants:
                              trees, flowers, bushes - what are your favourites? Let us know and
                              we'll play them!
APIC (Attached picture): (Front Cover)[, 3]: image/jpeg, 32580 bytes
CTOC ():  frame
CHAP (Chapters):
    Chapter #0: start 0.000000, end 168.000000
      title           : News
    Chapter #1: start 167.000000, end 177.000000
      title           : ch2
    Chapter #2: start 441.000000, end 643.000000
      title           : Chika / My Power
    Chapter #3: start 642.000000, end 823.000000
      title           : Cassia / Do Right
    Chapter #4: start 823.000000, end 945.000000
      title           : Elderbrook über seine musikalische Entwicklung
    [... snip! ...]
    Chapter #92: start 13438.000000, end 13663.000000
      title           : Booka Shade ft. UNDERHER / Chemical Release
```

### See also
If you want to listen to the downloaded shows with your podcast player: https://github.com/citronalco/mp3-to-rss2feed creates a RSS2 feed from MP3 files.
