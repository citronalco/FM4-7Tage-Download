# FM4 7-Tage Backup

The Austrian radio station FM4 publishes MP3 recordings of all of their shows during the last 7 days on its website.
This script is a simple command line interface for their player API, and allows you to download all currently available recordings for a specific show.

Example:

```./fm4-7tage-download.pl "morning show" Downloads/Morning-Show-Recordings```

This would download all available recordings of "Morning Show" and save them in the "Downloads/Morning-Show-Recordings" directory.
Recordings get correct id3 tags, files aready downloaded are skipped, so it should be well suited for cron jobs.
