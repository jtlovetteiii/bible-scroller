// Sample passages from John 1:1-10
const passages = [
    {
        ref: "John 1:1–3",
        text: "In the beginning was the Word, and the Word was with God, and the Word was God. He was in the beginning with God. All things were made through him, and without him was not any thing made that was made."
    },
    {
        ref: "John 1:4–5",
        text: "In him was life, and the life was the light of men. The light shines in the darkness, and the darkness has not overcome it."
    },
    {
        ref: "John 1:6–8",
        text: "There was a man sent from God, whose name was John. He came as a witness, to bear witness about the light, that all might believe through him. He was not the light, but came to bear witness about the light."
    },
    {
        ref: "John 1:9–10",
        text: "The true light, which gives light to everyone, was coming into the world. He was in the world, and the world was made through him, yet the world did not know him."
    }
];

const media = [];

let currentIndex = 0;
let currentMediaIndex = 0;
let presentationMode = 'scripture'; // scripture or media
let isPartiallyScrolled = false; // Track if we're mid-passage
let isBlanked = false; // Track if content is blanked (bookmark mode)
let stickyWasVisible = false; // Track sticky reference state before blanking
let isLightTheme = false; // Track current theme state
let currentMode = 'normal'; // Track current mode: 'normal', 'edit', 'style'
let currentFileName = null; // Track currently loaded file
let isFileBrowserOpen = false; // Track file browser state

// Hold-to-scroll state
let isScrollingDown = false;
let isScrollingUp = false;
let scrollAnimationFrame = null;
let lastScrollTimestamp = null;
const SCROLL_SPEED = 350; // pixels per second (reading pace)

// Render all verses to the DOM
function renderVerses() {
    const container = document.getElementById('verses-container');

    // Clear existing content
    container.innerHTML = '';

    // Create verse sections
    passages.forEach((passage, index) => {
        const section = document.createElement('div');
        section.className = 'verse-section';
        section.id = `verse-${index}`;

        if (index === currentIndex) {
            section.classList.add('active');
        } else if (index > currentIndex) {
            section.classList.add('upcoming');
        }

        const ref = document.createElement('div');
        ref.className = 'verse-ref';
        ref.textContent = passage.ref;
        ref.dataset.index = index; // Store index for saving later

        const text = document.createElement('div');
        text.className = 'verse-text';
        // Use innerHTML to support styled content (like words-of-christ spans)
        text.innerHTML = passage.text;

        section.appendChild(ref);
        section.appendChild(text);
        container.appendChild(section);
    });

    // If in edit mode, re-enable editing on new elements
    if (currentMode === 'edit') {
        enableEditing();
    }
}

// Initialize the scroller
function init() {
    // Render initial verses
    renderVerses();

    // Set up keyboard navigation
    document.addEventListener('keydown', handleKeyPress);
    document.addEventListener('keyup', handleKeyRelease);

    // Set up file browser
    initFileBrowser();

    // Hide controls hint after a few seconds
    setTimeout(() => {
        const hint = document.getElementById('controls-hint');
        hint.style.opacity = '0';
    }, 5000);
}

