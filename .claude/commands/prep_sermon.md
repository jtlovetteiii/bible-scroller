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

IMPORTANT: Automatically identify and mark the words of Jesus Christ in red. When a passage contains direct quotes from Jesus, wrap those words in `<span class="words-of-christ">` tags. This includes:
- Passages from the Gospels (Matthew, Mark, Luke, John) that contain Jesus' spoken words
- Typically, Jesus' words are already indicated by quotation marks in the text
- The entire quoted statement should be wrapped, including the quotation marks
- Example: `<span class="words-of-christ">"I am the way, the truth, and the life."</span>`

Note that what you're embedding into the file is Scripture, which to our congregation is sacred and of great importance. Be careful! Do not, under any circumstance, alter the actual Scripture text that you find in the outline—only remove verse number markers!