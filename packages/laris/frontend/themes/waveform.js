// Waveform archetype - circular spectrum analyzer (approved 2026-07-16).
// Hot core, radial bars with ghost afterglow, dashed tech ring, thin outer
// ring, glitch displacement. No radar sweep (explicitly rejected).
(function () {
  window.ORB_THEMES = window.ORB_THEMES || {};

  window.ORB_THEMES.waveform = function create(wrap, size) {
    const canvas = document.createElement("canvas");
    canvas.width = size; canvas.height = size;
    wrap.appendChild(canvas);
    const ctx = canvas.getContext("2d");
    const rgba = window.ORB_UTIL.rgba;

    const C = size / 2, S = size / 280;
    const N = size < 160 ? 40 : 56;
    const bands = new Array(N).fill(0);
    const ghosts = [new Array(N).fill(0), new Array(N).fill(0)];
    let ghostClock = 0;

    // Gradient cache by quantized energy, accent, dim
    const gradientCache = new Map();

    function draw(s, pal) {
      ctx.clearRect(0, 0, size, size);
      const dim = s.active ? 1 : 0.75;
      const R0 = 62 * S;
      const glitchShift = s.glitch ? (Math.random() - 0.5) * 4 * S : 0;

      const coreR = (6 + s.v * 4) * S;
      const quantV = Math.round(s.v * 15);
      const cacheKey = `${quantV}|${pal.accent}|${pal.hot}|${dim}`;

      let g;
      if (gradientCache.has(cacheKey)) {
        g = gradientCache.get(cacheKey);
      } else {
        g = ctx.createRadialGradient(C, C, 1, C, C, coreR * 3.2);
        g.addColorStop(0, rgba(pal.hot, 0.95 * dim + s.v * 0.05));
        g.addColorStop(0.4, rgba(pal.accent, 0.30 * dim + s.v * 0.25));
        g.addColorStop(1, rgba(pal.accent, 0));
        gradientCache.set(cacheKey, g);
      }
      ctx.fillStyle = g;
      ctx.beginPath(); ctx.arc(C, C, coreR * 3.2, 0, 7); ctx.fill();

      ctx.setLineDash([3 * S, 5 * S]);
      ctx.beginPath(); ctx.arc(C, C, 46 * S + s.v * 3 * S, 0, 7);
      ctx.strokeStyle = rgba(pal.accent, 0.5 * dim); ctx.lineWidth = 1.3; ctx.stroke();
      ctx.setLineDash([]);

      ghostClock++;
      if (ghostClock % 5 === 0) { ghosts[1] = ghosts[0].slice(); ghosts[0] = bands.slice(); }

      for (let i = 0; i < N; i++) {
        const band = Math.abs(Math.sin(i * 0.55 + s.t * 3.1) * Math.sin(i * 0.13 + s.t * 1.7));
        const target = s.active ? s.v * band : 0.03 * Math.abs(Math.sin(i + s.t));
        bands[i] += (target - bands[i]) * (target > bands[i] ? 0.5 : 0.12);
        const ang = -Math.PI / 2 + (i / N) * Math.PI * 2;
        const cos = Math.cos(ang), sin = Math.sin(ang);
        for (let layer = 1; layer >= 0; layer--) {
          const val = layer === 0 ? bands[i] : ghosts[layer][i];
          if (layer > 0 && val < 0.02) continue;
          const h = (4 + val * 46) * S;
          ctx.beginPath();
          ctx.moveTo(C + cos * R0 + (layer ? 0 : glitchShift), C + sin * R0);
          ctx.lineTo(C + cos * (R0 + h) + (layer ? 0 : glitchShift), C + sin * (R0 + h));
          ctx.strokeStyle = layer === 0
            ? rgba(val > 0.55 ? pal.hot : pal.accent, (0.60 + val * 0.40) * dim)
            : rgba(pal.accent, 0.18 * dim);
          ctx.lineWidth = 3 * S * (size < 160 ? 1.35 : 1);
          ctx.stroke();
        }
      }

      ctx.beginPath(); ctx.arc(C, C, 124 * S, 0, 7);
      ctx.strokeStyle = rgba(pal.accent, 0.30 * dim + s.v * 0.25);
      ctx.lineWidth = 1.2; ctx.stroke();
      if (s.glitch) {
        const a0 = Math.random() * 7;
        ctx.beginPath(); ctx.arc(C + 3 * S, C, 124 * S, a0, a0 + 0.5);
        ctx.strokeStyle = rgba(pal.hot, 0.7); ctx.lineWidth = 1.4; ctx.stroke();
      }
    }

    return {
      draw,
      dispose() {
        canvas.remove();
        gradientCache.clear();
      }
    };
  };
})();