// Handle keyboard navigation
function handleKeyPress(event) {
    // Escape key exits edit or style mode
    if (event.key === 'Escape') {
        if (currentMode === 'edit') {
            event.preventDefault();
            toggleEditMode();
            return;
        } else if (currentMode === 'style') {
            event.preventDefault();
            toggleStyleMode();
            return;
        }
    }

    // Mode switching keys work only in normal mode
    if (currentMode === 'normal') {
        if (event.key === 'e' || event.key === 'E') {
            event.preventDefault();
            toggleEditMode();
            return;
        } else if (event.key === 's' || event.key === 'S') {
            event.preventDefault();
            toggleStyleMode();
            return;
        }
    }

    // Navigation keys only work in normal mode
    if (currentMode === 'normal') {
        if (event.key === ' ') {
            // Spacebar: Jump to next passage or media
            event.preventDefault();
            jumpToNextPassage();
        } else if (event.key === 'ArrowDown') {
            event.preventDefault();
            if (presentationMode === 'media') {
                // In media mode: navigate to next media
                jumpToNextPassage();
            } else {
                // In scripture mode: start continuous scroll (hold to scroll)
                if (!isScrollingDown) {
                    startScrollDown();
                }
            }
        } else if (event.key === 'ArrowUp') {
            event.preventDefault();
            if (presentationMode === 'media') {
                // In media mode: navigate to previous media
                navigatePrevious();
            } else {
                // In scripture mode: start continuous scroll up (hold to scroll)
                if (!isScrollingUp) {
                    startScrollUp();
                }
            }
        } else if (event.key === 'b' || event.key === 'B') {
            event.preventDefault();
            toggleBlank();
        } else if (event.key === 't' || event.key === 'T') {
            event.preventDefault();
            toggleTheme();
        } else if (event.key === 'f' || event.key === 'F') {
            event.preventDefault();
            toggleFileBrowser();
        } else if (event.key === 'm' || event.key === 'M') {
            event.preventDefault();
            togglePresentationMode();
        }
    }

    // File browser: Escape key closes it
    if (isFileBrowserOpen && event.key === 'Escape') {
        event.preventDefault();
        toggleFileBrowser();
    }

    // In style mode, handle text selection with Enter key
    if (currentMode === 'style' && event.key === 'Enter') {
        event.preventDefault();
        applyChristWordsStyle();
    }
}

// Handle key release to stop continuous scrolling
function handleKeyRelease(event) {
    // Only stop scrolling if in normal mode and scripture mode
    if (currentMode === 'normal' && presentationMode === 'scripture') {
        if (event.key === 'ArrowDown') {
            stopScrollDown();
        } else if (event.key === 'ArrowUp') {
            stopScrollUp();
        }
    }
}

// Jump to next passage (Spacebar)
function jumpToNextPassage() {
    // In media mode, advance to next media item
    if (presentationMode === 'media') {
        if (currentMediaIndex < media.length - 1) {
            currentMediaIndex++;
            fadeToNextMedia();
        }
        return;
    }
    
    if (currentIndex < passages.length - 1) {
        currentIndex++;
        isPartiallyScrolled = false;
        scrollToVerse(currentIndex);
        updateVerseStates();
    }
}

function navigatePrevious() {
    // In media mode, go back to previous media item
    if (presentationMode === 'media') {
        if (currentMediaIndex > 0) {
            currentMediaIndex--;
            fadeToNextMedia();
        }
    }
}

// Start continuous scroll down (hold Down arrow)
function startScrollDown() {
    isScrollingDown = true;
    showStickyReference();
    showScrollGradient();
    lastScrollTimestamp = null; // Reset timestamp

    const scrollStep = (timestamp) => {
        if (!isScrollingDown) return;

        const scrollContainer = document.getElementById('scroller-container');
        const currentVerse = document.getElementById(`verse-${currentIndex}`);

        if (!currentVerse) {
            stopScrollDown();
            return;
        }

        // Check if we're at the bottom boundary of the current passage
        const verseRect = currentVerse.getBoundingClientRect();
        const containerRect = scrollContainer.getBoundingClientRect();
        const verseBottom = verseRect.bottom;
        const viewportBottom = containerRect.bottom;

        // Stop scrolling if we've reached the end of the current passage
        if (verseBottom <= viewportBottom + 50) {
            stopScrollDown();
            return;
        }

        // Calculate scroll amount based on elapsed time
        if (lastScrollTimestamp !== null) {
            const deltaTime = timestamp - lastScrollTimestamp;
            const scrollAmount = (SCROLL_SPEED / 1000) * deltaTime;
            scrollContainer.scrollTop += scrollAmount;
            isPartiallyScrolled = true;
        }

        lastScrollTimestamp = timestamp;
        scrollAnimationFrame = requestAnimationFrame(scrollStep);
    };

    scrollAnimationFrame = requestAnimationFrame(scrollStep);
}

// Stop continuous scroll down
function stopScrollDown() {
    isScrollingDown = false;
    if (scrollAnimationFrame) {
        cancelAnimationFrame(scrollAnimationFrame);
        scrollAnimationFrame = null;
    }
    lastScrollTimestamp = null;
}

