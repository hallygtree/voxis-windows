(function () {
  const params = new URLSearchParams(window.location.search);
  const token = params.get("token");
  if (!token) return; // app.js already shows the "missing token" error

  const wrap = document.getElementById("orb-canvas-wrap");
  const caption = document.getElementById("phaseCaption");
  const ampFill = document.getElementById("ampFill");
  const fallback = document.getElementById("orb-fallback");

  let fallbackRemoved = false;
  function removeFallback() {
    if (fallbackRemoved) return;
    fallbackRemoved = true;
    if (fallback) fallback.classList.add("hide");
  }

  const PHASE_CAPTIONS = {
    recording: "ouvindo...",
    awaiting_project: "qual projeto?",
    awaiting_dictation: "pode ditar a mensagem...",
    awaiting_send: 'digitado - diga "manda" ou aperte enter',
  };

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
  // z=6: visible half-width = tan(22.5deg) * 6 = 1.242, so all rings/fragments
  // at radius <= 1.20 stay inside the canvas (no rectangular clip on desktop).
  camera.position.z = 6;

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  // explicit: inside the desktop overlay's transparent WKWebView an opaque
  // clear paints a dark tile behind the orb (invisible on the dark dashboard)
  renderer.setClearColor(0x000000, 0);
  renderer.setClearAlpha(0);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  wrap.appendChild(renderer.domElement);
  renderer.domElement.style.background = "transparent";

  function resize() {
    const size = wrap.clientWidth || 120;
    renderer.setSize(size, size);
    camera.aspect = 1;
    camera.updateProjectionMatrix();
  }

  const geo = new THREE.IcosahedronGeometry(1.8, 3);
  const baseVerts = geo.attributes.position.array.slice();

  const wireMat = new THREE.LineBasicMaterial({ color: 0x5adce1, transparent: true, opacity: 0.85 });
  const wireframe = new THREE.LineSegments(new THREE.WireframeGeometry(geo), wireMat);
  scene.add(wireframe);

  const fillMat = new THREE.MeshBasicMaterial({ color: 0x0d2a2c, transparent: true, opacity: 0.22 });
  const fill = new THREE.Mesh(geo, fillMat);
  scene.add(fill);

  const outerGlow = new THREE.Mesh(new THREE.IcosahedronGeometry(1.83, 2),
    new THREE.MeshBasicMaterial({ color: 0x5adce1, transparent: true, opacity: 0.04, side: THREE.BackSide, blending: THREE.AdditiveBlending }));
  scene.add(outerGlow);

  // --- JARVIS orbital rings + tick marks (B direction) ---
  // Scaled to fit within the 110px desktop canvas viewport: at z=3.2 with
  // 45deg FOV, half-visible = ~1.325. Keep all extras inside 1.25 to avoid
  // canvas-edge clipping that paints a visible rectangle on the desktop.
  function makeRing(radius, color, opacity, tickCount) {
    const group = new THREE.Group();
    const ring = new THREE.Mesh(
      new THREE.TorusGeometry(radius, 0.005, 4, 80),
      new THREE.MeshBasicMaterial({ color, transparent: true, opacity })
    );
    group.add(ring);
    if (tickCount > 0) {
      for (let j = 0; j < tickCount; j++) {
        const ang = (j / tickCount) * Math.PI * 2;
        const tickGeo = new THREE.BufferGeometry();
        tickGeo.setAttribute("position", new THREE.Float32BufferAttribute([
          Math.cos(ang) * (radius - 0.03), 0, Math.sin(ang) * (radius - 0.03),
          Math.cos(ang) * (radius + 0.04), 0, Math.sin(ang) * (radius + 0.04),
        ], 3));
        const tick = new THREE.LineSegments(tickGeo, new THREE.LineBasicMaterial({ color, transparent: true, opacity: opacity * 1.6 }));
        group.add(tick);
      }
    }
    return group;
  }

  const ring1 = makeRing(2.0, 0x5adce1, 0.35, 12);
  const ring2 = makeRing(2.1, 0xd95a9e, 0.28, 0);
  ring2.rotation.x = Math.PI / 2.5;
  const ring3 = makeRing(2.2, 0x5adce1, 0.22, 24);
  ring3.rotation.x = Math.PI / 3;
  ring3.rotation.z = Math.PI / 4;
  scene.add(ring1, ring2, ring3);

  // Fragments orbiting the orb (additive points, react to amplitude)
  const FRAG_COUNT = 26;
  const fragGeo = new THREE.BufferGeometry();
  const fragPos = new Float32Array(FRAG_COUNT * 3);
  const fragData = [];
  for (let i = 0; i < FRAG_COUNT; i++) {
    fragData.push({
      r: 1.85 + Math.random() * 0.3,
      a: Math.random() * Math.PI * 2,
      tilt: (Math.random() - 0.5) * 0.4,
      speed: 0.3 + Math.random() * 0.5,
      phase: Math.random() * Math.PI * 2,
    });
  }
  fragGeo.setAttribute("position", new THREE.BufferAttribute(fragPos, 3));
  const fragMat = new THREE.PointsMaterial({
    color: 0x5adce1, size: 0.03, transparent: true, opacity: 0.35,
    blending: THREE.AdditiveBlending, depthWrite: false,
  });
  const frags = new THREE.Points(fragGeo, fragMat);
  scene.add(frags);

  const cyan = new THREE.Color(0x5adce1), pink = new THREE.Color(0xd95a9e);

  function smoothNoise(x, y, z, time, freq) {
    return (Math.sin(x*freq+time*0.6)+Math.sin(y*freq*1.3+time*0.5+1.7)+Math.sin(z*freq*0.9+time*0.7+3.1)+Math.sin((x+y)*freq*0.6-time*0.4))/4;
  }
  function updateWireframe() {
    const newWire = new THREE.WireframeGeometry(geo);
    wireframe.geometry.dispose();
    wireframe.geometry = newWire;
  }

  // State-transition pop so the orb announces "now listening" sharply,
  // then settles into a calmer sustained envelope. Prevents the lazy fade-in
  // that made activation feel laggy.
  let activationPulse = 0;

  let active = false;
  let t = 0;
  let targetEnergy = 0;
  let smoothedVoice = 0;
  let idleFrameSkip = 0;

  function setPhase(phase) {
    const wasIdle = !active;
    active = phase !== "idle";
    if (wasIdle && active) activationPulse = 1.0; // snap to life on rising edge
    wrap.classList.toggle("active", active);
    const text = PHASE_CAPTIONS[phase];
    if (text) {
      caption.textContent = text;
      caption.classList.add("show");
    } else {
      caption.classList.remove("show");
    }
  }

  function animate() {
    requestAnimationFrame(animate);
    const settled = !active && smoothedVoice < 0.01;
    if (settled) {
      idleFrameSkip = (idleFrameSkip + 1) % 8;
      if (idleFrameSkip !== 0) return;
    } else {
      idleFrameSkip = 0;
    }
    t += 0.014;
    // Activation pulse: sharp pop on rising edge then fast exponential decay
    // so the orb "snaps" to life when recording begins, instead of fading in
    // lazily through smoothedVoice's slow-release ballistics.
    if (activationPulse > 0.001) activationPulse *= 0.88; else activationPulse = 0;
    // VU-meter ballistics: fast attack so the orb jumps with speech onsets,
    // slow release so it falls smoothly. Live ~25Hz mic events re-feed
    // targetEnergy while recording; the decay only matters once they stop.
    targetEnergy *= 0.96;
    const rate = targetEnergy > smoothedVoice ? 0.55 : 0.10;
    smoothedVoice += (targetEnergy - smoothedVoice) * rate;
    // Active is much more vivid now: stronger baseline, bigger amplitude swing,
    // plus the activation pulse stacked on top so speech onset deformation is
    // truly alive instead of a gentle wobble.
    const baseline = active ? 0.18 : 0.025;
    const energy = baseline + smoothedVoice * 0.95 + activationPulse * 0.6;
    const visualEnergy = Math.min(1.5, energy);
    ampFill.style.width = Math.min(100, visualEnergy*100) + '%';

    const pos = geo.attributes.position;
    // Idle: almost flat, just a whisper. Active: big wobble driven by voice.
    const freq = 1.1, ampVal = 0.03 + visualEnergy * 0.35;
    for (let i = 0; i < pos.count; i++) {
      const ix = i*3, bx=baseVerts[ix], by=baseVerts[ix+1], bz=baseVerts[ix+2];
      const len = Math.sqrt(bx*bx+by*by+bz*bz)||1, nx=bx/len, ny=by/len, nz=bz/len;
      const n = smoothNoise(nx,ny,nz,t,freq), d = 1+n*ampVal;
      pos.array[ix]=nx*d; pos.array[ix+1]=ny*d; pos.array[ix+2]=nz*d;
    }
    pos.needsUpdate = true; geo.computeVertexNormals(); updateWireframe();

    // Color shift is much snappier now: small energy already pushes pink.
    const mixT = Math.min(1, visualEnergy*1.5);
    const c = cyan.clone().lerp(pink, mixT);
    wireMat.color.copy(c); fillMat.color.copy(c.clone().multiplyScalar(0.25));
    // Tint the orbital rings + fragments in the same mixed color
    ring1.children.forEach(ch => ch.material.color.copy(c));
    ring2.children.forEach(ch => ch.material.color.copy(pink.clone().lerp(c, 0.3)));
    ring3.children.forEach(ch => ch.material.color.copy(c));
    fragMat.color.copy(c);

    // Rotation: idle = slow breath; active = driven by amplitude, never the
    // same velocity twice so it reads as "reacting" not as a fixed loop.
    const rotSpeed = active ? (1.2 + visualEnergy * 2.4) : 0.35;
    wireframe.rotation.y += 0.003*rotSpeed; fill.rotation.y = wireframe.rotation.y;
    wireframe.rotation.x = Math.sin(t*0.3)*0.08; fill.rotation.x = wireframe.rotation.x;

    // Orbital rings counter-rotate - reads as mechanical HUD, not a static halo
    ring1.rotation.y = t * (0.35 + visualEnergy * 0.6);
    ring2.rotation.y = -t * (0.45 + visualEnergy * 0.8);
    ring3.rotation.y = t * (0.25 + visualEnergy * 0.4);
    // Rings fade up only when active; stay invisible while idle
    const ringVis = active ? Math.min(1, (smoothedVoice * 2) + activationPulse) : 0;
    ring1.children.forEach(ch => ch.material.opacity = 0.25 * ringVis);
    ring2.children.forEach(ch => ch.material.opacity = 0.20 * ringVis);
    ring3.children.forEach(ch => ch.material.opacity = 0.18 * ringVis);

    // Fragments: orbit fast during active, drift slowly when idle
    const fragSpeed = active ? (1.0 + visualEnergy * 1.5) : 0.25;
    for (let i = 0; i < FRAG_COUNT; i++) {
      const d = fragData[i];
      const ang = d.a + t * d.speed * fragSpeed;
      fragPos[i*3]   = Math.cos(ang) * d.r;
      fragPos[i*3+1] = Math.sin(ang * 0.7 + d.phase) * d.tilt * (1 + visualEnergy * 0.4);
      fragPos[i*3+2] = Math.sin(ang) * d.r;
    }
    fragGeo.attributes.position.needsUpdate = true;
    fragMat.opacity = active ? (0.4 + visualEnergy * 0.5) : 0.08;
    fragMat.size = 0.03 + visualEnergy * 0.025;

    const breathe = 1 + Math.sin(t*(active?1.6:0.6))*(active?0.03:0.015) + visualEnergy*0.18;
    wireframe.scale.setScalar(breathe); fill.scale.setScalar(breathe);
    outerGlow.scale.setScalar(breathe*1.05);
    outerGlow.material.opacity = 0.04 + visualEnergy * 0.10;
    wireMat.opacity = 0.50 + visualEnergy*0.45;

    renderer.render(scene, camera);
    removeFallback();
  }
  animate(); resize(); window.addEventListener('resize', resize);
  setPhase("idle");

  const voiceSocket = new WebSocket(`ws://${window.location.host}/ws/voice?token=${encodeURIComponent(token)}`);
  voiceSocket.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.error) return;
    targetEnergy = data.amplitude;
    setPhase(data.phase);
  };
  voiceSocket.onclose = () => setPhase("idle");
})();
