# Flowchart Examples

This document contains example flowcharts that we might receive from the minster of music, along with commentary on gotchas and notes on how the agent should handle generating the slide deck. Note that this document is for training/informational purposes only.

## Example: 7/5/2026

### Actual Flowchart

Star spangled
America the beautiful 2x
Mine eyes have seen the glory 2x
My country tis of thee 3x

Choir: one nation

Tehillah
His name is Jesus
King of Kings

Quartet

Video

Invitation: I am resolved

### Notes

There are a few gotchas with this flowchart:

- It doesn't contain all of the usual service elements, but they can be implied and assumed by the agent.
- There isn't a prelude: "The Star-Spangled Banner" (national anthem) serves as a special prelude congregational hymn. This is very atypical.
- There is more than one special music slot: the choir and the quartet. When we see "quartet" by itself in the flow, it usually means "The Lovette Quartet", but that's not a given.

The actual slide deck, based only on this information, would be:

- Welcome slide (welcome-text-{season})
- Formal Welcome (welcome-text-{season}, welcome-card-{season}, welcome-text-{season}, scripture-emphasis)
- Hymns (title card and lyric cards for both hymns)
- Choir special
- Congregational singing ("His Name Is Jesus" and "King of Kings" -- "Tehillah" is the name of our praise team; this is a marker for congregational singing, not a named performer)
- Special music slide for the quartet
  - Note: The agent might can safely assume "The Lovette Quartet", but this represents a validation issue: the minister should always provide the name of the song being performed, not just the performer.
- Black slide for transition to the Pastor's message (the video will be added later, outside of this deck)
- Pastor's message (no slides needed: handled by the Bible Scroller app)
- Invitation hymn (title card and lyric cards)
- Closing prayer
- Ending slide (welcome-blank-{season})

Note, however, that this isn't actually correct. The flowchart doesn't tell us this, but the Star-Spangled Banner is a "hymn", sung by the congregation, that takes the place of the prelude slot. Also, the minister later wanted to add quartet and choir lyric slides.

Here's how I would have imagined the email flow to go:

- Minister sends an email with the appropriate subject line and the flowchart above
- Agent flags that the "Quartet" slot needs a song title and confirmation of the performer (it can suggest "Lovette Quartet")
- Since this is a "validation" issue, the agent should reply back requesting this information.
- Minister replies that the performer is the "Lovette Quartet" and that the song is "Portrait of America".
- Agent generates the slide deck. Let's assume for now that:
  - We have generated slides for the hymns before, so we have their lyrics in the library already and can reuse them without a lookup.
  - We hadn't done "His Name is Jesus" or "King of Kings" before, and these aren't hymns with a known lyric lookup path, so the agent was only able to generate the title card for the songs and has to ask the minister for the lyrics.
- Agent replies to the minister's email with:
  - A link to the slide deck
  - A request that the minister reply back with the lyrics for "His Name is Jesus" and "King of Kings", since we haven't done those before
- Minister notices that the Star-Spangled Banner is listed as a congregational hymn after the Welcome
- Minister replies to the agent's email with the requested lyrics and a note that the Star-Spangled Banner should come before the Welcome
- Agent re-generates the slide deck, storing the lyrics in the library, generating the lyric slides, and moving the Star-Spangled Banner slides
- Agent replies to the minister's email with:
  - A link to the slide deck
  - Any applicable notes or questions the agent had regarding the structure of the songs (if necessary)
- The minister decides this looks good
- Later in the week, the minister decides that he wants to put lyrics in for the Choir and Quartet special
- The minister replies to the agent's email with a note saying so, along with the lyrics
- Agent re-generates the slide deck, inserting the requested lyrics
  - I don't have a preference as to whether the agent stores these in the library for future use.
- Agent replies to the minister's email with a link to the slide deck and the requested changes.

## Example: 7/12/2026

### Actual Flowchart

Prelude: Heaven on my mind (Penelope Moore)

Hymns
O for a thousand tongues
Tell me the story of Jesus

Choir: Amazing Love Medley

Tehillah: Forever Yahweh

Jesus

Invitation: Before the throne of God above

### Notes

This is a fairly typical flowchart, but it doesn't convey the whole service--only the music. In situations like this, the other common service elements are implied and should be assumed by the agent. The actual slide deck, based only on this information, would be:

- Welcome slide (welcome-text-{season})
- Prelude (prelude card listing the song title and the singer "Penelope Moore")
- Formal Welcome (welcome-text-{season}, welcome-card-{season}, welcome-text-{season}, scripture-emphasis)
- Hymns (title card and lyric cards for both hymns)
- Choir special
- Congregational singing ("Forever Yahweh" and "Jesus" -- "Tehillah" is the name of our praise team; this is a marker for congregational singing, not a named performer)
- Black slide for transition to the Pastor's message
- Pastor's message (no slides needed: handled by the Bible Scroller app)
- Invitation hymn (title card and lyric cards)
- Closing prayer
- Ending slide (welcome-blank-{season})

There's a catch, though: the minister actually wanted lyric slides for the Prelude and the Choir songs. He didn't provide them in the flowchart, but he wanted them in the final output. So, here's how I would have imagined the agent flow to go:

- Minister sends an email with the appropriate subject line and the flowchart above
- Agent generates the slide deck. Let's assume for now that:
  - We had already used "O For A Thousand Tongues" in a previous deck, so the lyrics are already in the library
  - We hadn't done "Tell Me the Story of Jesus" or "Before the Throne of God Above" before, but the agent was able to look up the lyrics and store them
  - We hadn't done "Forever Yahweh" before, and this isn't a hymn with a known lyric lookup path, so the agent was only able to generate the title card for the song and has to ask the minister for the lyrics.
  - We had already done "Jesus" before, so the agent could reuse the lyrics from the library.
- Agent replies to the minister's email with:
  - A link to the slide deck
  - A note that we had to look up the lyrics for "Tell Me the Story of Jesus" and "Before the Throne of God Above", so the minister should check those slides carefully
  - A request that the minister reply back with the lyrics for "Forever Yahweh", since we haven't done that one before
- Minister replies to the agent's email with the requested lyrics
- Agent re-generates the slide deck, storing the lyrics in the library and generating the slides
- Agent replies to the minister's email with:
  - A link to the slide deck
  - Any applicable notes or questions the agent had regarding the structure of the song (if necessary)
- The minister decides this looks good
- Later in the week, the minister decides that he wants to put lyrics in for the Prelude and Choir special
- The minister replies to the agent's email with a note saying so, along with the lyrics
- Agent re-generates the slide deck, inserting the requested lyrics
  - I don't have a preference as to whether the agent stores these in the library for future use.
- Agent replies to the minister's email with a link to the slide deck and the requested changes.
- On Sunday morning, the minister realizes the the agent missed verse 3 of "Tell Me the Story of Jesus".
- The minister replies to the agent' email with a note saying so, and provides verse 3's lyrics
- Agent re-generates the slide deck, adding the slides for verse 3 (and the final refrain) of "Tell Me the Story of Jesus", and updating the library.
- Agent replies to the minister's email with a link to the slide deck