// Start continuous scroll up (hold Up arrow)
function startScrollUp() {
    isScrollingUp = true;
    lastScrollTimestamp = null; // Reset timestamp

    const scrollStep = (timestamp) => {
        if (!isScrollingUp) return;

        const scrollContainer = document.getElementById('scroller-container');
        const currentVerse = document.getElementById(`verse-${currentIndex}`);

        if (!currentVerse) {
            stopScrollUp();
            return;
        }

        // Check if we're at the top boundary of the current passage
        const verseRect = currentVerse.getBoundingClientRect();
        const containerRect = scrollContainer.getBoundingClientRect();
        const verseTop = verseRect.top;
        const viewportTop = containerRect.top;

        // Stop scrolling if we've reached the start of the current passage
        if (verseTop >= viewportTop - 50) {
            stopScrollUp();
            hideStickyReference();
            hideScrollGradient();
            isPartiallyScrolled = false;
            return;
        }

        // Calculate scroll amount based on elapsed time
        if (lastScrollTimestamp !== null) {
            const deltaTime = timestamp - lastScrollTimestamp;
            const scrollAmount = (SCROLL_SPEED / 1000) * deltaTime;
            scrollContainer.scrollTop -= scrollAmount;
        }

        lastScrollTimestamp = timestamp;
        scrollAnimationFrame = requestAnimationFrame(scrollStep);
    };

    scrollAnimationFrame = requestAnimationFrame(scrollStep);
}

// Stop continuous scroll up
function stopScrollUp() {
    isScrollingUp = false;
    if (scrollAnimationFrame) {
        cancelAnimationFrame(scrollAnimationFrame);
        scrollAnimationFrame = null;
    }
    lastScrollTimestamp = null;
}

// Scroll to a specific verse (between-passage transition)
function scrollToVerse(index, instant=false) {
    const verse = document.getElementById(`verse-${index}`);
    if (verse) {
        verse.scrollIntoView({
            behavior: instant ? 'instant' : 'smooth',
            block: 'start'
        });
    }
}

// Update visual states of verses (active, dimmed, upcoming)
function updateVerseStates() {
    passages.forEach((_, index) => {
        const section = document.getElementById(`verse-${index}`);

        // Remove all state classes
        section.classList.remove('active', 'upcoming');

        // Add appropriate class
        if (index === currentIndex) {
            section.classList.add('active');
        } else if (index > currentIndex) {
            section.classList.add('upcoming');
        }
        // Past verses (index < currentIndex) have no special class (default dimmed state)
    });

    // Hide sticky reference and gradient when transitioning between verses
    hideStickyReference();
    hideScrollGradient();
}

// Show sticky reference header
function showStickyReference() {
    const stickyRef = document.getElementById('sticky-reference');
    const stickyText = document.getElementById('sticky-reference-text');

    stickyText.textContent = passages[currentIndex].ref;
    stickyRef.classList.remove('hidden');
}

// Hide sticky reference header
function hideStickyReference() {
    const stickyRef = document.getElementById('sticky-reference');
    stickyRef.classList.add('hidden');
}

// Show scroll gradient overlay
function showScrollGradient() {
    const gradient = document.getElementById('scroll-gradient');
    gradient.classList.remove('hidden');
}

// Hide scroll gradient overlay
function hideScrollGradient() {
    const gradient = document.getElementById('scroll-gradient');
    gradient.classList.add('hidden');
}

// Toggle blank mode (bookmark state)
function toggleBlank() {
    isBlanked = !isBlanked;

    const versesContainer = document.getElementById('verses-container');
    const stickyRef = document.getElementById('sticky-reference');

    if (isBlanked) {
        // Remember if sticky reference was visible before blanking
        stickyWasVisible = !stickyRef.classList.contains('hidden');

        // Fade out content and hide sticky reference
        versesContainer.classList.add('blanked');
        if (stickyWasVisible) {
            stickyRef.classList.add('hidden');
        }
    } else {
        // Fade back in
        versesContainer.classList.remove('blanked');

        // Restore sticky reference if it was visible before blanking
        if (stickyWasVisible) {
            stickyRef.classList.remove('hidden');
        }
    }
}

// Toggle theme (light/dark)
function toggleTheme() {
    isLightTheme = !isLightTheme;

    if (isLightTheme) {
        document.body.classList.add('light-theme');
    } else {
        document.body.classList.remove('light-theme');
    }
}

