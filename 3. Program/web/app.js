(() => {
  const els = {
    tcpBadge: document.getElementById("tcpBadge"),
    connBadge: document.getElementById("connBadge"),
    posX: document.getElementById("posX"),
    posY: document.getElementById("posY"),
    posZ: document.getElementById("posZ"),
    posR: document.getElementById("posR"),
    poseStatusText: document.getElementById("poseStatusText"),
    controlStatusText: document.getElementById("controlStatusText"),
    targetStatusText: document.getElementById("targetStatusText"),
    btnConnect: document.getElementById("btnConnect"),
    btnDisconnect: document.getElementById("btnDisconnect"),
    btnHome: document.getElementById("btnHome"),
    btnStop: document.getElementById("btnStop"),
    btnStopCenter: document.getElementById("btnStopCenter"),
    btnSuctionOn: document.getElementById("btnSuctionOn"),
    btnSuctionOff: document.getElementById("btnSuctionOff"),
    btnApplySpeed: document.getElementById("btnApplySpeed"),
    speedX: document.getElementById("speedX"),
    speedY: document.getElementById("speedY"),
    speedZ: document.getElementById("speedZ"),
    targetX: document.getElementById("targetX"),
    targetY: document.getElementById("targetY"),
    targetZ: document.getElementById("targetZ"),
    targetR: document.getElementById("targetR"),
    btnMoveXYZR: document.getElementById("btnMoveXYZR"),
    btnUseCurrentPose: document.getElementById("btnUseCurrentPose"),
    btnQuickHome: document.getElementById("btnQuickHome"),
    btnQuickSuctionOn: document.getElementById("btnQuickSuctionOn"),
    btnQuickSuctionOff: document.getElementById("btnQuickSuctionOff"),
  };

  const jogButtons = Array.from(document.querySelectorAll(".btn-jog[data-dir]"));
  let activeJogDir = null;
  let lastState = null;
  let pollingInFlight = false;

  function setStatusMessage(el, text, level = "info") {
    el.textContent = text;
    el.classList.remove("status-success", "status-warning", "status-error");
    if (level === "success") el.classList.add("status-success");
    else if (level === "warning") el.classList.add("status-warning");
    else if (level === "error") el.classList.add("status-error");
  }

  async function postJSON(url, body = {}) {
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (data.status) {
        renderState(data.status);
      }
      return data;
    } catch (err) {
      return { ok: false, message: `Gagal menghubungi server Flask: ${err.message}` };
    }
  }

  function renderState(state) {
    lastState = state;
    const tcpOn = Boolean(state.tcp_connected);
    const connected = Boolean(state.connected);

    els.tcpBadge.textContent = tcpOn ? "TCP: ONLINE" : "TCP: OFFLINE";
    els.tcpBadge.className = `badge ${tcpOn ? "badge-tcp-on" : "badge-tcp-off"}`;

    els.connBadge.textContent = connected ? "CONNECTED" : "DISCONNECTED";
    els.connBadge.className = `badge ${connected ? "badge-connected" : "badge-disconnected"}`;

    if (connected && state.pose) {
      els.posX.textContent = Number(state.pose.x).toFixed(2);
      els.posY.textContent = Number(state.pose.y).toFixed(2);
      els.posZ.textContent = Number(state.pose.z).toFixed(2);
      els.posR.textContent = Number(state.pose.r).toFixed(2);
      setStatusMessage(els.poseStatusText, "Posisi berhasil diperbarui.", "info");
    } else {
      els.posX.textContent = "---";
      els.posY.textContent = "---";
      els.posZ.textContent = "---";
      els.posR.textContent = "---";
      setStatusMessage(
        els.poseStatusText,
        state.message || "Robot belum terhubung.",
        state.level || "warning"
      );
    }

    // Highlight tombol Suction & Home jika aktif
    const suctionOn = Boolean(state.suction) && connected;
    els.btnSuctionOn.classList.toggle("is-active", suctionOn);
    els.btnQuickSuctionOn.classList.toggle("is-active", suctionOn);
    els.btnHome.classList.toggle("is-active", Boolean(state.homing));
    els.btnQuickHome.classList.toggle("is-active", Boolean(state.homing));

    if (state.message) {
      setStatusMessage(els.controlStatusText, state.message, state.level || "info");
    }
  }

  async function pollStatus() {
    if (pollingInFlight) return;
    pollingInFlight = true;
    try {
      const res = await fetch("/api/status", { cache: "no-store" });
      if (res.ok) {
        const state = await res.json();
        renderState(state);
      }
    } catch (_) {
      els.tcpBadge.textContent = "SERVER: OFFLINE";
      els.tcpBadge.className = "badge badge-tcp-off";
    } finally {
      pollingInFlight = false;
    }
  }

  // ===== CONTINUOUS JOG =====
  async function startJog(dir, btn) {
    if (activeJogDir === dir) return;
    activeJogDir = dir;
    jogButtons.forEach((b) => b.classList.toggle("active", b === btn));
    const res = await postJSON("/api/jog/start", { direction: dir });
    if (!res.ok) {
      setStatusMessage(els.controlStatusText, res.message || "Gagal memulai JOG.", "warning");
    }
  }

  async function stopJog() {
    if (activeJogDir === null) return;
    activeJogDir = null;
    jogButtons.forEach((b) => b.classList.remove("active"));
    await postJSON("/api/jog/stop");
  }

  jogButtons.forEach((btn) => {
    const dir = btn.dataset.dir;
    btn.addEventListener("contextmenu", (e) => e.preventDefault());

    btn.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      if (btn.setPointerCapture && e.pointerId !== undefined) {
        try {
          btn.setPointerCapture(e.pointerId);
        } catch (_) {}
      }
      startJog(dir, btn);
    });

    btn.addEventListener("pointerup", (e) => {
      e.preventDefault();
      stopJog();
    });

    btn.addEventListener("pointercancel", () => {
      stopJog();
    });
  });

  window.addEventListener("blur", () => {
    if (activeJogDir !== null) stopJog();
  });

  // Keyboard shortcut desktop (tidak aktif saat mengetik di input)
  const keyMap = {
    ArrowUp: "X+",
    ArrowDown: "X-",
    ArrowLeft: "Y+",
    ArrowRight: "Y-",
    q: "Z+",
    Q: "Z+",
    e: "Z-",
    E: "Z-",
  };

  window.addEventListener("keydown", (e) => {
    if (e.target && (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA")) return;
    if (e.repeat) return;
    if (e.code === "Space") {
      e.preventDefault();
      handleStopAll();
      return;
    }
    const dir = keyMap[e.key];
    if (dir) {
      e.preventDefault();
      const btn = jogButtons.find((b) => b.dataset.dir === dir);
      startJog(dir, btn || null);
    }
  });

  window.addEventListener("keyup", (e) => {
    if (e.target && (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA")) return;
    const dir = keyMap[e.key];
    if (dir && activeJogDir === dir) {
      e.preventDefault();
      stopJog();
    }
  });

  // ===== KONTROL UTAMA =====
  async function handleConnect() {
    setStatusMessage(els.controlStatusText, "Menghubungkan ke Dobot Magician...", "info");
    const res = await postJSON("/api/connect", {});
    setStatusMessage(
      els.controlStatusText,
      res.message || (res.ok ? "Dobot terhubung." : "Gagal terhubung."),
      res.ok ? "success" : "error"
    );
  }

  async function handleDisconnect() {
    activeJogDir = null;
    jogButtons.forEach((b) => b.classList.remove("active"));
    const res = await postJSON("/api/disconnect", {});
    setStatusMessage(
      els.controlStatusText,
      res.message || "Koneksi diputus.",
      res.ok ? "warning" : "error"
    );
  }

  async function handleHome() {
    activeJogDir = null;
    jogButtons.forEach((b) => b.classList.remove("active"));
    const res = await postJSON("/api/home", {});
    const msg = res.message || "Perintah HOME dikirim.";
    setStatusMessage(els.controlStatusText, msg, res.ok ? "info" : "warning");
    setStatusMessage(els.targetStatusText, msg, res.ok ? "info" : "warning");
  }

  async function handleStopAll() {
    activeJogDir = null;
    jogButtons.forEach((b) => b.classList.remove("active"));
    const res = await postJSON("/api/stop", {});
    setStatusMessage(els.controlStatusText, res.message || "STOP dikirim.", "warning");
  }

  async function handleSuction(state) {
    const res = await postJSON("/api/suction", { state });
    const msg = res.message || `Perintah Suction ${state ? "ON" : "OFF"} dikirim.`;
    setStatusMessage(els.controlStatusText, msg, res.ok ? "success" : "warning");
    setStatusMessage(els.targetStatusText, msg, res.ok ? "success" : "warning");
  }

  async function handleApplySpeed() {
    const x = parseFloat(els.speedX.value);
    const y = parseFloat(els.speedY.value);
    const z = parseFloat(els.speedZ.value);

    if ([x, y, z].some((v) => Number.isNaN(v) || v < 1 || v > 100)) {
      setStatusMessage(els.controlStatusText, "Kecepatan X, Y, Z harus antara 1 - 100 mm/s.", "error");
      return;
    }

    const res = await postJSON("/api/speed", { x, y, z });
    setStatusMessage(
      els.controlStatusText,
      res.message || "Kecepatan diterapkan.",
      res.ok ? "success" : "warning"
    );
  }

  // ===== TARGET POSISI X, Y, Z, R =====
  async function handleMoveXYZR() {
    const x = parseFloat(els.targetX.value);
    const y = parseFloat(els.targetY.value);
    const z = parseFloat(els.targetZ.value);
    const r = parseFloat(els.targetR.value);

    if ([x, y, z, r].some((v) => Number.isNaN(v))) {
      setStatusMessage(els.targetStatusText, "Semua kolom X, Y, Z, dan R wajib diisi angka.", "error");
      return;
    }

    setStatusMessage(
      els.targetStatusText,
      `Mengirim perintah gerak ke X=${x}, Y=${y}, Z=${z}, R=${r}...`,
      "info"
    );
    const res = await postJSON("/api/move", { x, y, z, r });
    setStatusMessage(
      els.targetStatusText,
      res.message || "Perintah target posisi dikirim.",
      res.ok ? "success" : "error"
    );
  }

  function handleUseCurrentPose() {
    if (!lastState || !lastState.connected || !lastState.pose) {
      setStatusMessage(els.targetStatusText, "Robot belum terhubung. Klik CONNECT terlebih dahulu.", "warning");
      return;
    }
    els.targetX.value = Number(lastState.pose.x).toFixed(2);
    els.targetY.value = Number(lastState.pose.y).toFixed(2);
    els.targetZ.value = Number(lastState.pose.z).toFixed(2);
    els.targetR.value = Number(lastState.pose.r).toFixed(2);
    setStatusMessage(els.targetStatusText, "Koordinat input diisi dari posisi aktual robot.", "success");
  }

  els.btnConnect.addEventListener("click", handleConnect);
  els.btnDisconnect.addEventListener("click", handleDisconnect);
  els.btnHome.addEventListener("click", handleHome);
  els.btnStop.addEventListener("click", handleStopAll);
  els.btnStopCenter.addEventListener("click", handleStopAll);
  els.btnSuctionOn.addEventListener("click", () => handleSuction(true));
  els.btnSuctionOff.addEventListener("click", () => handleSuction(false));
  els.btnApplySpeed.addEventListener("click", handleApplySpeed);

  els.btnMoveXYZR.addEventListener("click", handleMoveXYZR);
  els.btnUseCurrentPose.addEventListener("click", handleUseCurrentPose);
  els.btnQuickHome.addEventListener("click", handleHome);
  els.btnQuickSuctionOn.addEventListener("click", () => handleSuction(true));
  els.btnQuickSuctionOff.addEventListener("click", () => handleSuction(false));

  pollStatus();
  setInterval(pollStatus, 150);
})();

