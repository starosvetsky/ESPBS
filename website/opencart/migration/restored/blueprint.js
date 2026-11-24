(function () {
  'use strict';
  var drawings = document.querySelectorAll('[data-blueprint]');
  if (!drawings.length) return;
  var motion = window.matchMedia('(prefers-reduced-motion: reduce)');
  if (motion.matches || !('IntersectionObserver' in window)) return;
  var observer;
  function finish(drawing) {
    drawing.classList.remove('is-pending', 'is-playing');
    drawing.classList.add('is-complete');
  }
  try {
    observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        var drawing = entry.target;
        observer.unobserve(drawing);
        drawing.classList.remove('is-pending');
        drawing.classList.add('is-playing');
        // Remove animation styles after the final frame. No looping/timers remain.
        window.setTimeout(function () { finish(drawing); }, 4200);
      });
    }, { threshold: 0.25 });
    drawings.forEach(function (drawing) {
      drawing.classList.add('is-pending');
      observer.observe(drawing);
    });
    function reduce(event) {
      if (!event.matches) return;
      observer.disconnect();
      drawings.forEach(finish);
    }
    if (motion.addEventListener) motion.addEventListener('change', reduce);
  } catch (error) {
    if (observer) observer.disconnect();
    drawings.forEach(finish);
  }
}());
