# FM4 7-Tage Download

Command line script to downloads recordings from FM4's Player.

## Description
The Austrian radio station FM4 publishes recordings of all shows on its website - but only for seven days.
This Python 3 command line script downloads currently available recordings of a show, so you can keep them longer.

The show's metadata, like playlist and cover images, gets stored in the downloaded files' ID3 tags (see below).
Optionally, sections like advertisements, news etc. are removed automatically.
Audio is not reencoded, so there is no loss in quality.
Recordings are saved in MP3 format.

Already downloaded broadcasts are skipped, so this script is well suited for cron jobs.

Be patient, FM4 throttles downloads quite heavily!

## Requirements
Python 3 with modules "mutagen", "requests" and, optionally, "av".
(On Debian/Ubuntu/Mint: `sudo apt install python3 python3-mutagen python3-requests python3-av`)

If the "av" Python module is installed, this script can cut broadcasts in the same way as it gets played in [FM4's Player](https://fm4.orf.at/player) (usually News at the beginning are removed). Additionally, it is able to remove advertisements, news, jingles, etc.
Without the "av" Python module, this script saves the whole broadcast.

## Usage
```
fm4-7tage-download.py [-h] [-c TYPE] [-i] [-n] ShowTitle [TargetDirectory]

Find all availabe recordings of a show on FM4's website, download them as MP3 files and save the shows' metadata in the ID3 tags.

positional arguments:
ShowTitle         The show's title (e.g. "Morning Show")
TargetDirectory   Directory to save the files in (default: current directory)

options:
-h, --help       Show this help message and exit
-c, --cut TYPE   Cut all chapters of given types from recording, comma separated (default: None)
                 Known types:
                     B = Feature ("Beitrag"), J = Jingle, M = Music ("Musik"),
                     N = News ("Nachrichten"), SO = Feature, W = Advertisement ("Werbung")
-i, --ignore     Ignore recommended audio section removals (default: False)
                 Typically News are removed/skipped this way
-n, --newest     Download newest broadcast only (default: False)
```
### Examples
**Simple:**

```fm4-7tage-download.py "morning show"```

Download all available broadcast of "*Morning Show*", cut them in the same way as FM4 does in it's Player, and save them with filled out ID3 tags into the current directory.

**Advanced:**

```fm4-7tage-download.py --cut N,W --ignore --newest "morning show" "Downloads/Morning Show Recordings"```

Download only the newest broadcast of "*Morning Show*" and save it with filled out ID3 tags into "*Downloads/Morning-Show-Recordings"*.
FM4's recommendations for cuts are ignored, and all News and advertisements get removed.


## ID3 Tags
This script not only downloads the recordings, but also automatically extracts all metadata provided by FM4 and saves it in appropriate ID3v2.3 tags of the downloaded MP3 files.
The tracklist with its cover images gets translated into ID3 chapters.

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
CTOC (): frame
CHAP (Chapters):
Chapter #0: start 0.000000, end 168.000000
title : News
Chapter #1: start 167.000000, end 177.000000
title : ch2
Chapter #2: start 441.000000, end 643.000000
title : Chika: My Power
Chapter #3: start 642.000000, end 823.000000
title : Cassia: Do Right
Chapter #4: start 823.000000, end 945.000000
title : Elderbrook über seine musikalische Entwicklung
[... snip! ...]
Chapter #92: start 13438.000000, end 13663.000000
title : Booka Shade ft. UNDERHER: Chemical Release
```

## See also
If you run a web server and want to listen to the downloaded shows with your podcast player: https://github.com/citronalco/mp3-to-rss2feed creates a RSS2 feed from MP3 files and their ID3 tags.
