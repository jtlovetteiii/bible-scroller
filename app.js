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
    }
}

// Navigate to next verse
function navigateNext() {
    if (currentIndex < passages.length - 1) {
        currentIndex++;
        scrollToVerse(currentIndex);
        updateVerseStates();
    }
}

// Navigate to previous verse
function navigatePrevious() {
    if (currentIndex > 0) {
        currentIndex--;
        scrollToVerse(currentIndex);
        updateVerseStates();
    }
}

// Scroll to a specific verse
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
}

// Initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}
