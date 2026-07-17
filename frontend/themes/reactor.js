// Reactor archetype - concentric HUD arcs (screen-2 candidate A).
// Sharp core, 48-tick radial gauge lit by voice, three mechanical sweeps,
// fixed outer ring with cardinal ticks. Brightness hierarchy only.
(function () {
  window.ORB_THEMES = window.ORB_THEMES || {};

  window.ORB_THEMES.reactor = function create(wrap, size) {
    const canvas = document.createElement("canvas");
    canvas.width = size; canvas.height = size;
    wrap.appendChild(canvas);
    const ctx = canvas.getContext("2d");
    const rgba = window.ORB_UTIL.rgba;
    const C = size / 2, S = size / 300;

    function arc(pal, r, a0, a1, w, alpha) {
      ctx.beginPath(); ctx.arc(C, C, r * S, a0, a1);
      ctx.strokeStyle = rgba(pal.accent, alpha); ctx.lineWidth = w; ctx.stroke();
    }

    function draw(s, pal) {
      ctx.clearRect(0, 0, size, size);
      const dim = s.active ? 1 : 0.6;

      const coreR = (16 + s.v * 7) * S;
      const g = ctx.createRadialGradient(C, C, 2, C, C, coreR * 2.2);
      g.addColorStop(0, rgba(pal.hot, 0.75 * dim + s.v * 0.25));
      g.addColorStop(0.35, rgba(pal.accent, 0.35 * dim + s.v * 0.3));
      g.addColorStop(1, rgba(pal.accent, 0));
      ctx.fillStyle = g;
      ctx.beginPath(); ctx.arc(C, C, coreR * 2.2, 0, 7); ctx.fill();

      const lit = Math.round(48 * Math.min(1, s.v * 1.4));
      for (let i = 0; i < 48; i++) {
        const ang = -Math.PI / 2 + (i / 48) * Math.PI * 2;
        const on = s.active && i < lit;
        ctx.beginPath();
        ctx.moveTo(C + Math.cos(ang) * 46 * S, C + Math.sin(ang) * 46 * S);
        ctx.lineTo(C + Math.cos(ang) * (on ? 58 : 52) * S, C + Math.sin(ang) * (on ? 58 : 52) * S);
        ctx.strokeStyle = rgba(pal.accent, on ? 0.95 : 0.18 * dim);
        ctx.lineWidth = on ? 2.2 : 1; ctx.stroke();
      }

      const sweeps = [
        { r: 76, len: 1.1 + s.v * 1.2, speed: 0.9, w: 3, a: 0.7 },
        { r: 88, len: 0.5 + s.v * 0.8, speed: -1.4, w: 2, a: 0.5 },
        { r: 97, len: 1.9, speed: 0.35, w: 1.2, a: 0.32 },
      ];
      for (const sw of sweeps) {
        const base = s.t * sw.speed;
        arc(pal, sw.r, base, base + sw.len, sw.w, sw.a * dim + s.v * 0.2);
      }

      arc(pal, 112, 0, 7, 1, 0.22 * dim);
      for (let i = 0; i < 8; i++) {
        const ang = (i / 8) * Math.PI * 2 + Math.PI / 8;
        ctx.beginPath();
        ctx.moveTo(C + Math.cos(ang) * 108 * S, C + Math.sin(ang) * 108 * S);
        ctx.lineTo(C + Math.cos(ang) * 117 * S, C + Math.sin(ang) * 117 * S);
        ctx.strokeStyle = rgba(pal.accent, 0.4 * dim + s.v * 0.3);
        ctx.lineWidth = 1.6; ctx.stroke();
      }
    }

    return { draw, dispose() { canvas.remove(); } };
  };
})();