// Toggle presentation mode between scripture and media
function togglePresentationMode() {
    console.log('togglePresentationMode called. media.length:', media.length);
    console.log('media array:', media);
    console.log('presentationMode:', presentationMode);

    if (media.length === 0) {
        // No media available, can't switch to media mode
        console.log('No media available, cannot switch to media mode');
        return;
    }

    if (presentationMode === 'scripture') {
        // Switch to media mode
        console.log('Switching to media mode');
        presentationMode = 'media';
        showMediaMode();
    } else {
        // Switch back to scripture mode
        console.log('Switching to scripture mode');
        presentationMode = 'scripture';
        showScriptureMode();
    }
}

// Show media mode (fade in current media item)
function showMediaMode() {
    const versesContainer = document.getElementById('verses-container');
    const mediaContainer = document.getElementById('media-container');
    const stickyRef = document.getElementById('sticky-reference');
    const scrollGradient = document.getElementById('scroll-gradient');

    // Hide sticky reference and scroll gradient if visible
    stickyRef.classList.add('hidden');
    scrollGradient.classList.add('hidden');

    // Show media container and render current media item
    mediaContainer.style.display = 'flex';
    renderCurrentMedia();

    // Start crossfade: fade out verses and fade in media simultaneously
    setTimeout(() => {
        versesContainer.style.transition = 'opacity 1.2s ease-in-out';
        mediaContainer.style.transition = 'opacity 1.2s ease-in-out';

        versesContainer.style.opacity = '0';
        mediaContainer.style.opacity = '1';

        // After transition completes, hide verses container and clear styles
        setTimeout(() => {
            versesContainer.style.display = 'none';
            versesContainer.style.opacity = '';
            versesContainer.style.transition = '';
            mediaContainer.style.transition = '';
        }, 1200);
    }, 50);
}

// Show scripture mode (fade back to verses)
function showScriptureMode() {
    const versesContainer = document.getElementById('verses-container');
    const mediaContainer = document.getElementById('media-container');

    // Show verses container and prepare for crossfade
    versesContainer.style.display = 'block';

    // Scroll to the current verse immediately (before fade begins)
    scrollToVerse(currentIndex, true);

    // Start crossfade: fade out media and fade in verses simultaneously
    setTimeout(() => {
        versesContainer.style.transition = 'opacity 1.2s ease-in-out';
        mediaContainer.style.transition = 'opacity 1.2s ease-in-out';

        mediaContainer.style.opacity = '0';
        // Only set opacity to 1 if not blanked
        if (!isBlanked) {
            versesContainer.style.opacity = '1';
        } else {
            versesContainer.style.opacity = '0.05';
        }

        // After transition completes, hide media container and clear inline styles
        setTimeout(() => {
            mediaContainer.style.display = 'none';
            // Clear inline opacity to let CSS classes (like .blanked) control it
            versesContainer.style.opacity = '';
            versesContainer.style.transition = '';
            mediaContainer.style.transition = '';
        }, 1200);
    }, 50);
}

// Render the current media item
function renderCurrentMedia() {
    const mediaContainer = document.getElementById('media-container');

    if (currentMediaIndex < 0 || currentMediaIndex >= media.length) {
        mediaContainer.innerHTML = '<div class="media-error">No media available</div>';
        return;
    }

    const mediaItem = media[currentMediaIndex];
    const img = document.createElement('img');
    img.src = `passages/${mediaItem.src}`;
    img.alt = mediaItem.alt || '';
    img.className = 'media-image active';

    mediaContainer.innerHTML = '';
    mediaContainer.appendChild(img);
}

