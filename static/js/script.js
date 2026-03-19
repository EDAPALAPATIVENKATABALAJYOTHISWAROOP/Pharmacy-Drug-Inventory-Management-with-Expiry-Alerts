// script.js — PharmacySystem Frontend JavaScript

$(document).ready(function () {

    // ── Auto-dismiss flash messages after 4 seconds ──
    setTimeout(function () {
        $('.alert').fadeOut(500, function() {
            $(this).remove();
        });
    }, 4000);

    // ── Dark / Light Mode Toggle ──
    const $toggle = $('#darkModeToggle');
    if ($toggle.length) {
        // Apply saved preference on load
        if (localStorage.getItem('theme') === 'dark') {
            $('body').addClass('dark-mode');
            $toggle.text('☀️');
        } else {
            $toggle.text('🌙');
        }

        // Toggle on click
        $toggle.on('click', function () {
            $('body').toggleClass('dark-mode');
            const isDark = $('body').hasClass('dark-mode');
            $(this).text(isDark ? '☀️' : '🌙');
            localStorage.setItem('theme', isDark ? 'dark' : 'light');
        });
    }

});

