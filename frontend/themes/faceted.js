// Faceted archetype - rigid lit plates (screen-2 candidate C), three.js.
// Plates light in waves + voice-driven flashes; geometry NEVER deforms.
// Falls back to Waveform if THREE is unavailable (spec error-handling rule).
(function () {
  window.ORB_THEMES = window.ORB_THEMES || {};

  window.ORB_THEMES.faceted = function create(wrap, size) {
    if (typeof THREE === "undefined") {
      return window.ORB_THEMES.waveform(wrap, size);
    }
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(40, 1, 0.1, 100);
    camera.position.z = 6.2;
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setClearColor(0x000000, 0);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(size, size);
    wrap.appendChild(renderer.domElement);

    const geo = new THREE.IcosahedronGeometry(1.7, 1).toNonIndexed();
    const faceCount = geo.attributes.position.count / 3;
    const colors = new Float32Array(geo.attributes.position.count * 3);
    geo.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    const mesh = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ vertexColors: true }));
    scene.add(mesh);

    const edgeMat = new THREE.LineBasicMaterial({ transparent: true, opacity: 0.5 });
    const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geo, 1), edgeMat);
    edges.scale.setScalar(1.002);
    scene.add(edges);

    const ringMat = new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.3 });
    const ring = new THREE.Mesh(new THREE.TorusGeometry(2.35, 0.006, 4, 96), ringMat);
    ring.rotation.x = Math.PI / 2 - 0.28;
    scene.add(ring);

    const flicker = new Array(faceCount).fill(0);

    function draw(s, pal) {
      const ACC = new THREE.Color(pal.accent);
      edgeMat.color.copy(ACC); ringMat.color.copy(ACC);
      const dim = s.active ? 1 : 0.5;
      for (let f = 0; f < faceCount; f++) {
        const wave = Math.sin(f * 0.7 + s.t * 2.2) * 0.5 + 0.5;
        const flash = s.active && Math.random() < s.v * 0.05 ? 1 : 0;
        flicker[f] = Math.max(flicker[f] * 0.93, flash);
        const level = (0.06 + wave * 0.10) * dim + s.v * wave * 0.45 + flicker[f] * 0.8;
        const c = ACC.clone().multiplyScalar(Math.min(1.2, 0.12 + level));
        for (let vtx = 0; vtx < 3; vtx++) {
          const i = (f * 3 + vtx) * 3;
          colors[i] = c.r; colors[i + 1] = c.g; colors[i + 2] = c.b;
        }
      }
      geo.attributes.color.needsUpdate = true;
      mesh.rotation.y += 0.004 + s.v * 0.012;
      edges.rotation.copy(mesh.rotation);
      ring.rotation.z = s.t * 0.25;
      ringMat.opacity = 0.12 * dim + s.v * 0.35;
      edgeMat.opacity = 0.35 * dim + s.v * 0.4;
      renderer.render(scene, camera);
    }

    return {
      draw,
      dispose() {
        // free GPU resources - archetype switches must not accumulate
        geo.dispose();
        mesh.material.dispose();
        edges.geometry.dispose();
        edgeMat.dispose();
        ring.geometry.dispose();
        ringMat.dispose();
        renderer.dispose();
        renderer.domElement.remove();
      },
    };
  };
})();