// Fade transition between media items (crossfade)
function fadeToNextMedia() {
    const mediaContainer = document.getElementById('media-container');
    const currentImg = mediaContainer.querySelector('.media-image.active');

    if (!currentImg) {
        // No current image, just render the new one
        renderCurrentMedia();
        return;
    }

    // Create the new image
    const mediaItem = media[currentMediaIndex];
    const newImg = document.createElement('img');
    newImg.src = `passages/${mediaItem.src}`;
    newImg.alt = mediaItem.alt || '';
    newImg.className = 'media-image';

    // Set initial style to be invisible but on top
    newImg.style.opacity = '0';
    newImg.style.zIndex = '2';

    // Keep old image visible underneath
    currentImg.style.zIndex = '1';

    // Wait for the image to load before starting the crossfade
    newImg.onload = () => {
        // Add new image to container (it starts at opacity 0 on top)
        mediaContainer.appendChild(newImg);

        // Trigger fade-in of new image (old image stays at opacity 1 underneath)
        setTimeout(() => {
            newImg.style.transition = 'opacity 0.6s ease-in-out';
            newImg.style.opacity = '1';

            // Remove old image after transition completes
            setTimeout(() => {
                currentImg.remove();
                // Clean up inline styles and add active class
                newImg.style.opacity = '';
                newImg.style.zIndex = '';
                newImg.style.transition = '';
                newImg.classList.add('active');
            }, 600);
        }, 50);
    };

    // Handle load errors gracefully
    newImg.onerror = () => {
        console.error('Failed to load image:', newImg.src);
        // Fall back to just showing the new image
        renderCurrentMedia();
    };
}

// Update mode indicator UI
function updateModeIndicator() {
    const indicator = document.getElementById('mode-indicator');
    const indicatorText = document.getElementById('mode-indicator-text');

    if (currentMode === 'normal') {
        indicator.classList.add('hidden');
        indicator.classList.remove('edit-mode', 'style-mode');
    } else if (currentMode === 'edit') {
        indicator.classList.remove('hidden', 'style-mode');
        indicator.classList.add('edit-mode');
        indicatorText.textContent = 'EDIT MODE';
    } else if (currentMode === 'style') {
        indicator.classList.remove('hidden', 'edit-mode');
        indicator.classList.add('style-mode');
        indicatorText.textContent = 'STYLE MODE - Select text and press Enter';
    }
}

// Toggle Edit Mode
function toggleEditMode() {
    if (currentMode === 'edit') {
        // Exit edit mode
        currentMode = 'normal';
        disableEditing();
    } else {
        // Enter edit mode
        currentMode = 'edit';
        enableEditing();
    }
    updateModeIndicator();
}

// Toggle Style Mode
function toggleStyleMode() {
    if (currentMode === 'style') {
        // Exit style mode
        currentMode = 'normal';
    } else {
        // Enter style mode
        currentMode = 'style';
    }
    updateModeIndicator();
}

// Enable editing on all verse text elements
function enableEditing() {
    // Make verse text editable
    const verseTexts = document.querySelectorAll('.verse-text');
    verseTexts.forEach(text => {
        text.contentEditable = 'true';
        text.style.outline = '2px dashed rgba(100, 150, 255, 0.5)';
    });

    // Make verse references editable and add edit buttons
    const verseRefs = document.querySelectorAll('.verse-ref');
    verseRefs.forEach((ref, index) => {
        ref.contentEditable = 'true';
        ref.style.outline = '2px dashed rgba(100, 150, 255, 0.3)';

        // Add edit buttons to each verse reference
        // Don't add buttons if they already exist
        if (ref.querySelector('.edit-buttons')) return;

        const buttonContainer = document.createElement('span');
        buttonContainer.className = 'edit-buttons';

        // Move up button
        const upBtn = document.createElement('button');
        upBtn.className = 'edit-btn';
        upBtn.textContent = '↑';
        upBtn.title = 'Move passage up';
        upBtn.onclick = () => movePassageUp(index);

        // Move down button
        const downBtn = document.createElement('button');
        downBtn.className = 'edit-btn';
        downBtn.textContent = '↓';
        downBtn.title = 'Move passage down';
        downBtn.onclick = () => movePassageDown(index);

        // Insert above button
        const insertAboveBtn = document.createElement('button');
        insertAboveBtn.className = 'edit-btn';
        insertAboveBtn.textContent = '⊕↑';
        insertAboveBtn.title = 'Insert passage above';
        insertAboveBtn.onclick = () => insertPassage(index, 'above');

        // Insert below button
        const insertBelowBtn = document.createElement('button');
        insertBelowBtn.className = 'edit-btn';
        insertBelowBtn.textContent = '⊕↓';
        insertBelowBtn.title = 'Insert passage below';
        insertBelowBtn.onclick = () => insertPassage(index, 'below');

        // Delete button
        const deleteBtn = document.createElement('button');
        deleteBtn.className = 'edit-btn delete';
        deleteBtn.textContent = '×';
        deleteBtn.title = 'Delete passage';
        deleteBtn.onclick = () => deletePassage(index);

        buttonContainer.appendChild(upBtn);
        buttonContainer.appendChild(downBtn);
        buttonContainer.appendChild(insertAboveBtn);
        buttonContainer.appendChild(insertBelowBtn);
        buttonContainer.appendChild(deleteBtn);

        ref.appendChild(buttonContainer);
    });
}

