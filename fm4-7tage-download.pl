#!/usr/bin/perl

use strict;
use warnings;
use WWW::Mechanize;
use URI::Encode;
use JSON;
use POSIX;
use HTML::Strip;
use File::Spec;
use MP3::Tag;
MP3::Tag->config(write_v24=>1);
use Unicode::String qw(utf8 latin1);

$|=1;

if (@ARGV ne 2) {
    print "USAGE:\n";
    print $0." <ShowTitle> <downloadDir>\n\n";
    print "Example:\n";
    print $0.' "Morning Show" "Downloads/Morning Show Recordings"'."\n";
    exit;
}

my $SENDUNG=$ARGV[0];
my $DESTDIR=$ARGV[1];

die("Directory ".$DESTDIR." does not exist!\n") unless (-d $DESTDIR);

my $searchUrl="https://audioapi.orf.at/fm4/api/json/current/search?q=";
my $shoutcastBaseUrl="http://loopstream01.apa.at/?channel=fm4&id=";

my $browser=WWW::Mechanize->new(timeout=>5);
my $removeHtml=HTML::Strip->new();
$browser->get($searchUrl.URI::Encode::uri_encode($SENDUNG));
my $result=JSON->new()->utf8->decode($browser->content());

foreach (@{$result->{'hits'}}) {
    $browser->get($_->{'data'}->{'href'});
    my $data=JSON->new()->utf8->decode($browser->content());
    my ($title)=$data->{'title'}=~/^\s*(.+?)\s*$/;
    next unless $title=~/$SENDUNG/i;	# Filter out results not containing the query string in the title
    my $broadcastDate=POSIX::strftime("%Y-%m-%d",localtime($data->{'start'}/1000));
    my $description=$removeHtml->parse(($data->{'description'}) or $broadcastDate);

    my @parts=(sort { $a->{'start'} cmp $b->{'start'}} @{$data->{'streams'}});	# for multi-part shows sort them by start time...
    for (my $i=0; $i<@parts; $i++) {

	my $tagTitle=$title." ".$broadcastDate;
	$tagTitle.=" [".($i+1)."/".@parts."]" if @parts>1;	# ...and add "[currentPartNo/totalParts]" to title

	my $filename="FM4 ".$tagTitle.".mp3";
	$filename=~s/[^\w\s\-\.\[\]]/_/g;

	if (-f File::Spec->join($DESTDIR,$filename)) {
	    print $filename." already exists, skipping.\n";
	    next;
	}

	print $filename." downloading... ";
	my ($tries,@parameters,$FD);
	$tries=4;
	@parameters=(
	    $shoutcastBaseUrl.$parts[$i]->{'loopStreamId'},	# URL
	    ":content_cb" => sub {
		my ($chunk) = @_;
		print $FD $chunk;
	    });
	while ($tries) {
	    open($FD,">>".File::Spec->join($DESTDIR, $filename.".part"));

	    my $bytes=-s File::Spec->join($DESTDIR, $filename.".part");
	    if ($bytes > 0) {
		push(@parameters,"Range"=>"bytes=".$bytes."-");
	    }
	    my $result=$browser->get(@parameters);
	    close $FD;

	    last if ($result->is_success or $result->code == 416);
	    $tries--;
	}
	if ($tries eq 0) {
	    print "failed.\n";
	    next;
	}

	rename(File::Spec->join($DESTDIR,$filename.".part"),File::Spec->join($DESTDIR,$filename));

	my $tag=MP3::Tag->new(File::Spec->join($DESTDIR,$filename));
	$tag->get_tags;
	$tag->new_tag("ID3v2") unless (exists $tag->{ID3v2});
	$tag->{ID3v2}->artist("FM4");
	$tag->{ID3v2}->title($tagTitle);
	$tag->{ID3v2}->comment($description);
	$tag->{ID3v2}->write_tag;
	print "done.\n";
    }
}
