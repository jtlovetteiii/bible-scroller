# Prep Sermon

---
argument-hint: The Price of Freedom
description: Reads a sermon outline from a specified document and generates a JSON file that contains just the verses.
---

Each Sunday, the Pastor of our church prepares a document that outlines the key points and Scripture references in his sermon. It's my job to create a presentation that enables the congregation to follow along. I use a combination of tools:

- Key points are translated into static slides in Microsoft PowerPoint.
- Scripture references are displayed using this app ("Bible Scroller").

Before you proceed, make sure you've read this app's README file in its entirety and understand what this app does and how it works.

As you'll observe in the README, this app can read Bible passages from JSON files in the "passages" folder. This is where you can help me out: given the name of a sermon, I want you to read the outline, extract the Scripture passages that you find, ignore everything else, and create a JSON file in the "passages" folder that I can load into this app.

Be sure to follow the pattern of existing files in the "passages" folder. In general, these files just contain a JSON array where each entry is a Scripture passage from the outline. Each array entry must contain a "ref" (the chapter, verse, and reference exactly as it appears in the outline), and a "text" (the text of the passage exactly as it appears in the outline).

IMPORTANT: When creating the JSON file, you MUST properly escape all double quote characters (") within the Scripture text by replacing them with (\"). This is critical for valid JSON syntax. For example, if the text contains "The Lord is one," it must be written as \"The Lord is one,\" in the JSON.

IMPORTANT: Scripture passages in the outline often contain verse numbers embedded within the text (e.g., "...of His glory. 32 All the nations will be gathered..."). You MUST remove these inline verse numbers from the text field. Only the actual Scripture words should remain—no verse markers or numbers. For example, "...of His glory. 32 All the nations will be gathered..." should become "...of His glory. All the nations will be gathered..." The verse numbers serve as markers in the outline but should not appear in the final presentation.

IMPORTANT: Marking words of Jesus Christ and Old Testament quotations requires additional passes after the JSON is complete. Follow this three-pass workflow:

**Pass 1**: Generate the complete JSON file with all passages and media — no markup yet. Show the user the completed file.

**Pass 2**: Go back through each NT passage and add `<span class="words-of-christ">` tags where appropriate. Rules:
- ONLY in New Testament passages (Matthew, Mark, Luke, John, Acts, Revelation, etc.)
- Do NOT mark any text in Old Testament passages (Genesis through Malachi)
- If a passage is clearly attributed to Jesus by context (e.g. "He said to them", "Jesus answered", "He answered and said"), wrap the full spoken content — do not require explicit quotation marks in the outline text
- In the Gospels, Jesus often speaks in extended discourses spanning many verses (e.g., the Nicodemus discourse John 3:10–21, the Farewell Discourse John 14–17). If a verse falls inside such a discourse, it is Jesus' words even if that specific verse has no "Jesus said" introduction
- Parables told by Jesus: wrap the entire quoted parable
- When a passage contains multiple speakers, only wrap Jesus' portion
- Always wrap Christ's words in quotation marks inside the span, even when the entire passage is His words. If the text doesn't already have them, add them
- Example: `<span class="words-of-christ">"I am the way, the truth, and the life."</span>`
- If a case is ambiguous, ask the user rather than guessing

**Pass 3**: Go back through NT passages and mark embedded Old Testament quotations with `<span class="words-of-quote">`. Rules:
- Triggered by introductory phrases like "it is written:", "as it is written,", "He says:", "the Scripture says:", followed by a quoted block
- Wrap the quoted text including its quotation marks in the span
- Example: `as it is written, <span class="words-of-quote">"The just shall live by faith."</span>`
- Only applies within NT passages — do not mark quotes within OT passages

IMPORTANT: Formatting requirements for each passage:
- Always capitalize the first letter of each passage text, even if it appears lowercase in the outline
- Ensure each passage ends with proper punctuation (period, question mark, or exclamation point)
- If a passage ends with a comma or semicolon, replace it with a period
- Do not add punctuation if the passage already ends properly

IMPORTANT: Media files handling:
- After creating the passages array, check if a folder exists in the "passages" directory with the same name as the sermon date (e.g., "passages/2025-12-07/")
- If such a folder exists and contains image files (JPEG, PNG, etc.), create a "media" array in the JSON file
- Include each image file in the media array with its relative path (e.g., "2025-12-07/Slide1.jpeg") and "alt" set to "None"
- List the images in the order they appear in the folder (typically Slide1, Slide2, etc.)

Note that what you're embedding into the file is Scripture, which to our congregation is sacred and of great importance. Be careful! Do not, under any circumstance, alter the actual Scripture text that you find in the outline—only remove verse number markers and apply the formatting requirements above!