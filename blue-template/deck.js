(function () {
var slides = document.querySelectorAll('.slide');
var idx = 0;
var cur = document.getElementById('cur');
var total = document.getElementById('total');
total.textContent = slides.length;
function show(i) {
idx = (i + slides.length) % slides.length;
slides.forEach(function (s, k) { s.classList.toggle('is-active', k === idx); });
cur.textContent = idx + 1;
try { history.replaceState(null, '', '#' + (idx + 1)); } catch (e) {}
}
document.getElementById('prev').addEventListener('click', function () { show(idx - 1); });
document.getElementById('next').addEventListener('click', function () { show(idx + 1); });
document.addEventListener('keydown', function (e) {
if (e.key === 'ArrowRight' || e.key === 'PageDown' || e.key === ' ') { show(idx + 1); e.preventDefault(); }
else if (e.key === 'ArrowLeft' || e.key === 'PageUp') { show(idx - 1); e.preventDefault(); }
else if (e.key === 'Home') { show(0); }
else if (e.key === 'End') { show(slides.length - 1); }
});
document.querySelector('.stage').addEventListener('click', function (e) {
if (e.target.closest('.nav') || e.target.closest('a')) return;
var rect = e.currentTarget.getBoundingClientRect();
var x = e.clientX - rect.left;
if (x < rect.width / 2) show(idx - 1); else show(idx + 1);
});
function fit() {
var deck = document.getElementById('deck');
var w = window.innerWidth;
var h = window.innerHeight - 60;
var scale = Math.min(w / 1920, h / 1080);
deck.style.transform = 'scale(' + scale + ')';
}
window.addEventListener('resize', fit);
fit();
if (location.hash) {
var n = parseInt(location.hash.slice(1), 10);
if (!isNaN(n) && n >= 1 && n <= slides.length) show(n - 1);
}
})();
