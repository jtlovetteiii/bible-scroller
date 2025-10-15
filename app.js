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

let currentIndex = 0;
let isPartiallyScrolled = false; // Track if we're mid-passage
let isBlanked = false; // Track if content is blanked (bookmark mode)
let stickyWasVisible = false; // Track sticky reference state before blanking
let isLightTheme = false; // Track current theme state

// Initialize the scroller
function init() {
    const container = document.getElementById('verses-container');

    // Create verse sections
    passages.forEach((passage, index) => {
        const section = document.createElement('div');
        section.className = 'verse-section';
        section.id = `verse-${index}`;

        if (index === 0) {
            section.classList.add('active');
        } else {
            section.classList.add('upcoming');
        }

        const ref = document.createElement('div');
        ref.className = 'verse-ref';
        ref.textContent = passage.ref;

        const text = document.createElement('div');
        text.className = 'verse-text';
        text.textContent = passage.text;

        section.appendChild(ref);
        section.appendChild(text);
        container.appendChild(section);
    });

    // Set up keyboard navigation
    document.addEventListener('keydown', handleKeyPress);

    // Hide controls hint after a few seconds
    setTimeout(() => {
        const hint = document.getElementById('controls-hint');
        hint.style.opacity = '0';
    }, 5000);
}

// Handle keyboard navigation
function handleKeyPress(event) {
    if (event.key === ' ' || event.key === 'ArrowDown') {
        event.preventDefault();
        navigateNext();
    } else if (event.key === 'ArrowUp') {
        event.preventDefault();
        navigatePrevious();
    } else if (event.key === 'b' || event.key === 'B') {
        event.preventDefault();
        toggleBlank();
    } else if (event.key === 't' || event.key === 'T') {
        event.preventDefault();
        toggleTheme();
    }
}

// Navigate to next verse or scroll within current passage
function navigateNext() {
    const currentVerse = document.getElementById(`verse-${currentIndex}`);
    const scrollContainer = document.getElementById('scroller-container');

    if (!currentVerse) return;

    // Check if there's more content below the viewport in the current verse
    const verseRect = currentVerse.getBoundingClientRect();
    const containerRect = scrollContainer.getBoundingClientRect();
    const verseBottom = verseRect.bottom;
    const viewportBottom = containerRect.bottom;

    // If verse extends below viewport (with some buffer), do a partial scroll
    if (verseBottom > viewportBottom + 50) {
        // Partial scroll: move down 75% of viewport height
        partialScrollDown();
        isPartiallyScrolled = true;
    } else {
        // Full transition to next verse
        if (currentIndex < passages.length - 1) {
            currentIndex++;
            isPartiallyScrolled = false;
            scrollToVerse(currentIndex);
            updateVerseStates();
        }
    }
}

// Navigate to previous verse or scroll back within current passage
function navigatePrevious() {
    const currentVerse = document.getElementById(`verse-${currentIndex}`);
    const scrollContainer = document.getElementById('scroller-container');

    if (!currentVerse) return;

    // Check if the verse top is above the viewport
    const verseRect = currentVerse.getBoundingClientRect();
    const containerRect = scrollContainer.getBoundingClientRect();
    const verseTop = verseRect.top;
    const viewportTop = containerRect.top;

    // If we're partially scrolled or verse extends above viewport, scroll back up
    if (isPartiallyScrolled || verseTop < viewportTop - 50) {
        partialScrollUp();

        // Check if we're now back at the top of the current verse
        setTimeout(() => {
            const updatedRect = currentVerse.getBoundingClientRect();
            if (Math.abs(updatedRect.top - containerRect.top) < 100) {
                isPartiallyScrolled = false;
            }
        }, 600);
    } else {
        // Full transition to previous verse
        if (currentIndex > 0) {
            currentIndex--;
            isPartiallyScrolled = false;
            scrollToVerse(currentIndex);
            updateVerseStates();
        }
    }
}

// Partial scroll down within current passage (slower, keeps context)
function partialScrollDown() {
    const scrollContainer = document.getElementById('scroller-container');
    const scrollAmount = window.innerHeight * 0.6; // 75% of viewport

    scrollContainer.scrollBy({
        top: scrollAmount,
        behavior: 'smooth'
    });

    // Show sticky reference and gradient when scrolling within passage
    showStickyReference();
    showScrollGradient();
}

// Partial scroll up within current passage
function partialScrollUp() {
    const scrollContainer = document.getElementById('scroller-container');
    const scrollAmount = window.innerHeight * 0.6; // 75% of viewport

    scrollContainer.scrollBy({
        top: -scrollAmount,
        behavior: 'smooth'
    });

    // Check if we should hide sticky reference and gradient after scrolling back up
    setTimeout(() => {
        const currentVerse = document.getElementById(`verse-${currentIndex}`);
        const containerRect = scrollContainer.getBoundingClientRect();
        const verseRect = currentVerse.getBoundingClientRect();

        // If we're back at the top of the verse, hide sticky reference and gradient
        if (Math.abs(verseRect.top - containerRect.top) < 100) {
            hideStickyReference();
            hideScrollGradient();
        }
    }, 600);
}

// Scroll to a specific verse (between-passage transition)
function scrollToVerse(index) {
    const verse = document.getElementById(`verse-${index}`);
    if (verse) {
        verse.scrollIntoView({
            behavior: 'smooth',
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

// Initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}