// Disable editing and save changes back to passages array
function disableEditing() {
    // Save and disable verse text editing
    const verseTexts = document.querySelectorAll('.verse-text');
    verseTexts.forEach((text, index) => {
        text.contentEditable = 'false';
        text.style.outline = 'none';

        // Save the edited HTML content back to the passages array
        passages[index].text = text.innerHTML;
    });

    // Save and disable verse reference editing
    const verseRefs = document.querySelectorAll('.verse-ref');
    verseRefs.forEach((ref, index) => {
        ref.contentEditable = 'false';
        ref.style.outline = 'none';

        // Extract text without buttons
        const buttons = ref.querySelector('.edit-buttons');
        const refText = buttons ? ref.childNodes[0].textContent : ref.textContent;

        // Save the edited reference back to the passages array
        passages[index].ref = refText.trim();

        // Remove edit buttons
        if (buttons) {
            buttons.remove();
        }
    });

    // Auto-save to file if a file is currently loaded
    if (currentFileName) {
        savePassageFile();
    }
}

// Apply "words of Christ" styling to selected text
function applyChristWordsStyle() {
    const selection = window.getSelection();

    if (!selection.rangeCount || selection.isCollapsed) {
        return; // No text selected
    }

    const range = selection.getRangeAt(0);

    // Check if selection is within a verse-text element
    let container = range.commonAncestorContainer;
    if (container.nodeType === Node.TEXT_NODE) {
        container = container.parentNode;
    }

    const verseText = container.closest('.verse-text');
    if (!verseText) {
        return; // Selection not in a verse
    }

    // Wrap selected text in a span with the words-of-christ class
    const span = document.createElement('span');
    span.className = 'words-of-christ';

    try {
        range.surroundContents(span);
    } catch (e) {
        // If surroundContents fails (complex selection), use extractContents
        const contents = range.extractContents();
        span.appendChild(contents);
        range.insertNode(span);
    }

    // Clear selection
    selection.removeAllRanges();

    // Save changes to passages array
    const verseIndex = Array.from(document.querySelectorAll('.verse-text')).indexOf(verseText);
    if (verseIndex !== -1) {
        passages[verseIndex].text = verseText.innerHTML;
    }
}

// Move passage up in the list
function movePassageUp(index) {
    if (index === 0) return; // Already at top

    // Swap with previous passage
    [passages[index - 1], passages[index]] = [passages[index], passages[index - 1]];

    // Update currentIndex if needed
    if (currentIndex === index) {
        currentIndex--;
    } else if (currentIndex === index - 1) {
        currentIndex++;
    }

    renderVerses();
}

// Move passage down in the list
function movePassageDown(index) {
    if (index === passages.length - 1) return; // Already at bottom

    // Swap with next passage
    [passages[index], passages[index + 1]] = [passages[index + 1], passages[index]];

    // Update currentIndex if needed
    if (currentIndex === index) {
        currentIndex++;
    } else if (currentIndex === index + 1) {
        currentIndex--;
    }

    renderVerses();
}

// Insert a new passage
function insertPassage(index, position) {
    const newPassage = {
        ref: "Reference",
        text: "Verse text here..."
    };

    const insertIndex = position === 'above' ? index : index + 1;
    passages.splice(insertIndex, 0, newPassage);

    // Update currentIndex if needed
    if (currentIndex >= insertIndex) {
        currentIndex++;
    }

    renderVerses();
}

// Delete a passage
function deletePassage(index) {
    if (passages.length === 1) {
        alert("Cannot delete the last passage.");
        return;
    }

    if (confirm("Are you sure you want to delete this passage?")) {
        passages.splice(index, 1);

        // Update currentIndex if needed
        if (currentIndex >= passages.length) {
            currentIndex = passages.length - 1;
        } else if (currentIndex > index) {
            currentIndex--;
        }

        renderVerses();
    }
}

