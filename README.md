# FM4 7-Tage Download
The Austrian radio station FM4 publishes MP3 recordings of all of their shows during the last 7 days on its website.

This Python 3 script is a simple command line tool to download all currently available recordings for a specific show.

### Requirements
Python 3 with modules "mutagen", "urllib3" and "requests".
(On Debian/Ubuntu: `sudo apt install python3 python3-mutagen python3-urllib3 python3-requests`)

### Usage
```./fm4-7tage-download.py <ShowTitle> <TargetDirectory>```

The script searches in FM4's 7-Tage-Player API for shows with a matching name and downloads them into the given target directory.
Files aready present get skipped, so it is well suited for cron jobs.

The show's metadata gets stored in the downloaded MP3 file's ID3 tags (see below).

If a show's recording is split into multiple parts (e.g. "Morning Show"), the script will download all parts and name them accordingy ("FM4 Morning Show 2020-09-03 06_00 **[1_5]**.mp3, FM4 Morning Show 2020-09-03 06_00 **[2_5]**.mp3, ...).

**Example:**

```./fm4-7tage-download.py "morning show" Downloads/Morning-Show-Recordings```

This would download all available recordings of "Morning Show" and save them with correct ID3 tags in the "Downloads/Morning-Show-Recordings" directory.


## ID3 Tags
The show's metadata is used **extensively** to set the ID3v2.3 tags for downloaded recordings.

**Example:**

The downloaded file `Downloads/Morning-Show-Recordings/FM4 Morning Show 2020-09-03 06_00 [1_5].mp3` gets this ID3 tags:
```
TPE1 (Lead performer(s)/Soloist(s)): FM4
TALB (Album/Movie/Show title): Morning Show
TIT2 (Title/songname/content description): 2020-09-03 06:00 [1/5]
TRCK (Track number/Position in set): 1/5
TLEN (Length): 00:26:33
TDAT (Date): 0309
TIME (Time): 0600
TYER (Year): 2020
APIC (Attached picture): (Front Cover)[, 3]: image/jpeg, 32580 bytes
COMM (Comments): (desc)[deu]: Die FM4 Morning Show mit Dave Dempsey und Christoph Sepin | Wir machen Urlaub 
                              auf der schönsten Insel Österreichs, vergeben ein sehr rares Exemplar des FM4
                              Kalenders, erzählen euch alles über das Filmfestival Venedig und freuen uns, 
                              dass unseren Austrian Act of the Day Strandhase zu Gast zu haben.
TRSN (Internet radio station name): FM4
WORS (Official internet radio station homepage): http://fm4.orf.at
WOAS (Official audio source webpage): http://fm4.orf.at/radio/stories/fm4morningshow
CHAP (Chapters):
    Chapter #0: start 0.000000, end 171.000000
      title           : News
    Chapter #1: start 170.000000, end 187.000000
      title           : ch2
    Chapter #2: start 206.000000, end 423.000000
      title           : Kid Simius ft. Enda Gallery / Livin'It Up
    Chapter #3: start 420.000000, end 656.000000
      title           : Tame Impala / Is It True
    Chapter #4: start 652.000000, end 859.000000
      title           : Warpaint / New Song
    Chapter #5: start 859.000000, end 1083.000000
      title           : FM4 Inselhüpfen: Die Wiener Donauinsel
    Chapter #6: start 1079.000000, end 1324.000000
      title           : Der Nino Aus Wien / Praterlied / Live 29/08/2020 Alter Schalchthof Wels; 30/08 Sommerspiele
                        Perchtoldsdorf; 04/09 Aula Linz
    Chapter #7: start 1323.000000, end 1368.000000
      title           : ch8
    Chapter #8: start 1368.000000, end 1562.000000
      title           : DJ Shadow ft Run The Jewels / Nobody Speak / from the album 'The Mountain Will Fall' out
                        June 24, 2016 FM4 Soundselection 35, out November 11, 2016
```
