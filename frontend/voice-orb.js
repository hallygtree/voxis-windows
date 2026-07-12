(function () {
  const params = new URLSearchParams(window.location.search);
  const token = params.get("token");
  if (!token) return; // app.js already shows the "missing token" error

  const wrap = document.getElementById("orb-canvas-wrap");
  const caption = document.getElementById("phaseCaption");
  const ampFill = document.getElementById("ampFill");

  const PHASE_CAPTIONS = {
    recording: "ouvindo...",
    awaiting_project: "qual projeto?",
    awaiting_dictation: "pode ditar a mensagem...",
    awaiting_send: 'digitado - diga "manda" ou aperte enter',
  };

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
  camera.position.z = 3.2;

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  // explicit: inside the desktop overlay's transparent WKWebView an opaque
  // clear paints a dark tile behind the orb (invisible on the dark dashboard)
  renderer.setClearColor(0x000000, 0);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  wrap.appendChild(renderer.domElement);

  function resize() {
    const size = wrap.clientWidth || 120;
    renderer.setSize(size, size);
    camera.aspect = 1;
    camera.updateProjectionMatrix();
  }

  const geo = new THREE.IcosahedronGeometry(1, 3);
  const baseVerts = geo.attributes.position.array.slice();

  const wireMat = new THREE.LineBasicMaterial({ color: 0x5adce1, transparent: true, opacity: 0.85 });
  const wireframe = new THREE.LineSegments(new THREE.WireframeGeometry(geo), wireMat);
  scene.add(wireframe);

  const fillMat = new THREE.MeshBasicMaterial({ color: 0x0d2a2c, transparent: true, opacity: 0.22 });
  const fill = new THREE.Mesh(geo, fillMat);
  scene.add(fill);

  const outerGlow = new THREE.Mesh(new THREE.IcosahedronGeometry(1.3, 2),
    new THREE.MeshBasicMaterial({ color: 0x5adce1, transparent: true, opacity: 0.05, side: THREE.BackSide, blending: THREE.AdditiveBlending }));
  scene.add(outerGlow);

  const cyan = new THREE.Color(0x5adce1), pink = new THREE.Color(0xd95a9e);

  function smoothNoise(x, y, z, time, freq) {
    return (Math.sin(x*freq+time*0.6)+Math.sin(y*freq*1.3+time*0.5+1.7)+Math.sin(z*freq*0.9+time*0.7+3.1)+Math.sin((x+y)*freq*0.6-time*0.4))/4;
  }
  function updateWireframe() {
    const newWire = new THREE.WireframeGeometry(geo);
    wireframe.geometry.dispose();
    wireframe.geometry = newWire;
  }

  let active = false;
  let t = 0;
  let targetEnergy = 0;
  let smoothedVoice = 0;
  let idleFrameSkip = 0;

  function setPhase(phase) {
    active = phase !== "idle";
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
    // VU-meter ballistics: fast attack so the orb jumps with speech onsets,
    // slow release so it falls smoothly. Live ~25Hz mic events re-feed
    // targetEnergy while recording; the decay only matters once they stop.
    targetEnergy *= 0.96;
    const rate = targetEnergy > smoothedVoice ? 0.5 : 0.12;
    smoothedVoice += (targetEnergy - smoothedVoice) * rate;
    const baseline = active ? 0.1 : 0.02;
    const energy = baseline + smoothedVoice * 0.85;
    ampFill.style.width = Math.min(100, energy*100) + '%';

    const pos = geo.attributes.position;
    const freq = 1.1, amp = 0.05 + energy * 0.2;
    for (let i = 0; i < pos.count; i++) {
      const ix = i*3, bx=baseVerts[ix], by=baseVerts[ix+1], bz=baseVerts[ix+2];
      const len = Math.sqrt(bx*bx+by*by+bz*bz)||1, nx=bx/len, ny=by/len, nz=bz/len;
      const n = smoothNoise(nx,ny,nz,t,freq), d = 1+n*amp;
      pos.array[ix]=nx*d; pos.array[ix+1]=ny*d; pos.array[ix+2]=nz*d;
    }
    pos.needsUpdate = true; geo.computeVertexNormals(); updateWireframe();

    const mixT = Math.min(1, energy*1.3);
    const c = cyan.clone().lerp(pink, mixT);
    wireMat.color.copy(c); fillMat.color.copy(c.clone().multiplyScalar(0.25));

    const rotSpeed = active ? 1.4 : 0.4;
    wireframe.rotation.y += 0.003*rotSpeed; fill.rotation.y = wireframe.rotation.y;
    wireframe.rotation.x = Math.sin(t*0.3)*0.08; fill.rotation.x = wireframe.rotation.x;

    const breathe = 1 + Math.sin(t*(active?1.6:0.6))*(active?0.03:0.015) + energy*0.1;
    wireframe.scale.setScalar(breathe); fill.scale.setScalar(breathe);
    outerGlow.scale.setScalar(breathe*1.05);
    wireMat.opacity = 0.55 + energy*0.4;

    renderer.render(scene, camera);
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