// File Browser Functions
// ======================

// Initialize file browser
function initFileBrowser() {
    const closeBtn = document.getElementById('close-file-browser');
    if (closeBtn) {
        closeBtn.addEventListener('click', toggleFileBrowser);
    }
}

// Toggle file browser visibility
function toggleFileBrowser() {
    isFileBrowserOpen = !isFileBrowserOpen;
    const fileBrowser = document.getElementById('file-browser');

    if (isFileBrowserOpen) {
        fileBrowser.classList.remove('hidden');
        loadFileList();
    } else {
        fileBrowser.classList.add('hidden');
    }
}

// Load list of available passage files from server
async function loadFileList() {
    const fileListContainer = document.getElementById('file-list');

    try {
        const response = await fetch('/api/passages');
        const data = await response.json();

        if (data.files && data.files.length > 0) {
            fileListContainer.innerHTML = '';
            data.files.forEach(filename => {
                const fileItem = document.createElement('div');
                fileItem.className = 'file-item';
                if (filename === currentFileName) {
                    fileItem.classList.add('active');
                }

                const fileLink = document.createElement('a');
                fileLink.href = '#';
                fileLink.textContent = filename;
                fileLink.addEventListener('click', (e) => {
                    e.preventDefault();
                    loadPassageFile(filename);
                });

                fileItem.appendChild(fileLink);
                fileListContainer.appendChild(fileItem);
            });
        } else {
            fileListContainer.innerHTML = '<p class="no-files">No passage files found.</p>';
        }
    } catch (error) {
        console.error('Error loading file list:', error);
        fileListContainer.innerHTML = '<p class="error">Failed to load files. Is the server running?</p>';
    }
}

// Load a specific passage file
async function loadPassageFile(filename) {
    try {
        const response = await fetch(`/api/passages/${filename}`);
        const data = await response.json();

        if (Array.isArray(data)) {
            // Old format: just an array of passages
            passages.length = 0;
            passages.push(...data);
            media.length = 0;
        }
        else if (data.passages) {
            // Check if it's wrapped by the server
            if (data.passages.passages && Array.isArray(data.passages.passages)) {
                // Server wrapper format
                passages.length = 0;
                passages.push(...data.passages.passages);
                media.length = 0;
                if (data.passages.media && Array.isArray(data.passages.media)) {
                    media.push(...data.passages.media);
                }
            }
            else if (Array.isArray(data.passages)) {
                // Direct format with passages array.
                passages.length = 0;
                passages.push(...data.passages);
                media.length = 0;
                if (data.media && Array.isArray(data.media)) {
                    media.push(...data.media)
                }
            }
        }

        // Update UI
        currentFileName = filename;
        currentIndex = 0;
        currentMediaIndex = 0;
        isPartiallyScrolled = false;
        presentationMode = 'scripture';

        // Make sure we're showing scripture mode.
        const versesContainer = document.getElementById('verses-container');
        const mediaContainer = document.getElementById('media-container')
        versesContainer.style.display = 'block';
        versesContainer.style.opacity = '' // Clear inline styles to let CSS take over.
        mediaContainer.style.display = 'none';

        renderVerses();
        updateCurrentFileName();

        // Close the file browser.
        toggleFileBrowser();
    } catch (error) {
        console.error('Error loading passage file:', error);
        alert('Failed to load passage file.');
    }
}

// Save current passages to file
async function savePassageFile() {
    if (!currentFileName) {
        alert('No file currently loaded. Cannot save.');
        return;
    }

    try {
        const response = await fetch(`/api/passages/${currentFileName}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ passages, media })
        });

        const data = await response.json();

        if (data.success) {
            console.log('Saved passages to', currentFileName);
        } else {
            throw new Error('Save failed');
        }
    } catch (error) {
        console.error('Error saving passage file:', error);
        alert('Failed to save passage file.');
    }
}

// Update current filename display
function updateCurrentFileName() {
    const currentFileDisplay = document.getElementById('current-file-name');
    if (currentFileDisplay) {
        currentFileDisplay.textContent = currentFileName || 'None (using default passages)';
    }
}

// Initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}
