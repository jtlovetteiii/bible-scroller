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

// Scroll engine tuning
const SCROLL_SPEED = 350;        // hold-to-scroll reading pace, pixels per second
const SCROLL_RAMP = 0.09;        // seconds; time constant for easing into/out of the reading pace
const SCROLL_BRAKE_DISTANCE = 60; // pixels over which hold-to-scroll glides to a stop at a passage edge
const PASSAGE_EDGE_MARGIN = 50;  // pixels of slack at a passage's top/bottom edge
const TRANSITION_MIN_MS = 700;   // Space: shortest passage-to-passage transition
const TRANSITION_MAX_MS = 1400;  // Space: longest passage-to-passage transition
const TRANSITION_MS_PER_PX = 0.5;

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
    window.addEventListener('blur', releaseScrollKeys);

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
                if (!scroller.heldDown) {
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
                if (!scroller.heldUp) {
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
        } else if (event.key === 'ArrowRight') {
            event.preventDefault();
            if (presentationMode === 'scripture') {
                jumpDownWithinPassage();
            }
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

// Scroll engine
// =============
// One requestAnimationFrame loop drives every scripture scroll: hold-to-scroll
// (↑/↓), passage-to-passage transitions (Space) and instant jumps (→).
// The position is tracked as a float rather than read back from scrollTop,
// which the browser rounds — reading it back each frame loses the fraction
// and makes the speed uneven.
const scroller = {
    pos: 0,             // current scroll position (float)
    velocity: 0,        // pixels per second; positive is down
    heldDown: false,
    heldUp: false,
    tween: null,        // { from, to, start, duration } for Space transitions
    anchor: 0,          // where the current passage was landed on; ↑ returns here
    frame: null,
    lastTimestamp: null
};

function getScrollContainer() {
    return document.getElementById('scroller-container');
}

function maxScroll() {
    const container = getScrollContainer();
    return container.scrollHeight - container.clientHeight;
}

// Write the engine's position to the page
function applyScrollPosition() {
    scroller.pos = Math.min(Math.max(scroller.pos, 0), maxScroll());
    getScrollContainer().scrollTop = scroller.pos;
}

// Pick up any scrolling done outside the engine (mouse wheel, scrollbar)
function syncScrollPosition() {
    const actual = getScrollContainer().scrollTop;
    if (Math.abs(actual - scroller.pos) > 1) {
        scroller.pos = actual;
    }
}

// Top and bottom of the current passage, in scroll coordinates
function getPassageBounds() {
    const container = getScrollContainer();
    const verse = document.getElementById(`verse-${currentIndex}`);
    if (!verse) return null;

    const containerTop = container.getBoundingClientRect().top;
    const verseRect = verse.getBoundingClientRect();
    const top = verseRect.top - containerTop + container.scrollTop;
    const bottom = verseRect.bottom - containerTop + container.scrollTop;

    return {
        min: Math.min(scroller.anchor, top + PASSAGE_EDGE_MARGIN),
        max: Math.max(scroller.anchor, bottom - container.clientHeight - PASSAGE_EDGE_MARGIN)
    };
}

function ensureScrollLoop() {
    if (scroller.frame === null) {
        scroller.lastTimestamp = null;
        scroller.frame = requestAnimationFrame(scrollFrame);
    }
}

function stopScrollLoop() {
    if (scroller.frame !== null) {
        cancelAnimationFrame(scroller.frame);
        scroller.frame = null;
    }
    scroller.velocity = 0;
    scroller.tween = null;
}

function easeInOutCubic(t) {
    return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
}

function scrollFrame(timestamp) {
    // Clamp the frame time so a dropped frame doesn't become a visible jump
    const dt = scroller.lastTimestamp === null ? 1 / 60 : Math.min((timestamp - scroller.lastTimestamp) / 1000, 0.05);
    scroller.lastTimestamp = timestamp;

    if (scroller.tween) {
        // Space: eased transition to the next passage
        const { from, to, start, duration } = scroller.tween;
        const t = Math.min((timestamp - (start ?? timestamp)) / duration, 1);
        if (start === null) scroller.tween.start = timestamp;
        scroller.pos = from + (to - from) * easeInOutCubic(t);
        applyScrollPosition();

        if (t >= 1) {
            scroller.tween = null;
            scroller.frame = null;
            return;
        }
    } else {
        // ↑/↓: ease toward the reading pace while held, and back to rest on release
        const direction = (scroller.heldDown ? 1 : 0) - (scroller.heldUp ? 1 : 0);
        const target = direction * SCROLL_SPEED;
        scroller.velocity += (target - scroller.velocity) * (1 - Math.exp(-dt / SCROLL_RAMP));

        // Glide to a stop at the passage edge instead of hitting it: cap the
        // speed so a constant deceleration lands exactly on the edge
        const bounds = getPassageBounds();
        if (bounds) {
            const brake = SCROLL_SPEED * SCROLL_SPEED / (2 * SCROLL_BRAKE_DISTANCE);
            if (scroller.velocity > 0) {
                const remaining = Math.max(bounds.max - scroller.pos, 0);
                scroller.velocity = Math.min(scroller.velocity, Math.sqrt(2 * brake * remaining));
                scroller.pos = Math.min(scroller.pos + scroller.velocity * dt, Math.max(bounds.max, scroller.pos));
            } else if (scroller.velocity < 0) {
                const remaining = Math.max(scroller.pos - bounds.min, 0);
                scroller.velocity = Math.max(scroller.velocity, -Math.sqrt(2 * brake * remaining));
                scroller.pos = Math.max(scroller.pos + scroller.velocity * dt, Math.min(bounds.min, scroller.pos));
            }
        } else {
            scroller.pos += scroller.velocity * dt;
        }
        applyScrollPosition();

        // Back at the top of the passage: drop the sticky reference
        if (scroller.heldUp && bounds && scroller.pos - bounds.min < 1) {
            hideStickyReference();
            hideScrollGradient();
            isPartiallyScrolled = false;
        }

        if (direction === 0 && Math.abs(scroller.velocity) < 1) {
            scroller.velocity = 0;
            scroller.frame = null;
            return;
        }
    }

    scroller.frame = requestAnimationFrame(scrollFrame);
}

// Start continuous scroll down (hold Down arrow)
function startScrollDown() {
    if (scroller.tween) return; // let a passage transition finish first
    syncScrollPosition();
    scroller.heldDown = true;

    // A passage that already fits on screen has nowhere to scroll, so its
    // reference is still visible and the sticky header would just repeat it
    const bounds = getPassageBounds();
    if (bounds && bounds.max - scroller.pos > 1) {
        isPartiallyScrolled = true;
        showStickyReference();
        showScrollGradient();
    }
    ensureScrollLoop();
}

function stopScrollDown() {
    scroller.heldDown = false;
}

// Start continuous scroll up (hold Up arrow)
function startScrollUp() {
    if (scroller.tween) return;
    syncScrollPosition();
    scroller.heldUp = true;
    ensureScrollLoop();
}

function stopScrollUp() {
    scroller.heldUp = false;
}

// Release held keys, e.g. when the window loses focus and keyup never arrives
function releaseScrollKeys() {
    stopScrollDown();
    stopScrollUp();
}

// Jump down within current passage (instant, not smooth)
function jumpDownWithinPassage() {
    stopScrollLoop();
    syncScrollPosition();

    const bounds = getPassageBounds();
    if (!bounds) return;

    // Jump 40% of the viewport (roughly 6-8 lines), but not past the passage end
    const jumpAmount = getScrollContainer().clientHeight * 0.40;
    const remaining = bounds.max + PASSAGE_EDGE_MARGIN - scroller.pos;
    if (remaining <= 10) return;

    scroller.pos += Math.min(jumpAmount, remaining - 10);
    applyScrollPosition();

    // Mark as partially scrolled and show sticky reference
    isPartiallyScrolled = true;
    showStickyReference();
    showScrollGradient();
}

// Scroll to a specific verse (between-passage transition)
function scrollToVerse(index, instant=false) {
    const verse = document.getElementById(`verse-${index}`);
    if (!verse) return;

    const container = getScrollContainer();
    syncScrollPosition();

    // Short passages (200 characters or less) are centered; longer ones start at the top
    const plainText = passages[index].text.replace(/<[^>]*>/g, '');
    const isShortPassage = plainText.length <= 200;

    const verseTop = verse.getBoundingClientRect().top - container.getBoundingClientRect().top + container.scrollTop;
    const target = isShortPassage
        ? verseTop + verse.offsetHeight / 2 - container.clientHeight / 2
        : verseTop;
    const to = Math.min(Math.max(target, 0), maxScroll());

    scroller.anchor = to;
    scroller.heldDown = false;
    scroller.heldUp = false;

    if (instant) {
        stopScrollLoop();
        scroller.pos = to;
        applyScrollPosition();
        return;
    }

    const distance = Math.abs(to - scroller.pos);
    const duration = Math.min(Math.max(distance * TRANSITION_MS_PER_PX + 400, TRANSITION_MIN_MS), TRANSITION_MAX_MS);
    scroller.velocity = 0;
    scroller.tween = { from: scroller.pos, to, start: null, duration };
    ensureScrollLoop();
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
    if (media.length === 0) {
        // No media available, can't switch to media mode
        return;
    }

    if (presentationMode === 'scripture') {
        presentationMode = 'media';
        showMediaMode();
    } else {
        presentationMode = 'scripture';
        showScriptureMode();
    }
}

// Scripture <-> media transitions ("Settle")
// =========================================
// The outgoing layer clears before the incoming one arrives, so a slide title
// never sits on top of scripture text: the text lifts and fades, then the
// slide settles in from a slight zoom (and the reverse on the way back).
// Built on the Web Animations API so a transition can be interrupted (M
// pressed again mid-way) and the next one starts from what is on screen.
const TEXT_OUT_MS = 450;
const SLIDE_IN_MS = 1100;
const SLIDE_OUT_MS = 550;
const TEXT_IN_MS = 900;
const EASE_LEAVE = 'cubic-bezier(.4, 0, 1, 1)';
const EASE_ARRIVE = 'cubic-bezier(.16, .84, .3, 1)';
// Resting states of the hidden layers, so the next transition starts from them
const TEXT_HIDDEN_TRANSFORM = 'translateY(2vh)';
const SLIDE_HIDDEN_TRANSFORM = 'scale(1.04)';

let modeAnimations = [];

// Freeze any in-flight mode transition where it is
function settleModeAnimations() {
    modeAnimations.forEach(animation => {
        try {
            animation.commitStyles();
        } catch (e) {
            // Element isn't rendered (display: none); nothing to keep
        }
        animation.cancel();
    });
    modeAnimations = [];
}

// Run [element, keyframes, options] steps together, then call onDone unless a
// newer transition has taken over. Keyframes give only the end state; each
// animation starts from the element's current look.
function runModeTransition(steps, onDone) {
    const animations = steps.map(([element, keyframes, options]) =>
        element.animate(keyframes, { fill: 'both', ...options })
    );
    modeAnimations = animations;

    Promise.all(animations.map(animation => animation.finished))
        .then(() => {
            if (modeAnimations !== animations) return;
            settleModeAnimations();
            onDone();
        })
        .catch(() => {
            // Cancelled by a newer transition
        });
}

function visibleOpacity(element) {
    return element.style.display === 'none' ? 0 : parseFloat(getComputedStyle(element).opacity);
}

// Show media mode (text lifts away, then the slide settles in)
function showMediaMode() {
    const versesContainer = document.getElementById('verses-container');
    const mediaContainer = document.getElementById('media-container');

    stopScrollLoop();
    releaseScrollKeys();
    settleModeAnimations();

    // Hide sticky reference and scroll gradient if visible
    document.getElementById('sticky-reference').classList.add('hidden');
    document.getElementById('scroll-gradient').classList.add('hidden');

    mediaContainer.style.display = 'flex';
    renderCurrentMedia();

    // Wait only as long as the text actually takes to clear
    const textDelay = TEXT_OUT_MS * visibleOpacity(versesContainer);

    runModeTransition([
        [versesContainer, [{ opacity: 0, transform: 'translateY(-2vh)' }], { duration: TEXT_OUT_MS, easing: EASE_LEAVE }],
        [mediaContainer, [{ opacity: 1, transform: 'scale(1)' }], { duration: SLIDE_IN_MS, delay: textDelay, easing: EASE_ARRIVE }]
    ], () => {
        versesContainer.style.display = 'none';
        versesContainer.style.transform = TEXT_HIDDEN_TRANSFORM;
    });
}

// Show scripture mode (slide clears, then the text rises into place)
function showScriptureMode() {
    const versesContainer = document.getElementById('verses-container');
    const mediaContainer = document.getElementById('media-container');

    settleModeAnimations();

    versesContainer.style.display = 'block';

    // Scroll to the current verse immediately (before the text appears)
    scrollToVerse(currentIndex, true);

    const slideDelay = SLIDE_OUT_MS * visibleOpacity(mediaContainer);

    runModeTransition([
        [mediaContainer, [{ opacity: 0, transform: 'scale(1.02)' }], { duration: SLIDE_OUT_MS, easing: EASE_LEAVE }],
        [versesContainer, [{ opacity: isBlanked ? 0.05 : 1, transform: 'translateY(0)' }], { duration: TEXT_IN_MS, delay: slideDelay, easing: EASE_ARRIVE }]
    ], () => {
        mediaContainer.style.display = 'none';
        mediaContainer.style.transform = SLIDE_HIDDEN_TRANSFORM;
        // Clear inline styles to let CSS classes (like .blanked) control the text
        versesContainer.style.opacity = '';
        versesContainer.style.transform = '';
    });
}

// Put both layers back in their scripture-mode resting state, no animation
function resetModeLayers() {
    settleModeAnimations();
    const versesContainer = document.getElementById('verses-container');
    const mediaContainer = document.getElementById('media-container');
    versesContainer.style.display = 'block';
    versesContainer.style.opacity = '';
    versesContainer.style.transform = '';
    mediaContainer.style.display = 'none';
    mediaContainer.style.opacity = '';
    mediaContainer.style.transform = '';
}

// Decode every slide up front so no transition waits on an image load
let preloadedMedia = [];
function preloadMedia() {
    preloadedMedia = media.map(item => {
        const img = new Image();
        img.src = `passages/${item.src}`;
        img.decode().catch(() => console.error('Failed to load image:', img.src));
        return img;
    });
}

function createMediaImage(item) {
    const img = document.createElement('img');
    img.src = `passages/${item.src}`;
    img.alt = item.alt || '';
    img.className = 'media-image active';
    return img;
}

// Render the current media item
function renderCurrentMedia() {
    const mediaContainer = document.getElementById('media-container');

    if (currentMediaIndex < 0 || currentMediaIndex >= media.length) {
        mediaContainer.innerHTML = '<div class="media-error">No media available</div>';
        return;
    }

    mediaContainer.innerHTML = '';
    mediaContainer.appendChild(createMediaImage(media[currentMediaIndex]));
}

// Crossfade to the current media item. Kept a plain crossfade on purpose:
// consecutive slides usually share a background and differ by one line of
// text, so only the new line visibly changes.
let mediaFadeRequest = 0;
function fadeToNextMedia() {
    const mediaContainer = document.getElementById('media-container');

    if (!mediaContainer.querySelector('.media-image')) {
        renderCurrentMedia();
        return;
    }

    const request = ++mediaFadeRequest;
    const newImg = createMediaImage(media[currentMediaIndex]);

    const show = () => {
        // A later key press already moved on; skip this slide
        if (request !== mediaFadeRequest) return;

        mediaContainer.appendChild(newImg);
        newImg.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 600, easing: 'ease-in-out' })
            .finished
            .then(() => {
                // Drop the slides now hidden underneath
                while (newImg.previousElementSibling) {
                    newImg.previousElementSibling.remove();
                }
            })
            .catch(() => {});
    };

    newImg.decode().then(show, () => {
        console.error('Failed to load image:', newImg.src);
        show();
    });
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
        resetModeLayers();
        preloadMedia();

        renderVerses();
        scrollToVerse(0, true);
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
