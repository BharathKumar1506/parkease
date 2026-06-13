/**
 * upi_payment.js — Live QR UPI Payment Flow for ParkEase
 * ========================================================
 *
 * ── HOW TO RUN (IMPORTANT) ──────────────────────────────────────────────────
 *  The mobile phone and desktop must both reach the backend on the SAME port.
 *  Do NOT use VS Code Live Server (port 5500) — the mobile can't reach it
 *  through Windows Firewall.
 *
 *  CORRECT WAY — serve everything from FastAPI (port 8000):
 *    1. cd backend
 *    2. pip install -r requirements.txt   (adds aiofiles)
 *    3. python main.py
 *    4. Open on desktop:  http://192.168.29.120:8000/frontend/ParkEase.html
 *    5. Scan QR on mobile — it will open upi_mobile.html on port 8000
 *       and confirm payment through the same backend. ✓
 *
 *  Port 8000 is already allowed by FastAPI/uvicorn binding to 0.0.0.0.
 *  Windows Firewall allows it because Python/uvicorn registers the rule.
 *  Port 5500 (Live Server) does NOT get this rule → mobile blocked.
 * ────────────────────────────────────────────────────────────────────────────
 *
 * Flow:
 *  1. UPI_Payment.open() → POST /api/payments/qr-session → gets token
 *  2. Builds mobile URL: upi_mobile.html?token=TOKEN&...
 *  3. Generates QR from that URL (qrserver.com API)
 *  4. Desktop polls GET /api/payments/qr-status/TOKEN every 1s
 *     AND checks localStorage every 1s as a fallback (same-origin only)
 *  5. Mobile scans QR → opens upi_mobile.html → taps Pay Now
 *     → POST /api/payments/qr-confirm → backend marks paid
 *     If backend unreachable on mobile → writes localStorage as fallback
 *  6. Desktop poll detects status="paid" (backend) OR localStorage flag
 *     → shows processing → success → ticket
 */
;(function (global) {
  "use strict";

  var state = {
    phase: "qr",
    token: "",
    txnId: "",
    upiRef: "",
    amount: 0,
    pollTimer: null,
    countdownTimer: null,
    secondsLeft: 300,
    usingLocalFallback: false,  // true when backend was unreachable at session creation
  };

  function fmt(n) { return "₹" + parseFloat(n).toFixed(2); }

  function getAPI() {
    if (global.API) return global.API.replace(/\/$/, "");
    var host = window.location.hostname;
    var port = window.location.port;

    if (host === "localhost" || host === "127.0.0.1") {
      console.warn(
        "[ParkEase UPI] ⚠️  You are accessing via localhost. " +
        "Mobile phones cannot reach localhost. " +
        "Open this page via your LAN IP on port 8000: http://YOUR_LAN_IP:8000/frontend/ParkEase.html"
      );
    }

    // If already served from port 8000, the API is on the same origin
    if (port === "8000") {
      return window.location.protocol + "//" + host + ":8000";
    }

    // Otherwise assume API is on port 8000 of the same host
    return window.location.protocol + "//" + host + ":8000";
  }

  function getBookingInfo() {
    var ST = global.ST || {};
    return {
      amount:    ST.total || 0,
      lotName:   ST.lot  ? (ST.lot.name || "ParkEase") : "ParkEase",
      slot:      ST.slot ? (ST.slot.label || "").replace(" (Premium)","").trim() : "--",
      floor:     ST.floor || "--",
      entry:     ST.entry ? ST.entry.toLocaleTimeString("en-IN",{hour:"2-digit",minute:"2-digit"}) : "--",
      exit:      ST.exit  ? ST.exit.toLocaleTimeString ("en-IN",{hour:"2-digit",minute:"2-digit"}) : "--",
      date:      ST.entry ? ST.entry.toLocaleDateString("en-IN",{day:"2-digit",month:"short",year:"numeric"}) : "--",
      userName:  ST.uname  || "",
      userPhone: ST.uphone || "",
      vehicle:   (ST.vtype||"") + (ST.vnum ? " | "+ST.vnum : ""),
      duration:  (ST.hours||0) + " hr" + ((ST.hours||0)!==1?"s":""),
    };
  }

  function genTxnId() {
    var d = new Date();
    return "T"+d.getFullYear().toString().slice(2)
      +String(d.getMonth()+1).padStart(2,"0")
      +String(d.getDate()).padStart(2,"0")
      +Math.random().toString(36).toUpperCase().replace(/[^A-Z0-9]/g,"").slice(0,10);
  }

  function genUpiRef() {
    return String(Math.floor(600000000000 + Math.random()*99999999999));
  }

  /* ─── Polling ─────────────────────────────────────────────────────────────
   * Unified poll: checks backend AND localStorage every second.
   * This means it works whether the mobile reached the backend or not.
   */
  function startPoll(token) {
    stopPoll();
    state.pollTimer = setInterval(function() {

      // ── 1. Always check localStorage first (same-origin fallback) ──────
      try {
        if (localStorage.getItem("parkease_paid_" + token) === "1") {
          localStorage.removeItem("parkease_paid_" + token);
          stopPoll();
          stopCountdown();
          state.txnId  = genTxnId();
          state.upiRef = genUpiRef();
          showProcessing();
          return;  // ← already handled, skip backend check this tick
        }
      } catch(e) {}

      // ── 2. Also poll backend (skip if we know backend is unreachable) ──
      if (state.usingLocalFallback) return;

      fetch(getAPI() + "/api/payments/qr-status/" + token)
        .then(function(r){ return r.json(); })
        .then(function(d){
          if (d.status === "paid") {
            stopPoll();
            stopCountdown();
            state.txnId  = d.txn_id  || genTxnId();
            state.upiRef = d.upi_ref || genUpiRef();
            showProcessing();
          } else if (d.status === "expired") {
            stopPoll();
            stopCountdown();
            closeModal();
            if (global.showToast) global.showToast("QR expired. Please try again.","error");
            var btn = document.getElementById("payNowBtn");
            if (btn) btn.disabled = false;
          }
        })
        .catch(function(){/* network blip — keep polling */});
    }, 1000);
  }

  function stopPoll() {
    if (state.pollTimer) { clearInterval(state.pollTimer); state.pollTimer = null; }
  }

  function stopCountdown() {
    if (state.countdownTimer) { clearInterval(state.countdownTimer); state.countdownTimer = null; }
  }

  function closeModal() {
    stopPoll(); stopCountdown();
    var m = document.getElementById("upiPayModal");
    if (m) m.classList.remove("open");
  }

  /* ─── Build modal DOM once ───────────────────────────────────────────── */
  function buildModal() {
    if (document.getElementById("upiPayModal")) return;

    var style = document.createElement("style");
    style.textContent = `
      #upiPayModal{display:none;position:fixed;inset:0;background:rgba(5,7,14,.97);
        backdrop-filter:blur(20px);z-index:9998;align-items:center;
        justify-content:center;padding:16px;overflow-y:auto;}
      #upiPayModal.open{display:flex;}
      .upi-sheet{background:#0d1117;border:1px solid #1a2235;border-radius:28px;
        width:100%;max-width:420px;overflow:hidden;
        animation:upiUp .4s cubic-bezier(.34,1.56,.64,1) both;position:relative;}
      @keyframes upiUp{from{opacity:0;transform:translateY(70px) scale(.93)}to{opacity:1;transform:translateY(0) scale(1)}}

      /* Header */
      .upi-hdr{background:linear-gradient(135deg,#0a1422,#0d1830);padding:18px 22px;
        border-bottom:1px solid #1a2235;display:flex;align-items:center;justify-content:space-between;}
      .upi-hdr-brand{display:flex;align-items:center;gap:10px;}
      .upi-hdr-logo{width:38px;height:38px;background:linear-gradient(135deg,#00e5a0,#00b4d8);
        border-radius:10px;display:flex;align-items:center;justify-content:center;
        font-family:Syne,sans-serif;font-weight:800;font-size:14px;color:#000;}
      .upi-hdr-title{font-family:Syne,sans-serif;font-weight:700;font-size:.95rem;color:#f0f4ff;}
      .upi-hdr-sub{font-size:.7rem;color:#5a6a8a;margin-top:1px;}
      .upi-hdr-secure{background:rgba(0,229,160,.1);border:1px solid rgba(0,229,160,.25);
        color:#00e5a0;font-size:.65rem;font-weight:700;padding:4px 10px;border-radius:20px;}
      .upi-body{padding:22px;}

      /* Amount */
      .upi-amt-box{background:linear-gradient(135deg,rgba(0,229,160,.06),rgba(0,180,216,.06));
        border:1px solid rgba(0,229,160,.15);border-radius:18px;padding:16px 20px;
        display:flex;align-items:center;justify-content:space-between;margin-bottom:18px;}
      .upi-amt-label{font-size:.7rem;color:#5a6a8a;text-transform:uppercase;letter-spacing:1.5px;margin-bottom:4px;}
      .upi-amt-value{font-family:Syne,sans-serif;font-size:2rem;font-weight:800;
        background:linear-gradient(135deg,#00e5a0,#00b4d8);
        -webkit-background-clip:text;background-clip:text;
        -webkit-text-fill-color:transparent;color:transparent;line-height:1;}
      .upi-amt-to{font-size:.75rem;color:#5a6a8a;margin-top:4px;}
      .upi-upi-badge{background:rgba(255,255,255,.04);border:1px solid #1a2235;
        border-radius:12px;padding:10px 14px;text-align:center;}
      .upi-upi-badge-icon{font-size:22px;margin-bottom:2px;}
      .upi-upi-badge-txt{font-size:.65rem;font-weight:700;color:#00e5a0;}

      /* QR section */
      .upi-qr-section{text-align:center;}
      .upi-qr-instruction{font-size:.82rem;color:#8a9ab8;margin-bottom:14px;line-height:1.5;}
      .upi-qr-instruction strong{color:#f0f4ff;}
      .upi-qr-frame-wrap{display:inline-block;position:relative;margin-bottom:14px;}
      .upi-qr-frame{background:#fff;padding:12px;border-radius:20px;line-height:0;
        display:inline-block;position:relative;
        box-shadow:0 0 0 1px rgba(0,229,160,.15),0 0 40px rgba(0,229,160,.15);
        animation:qrGlow 2.5s ease-in-out infinite;}
      @keyframes qrGlow{
        0%,100%{box-shadow:0 0 0 1px rgba(0,229,160,.15),0 0 30px rgba(0,229,160,.1);}
        50%{box-shadow:0 0 0 2px rgba(0,229,160,.3),0 0 60px rgba(0,229,160,.28);}
      }
      .upi-qr-frame::before,.upi-qr-frame::after{content:"";position:absolute;
        width:22px;height:22px;border-color:#00e5a0;border-style:solid;border-radius:3px;z-index:2;}
      .upi-qr-frame::before{top:-2px;left:-2px;border-width:3px 0 0 3px;}
      .upi-qr-frame::after{bottom:-2px;right:-2px;border-width:0 3px 3px 0;}
      .upi-scan-line{position:absolute;left:12px;right:12px;height:2px;
        background:linear-gradient(90deg,transparent,#00e5a0,transparent);
        border-radius:1px;animation:scanLine 2s ease-in-out infinite;pointer-events:none;}
      @keyframes scanLine{0%{top:12px;opacity:0}10%{opacity:1}90%{opacity:1}100%{top:calc(100% - 12px);opacity:0}}

      /* Loading spinner inside QR frame */
      .upi-qr-loading{width:200px;height:200px;display:flex;flex-direction:column;
        align-items:center;justify-content:center;gap:12px;}
      .upi-qr-loading-spin{width:36px;height:36px;border:3px solid #e0e0e0;
        border-top-color:#00e5a0;border-radius:50%;animation:qrSpin .7s linear infinite;}
      @keyframes qrSpin{to{transform:rotate(360deg)}}
      .upi-qr-loading-txt{font-size:.72rem;color:#888;}

      /* Timer */
      .upi-timer-row{display:flex;align-items:center;justify-content:center;gap:8px;margin-bottom:14px;}
      .upi-timer-dot{width:8px;height:8px;border-radius:50%;background:#00e5a0;
        animation:tdp 1s ease-in-out infinite;}
      @keyframes tdp{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.4;transform:scale(.7)}}
      .upi-timer-txt{font-size:.78rem;color:#5a6a8a;}
      .upi-timer-txt span{font-family:Syne,sans-serif;font-weight:700;color:#00e5a0;}

      /* Steps */
      .upi-steps{display:flex;justify-content:center;gap:16px;margin-bottom:18px;}
      .upi-step-item{text-align:center;font-size:.68rem;color:#3a4a66;}
      .upi-step-num{width:26px;height:26px;border-radius:50%;background:#111827;
        border:1.5px solid #1e2840;display:flex;align-items:center;justify-content:center;
        margin:0 auto 4px;font-family:Syne,sans-serif;font-weight:700;font-size:.75rem;color:#3a4a66;}

      /* Processing */
      .upi-proc-wrap{text-align:center;padding:16px 0 8px;}
      .upi-proc-ring{width:90px;height:90px;margin:0 auto 20px;border-radius:50%;
        border:4px solid #1e2840;border-top-color:#00e5a0;border-right-color:#00b4d8;
        animation:pSpin .9s linear infinite;display:flex;align-items:center;justify-content:center;position:relative;}
      @keyframes pSpin{to{transform:rotate(360deg)}}
      .upi-proc-inner{position:absolute;inset:10px;border-radius:50%;
        background:rgba(0,229,160,.06);display:flex;align-items:center;justify-content:center;font-size:24px;}
      .upi-proc-title{font-family:Syne,sans-serif;font-size:1.1rem;font-weight:800;color:#f0f4ff;margin-bottom:6px;}
      .upi-proc-sub{color:#5a6a8a;font-size:.82rem;margin-bottom:18px;}
      .upi-proc-steps{display:flex;flex-direction:column;gap:7px;}
      .upi-proc-row{display:flex;align-items:center;gap:10px;padding:9px 13px;border-radius:12px;
        background:#111520;border:1px solid #1e2840;font-size:.82rem;color:#5a6a8a;transition:all .4s;}
      .upi-proc-row.active{border-color:rgba(0,180,216,.4);background:rgba(0,180,216,.06);color:#00b4d8;}
      .upi-proc-row.done{border-color:rgba(0,229,160,.3);background:rgba(0,229,160,.06);color:#00e5a0;}
      .upi-proc-dot{width:20px;height:20px;border-radius:50%;border:2px solid #1e2840;flex-shrink:0;
        display:flex;align-items:center;justify-content:center;font-size:10px;font-weight:800;transition:all .4s;}
      .upi-proc-row.active .upi-proc-dot{border-color:#00b4d8;animation:dp .7s ease-in-out infinite;}
      .upi-proc-row.done  .upi-proc-dot{background:#00e5a0;border-color:#00e5a0;color:#000;}
      @keyframes dp{0%,100%{opacity:1}50%{opacity:.3}}

      /* Success */
      .upi-success-wrap{text-align:center;padding:6px 0;}
      .upi-success-ring{width:86px;height:86px;margin:0 auto 16px;border-radius:50%;
        background:linear-gradient(135deg,#00e5a0,#00b4d8);
        display:flex;align-items:center;justify-content:center;font-size:36px;color:#000;
        animation:sPop .6s cubic-bezier(.34,1.56,.64,1) both;
        box-shadow:0 0 50px rgba(0,229,160,.4);}
      @keyframes sPop{from{opacity:0;transform:scale(.2)}to{opacity:1;transform:scale(1)}}
      .upi-success-title{font-family:Syne,sans-serif;font-size:1.4rem;font-weight:800;color:#f0f4ff;margin-bottom:4px;}
      .upi-success-sub{color:#5a6a8a;font-size:.82rem;margin-bottom:18px;}
      .upi-txn-card{background:#111520;border:1px solid #1e2840;border-radius:14px;padding:14px;margin-bottom:18px;text-align:left;}
      .upi-txn-row{display:flex;justify-content:space-between;align-items:center;
        padding:7px 0;border-bottom:1px solid rgba(255,255,255,.04);font-size:.8rem;}
      .upi-txn-row:last-child{border:none;}
      .upi-txn-lbl{color:#5a6a8a;}
      .upi-txn-val{font-weight:600;color:#f0f4ff;text-align:right;}
      .upi-txn-val.green{color:#00e5a0;font-family:Syne,sans-serif;font-weight:800;}
      .upi-continue-btn{width:100%;background:linear-gradient(135deg,#00e5a0,#00b4d8);
        color:#000;font-family:Syne,sans-serif;font-weight:800;font-size:1rem;padding:17px;
        border:none;border-radius:15px;cursor:pointer;transition:all .2s;
        box-shadow:0 8px 32px rgba(0,229,160,.3);}
      .upi-continue-btn:hover{transform:translateY(-2px);box-shadow:0 12px 40px rgba(0,229,160,.45);}

      .upi-footer{text-align:center;margin-top:12px;font-size:.67rem;color:#2a3a55;
        display:flex;align-items:center;justify-content:center;gap:6px;}
    `;
    document.head.appendChild(style);

    var modal = document.createElement("div");
    modal.id = "upiPayModal";
    modal.innerHTML =
      '<div class="upi-sheet">'
      +'<div class="upi-hdr">'
        +'<div class="upi-hdr-brand">'
          +'<div class="upi-hdr-logo">P</div>'
          +'<div><div class="upi-hdr-title">ParkEase Pay</div><div class="upi-hdr-sub">Scan QR · Any UPI app</div></div>'
        +'</div>'
        +'<div class="upi-hdr-secure">🔒 Secure</div>'
      +'</div>'
      +'<div class="upi-body" id="upiBody"></div>'
      +'</div>';
    document.body.appendChild(modal);
  }

  /* ─── Render: QR phase ───────────────────────────────────────────────── */
  function renderQR(info, token) {
    var body = document.getElementById("upiBody");

    // Build the mobile page URL.
    // IMPORTANT: window.location.origin must be the LAN IP (e.g. http://192.168.1.10:5500),
    // NOT localhost — mobile phones cannot reach localhost on the desktop.
    var pageOrigin = window.location.origin;  // e.g. http://192.168.1.10:5500
    var apiOrigin  = getAPI();                // e.g. http://192.168.1.10:8000
    var base = pageOrigin + window.location.pathname.replace(/[^/]*$/, "");
    var mobileUrl = base + "upi_mobile.html"
      + "?token="  + encodeURIComponent(token)
      + "&amount=" + encodeURIComponent(info.amount)
      + "&lot="    + encodeURIComponent(info.lotName)
      + "&slot="   + encodeURIComponent(info.slot)
      + "&api="    + encodeURIComponent(apiOrigin);

    console.log("[ParkEase UPI] Mobile URL:", mobileUrl);
    console.log("[ParkEase UPI] API host:", getAPI());
    body.innerHTML =
      '<div class="upi-amt-box">'
        +'<div>'
          +'<div class="upi-amt-label">Pay Amount</div>'
          +'<div class="upi-amt-value">'+fmt(info.amount)+'</div>'
          +'<div class="upi-amt-to">To: ParkEase Parking</div>'
        +'</div>'
        +'<div class="upi-upi-badge"><div class="upi-upi-badge-icon">📲</div><div class="upi-upi-badge-txt">UPI</div></div>'
      +'</div>'
      +'<div class="upi-qr-section">'
        +'<div class="upi-qr-instruction"><strong>Scan QR with your phone</strong><br>Opens payment page automatically</div>'
        +'<div class="upi-qr-frame-wrap">'
          +'<div class="upi-qr-frame" id="upiQrFrame">'
            +'<div id="upiQrSlot">'
              +'<div class="upi-qr-loading"><div class="upi-qr-loading-spin"></div><div class="upi-qr-loading-txt">Generating QR…</div></div>'
            +'</div>'
            +'<div class="upi-scan-line"></div>'
          +'</div>'
        +'</div>'
        +'<div class="upi-timer-row">'
          +'<div class="upi-timer-dot"></div>'
          +'<div class="upi-timer-txt">Waiting for payment · Expires in <span id="upiTimerVal">5:00</span></div>'
        +'</div>'
        +'<div class="upi-steps">'
          +'<div class="upi-step-item"><div class="upi-step-num">1</div>Scan QR</div>'
          +'<div class="upi-step-item" style="color:#5a6a8a;font-size:1.1rem;margin-top:5px">→</div>'
          +'<div class="upi-step-item"><div class="upi-step-num">2</div>Pay on Mobile</div>'
          +'<div class="upi-step-item" style="color:#5a6a8a;font-size:1.1rem;margin-top:5px">→</div>'
          +'<div class="upi-step-item"><div class="upi-step-num">3</div>Auto Confirm</div>'
        +'</div>'
      +'</div>'
      +'<div class="upi-footer">🔒 256-bit SSL &nbsp;|&nbsp; UPI Secured &nbsp;|&nbsp; PCI DSS</div>';

    // Generate QR image
    loadQR(mobileUrl);

    // Countdown
    state.secondsLeft = 300;
    stopCountdown();
    state.countdownTimer = setInterval(function() {
      state.secondsLeft--;
      var el = document.getElementById("upiTimerVal");
      if (el) {
        var m = Math.floor(state.secondsLeft / 60);
        var s = state.secondsLeft % 60;
        el.textContent = m + ":" + String(s).padStart(2,"0");
        if (state.secondsLeft <= 30) el.style.color = "#ff6b35";
      }
      if (state.secondsLeft <= 0) {
        stopCountdown(); stopPoll(); closeModal();
        var btn = document.getElementById("payNowBtn");
        if (btn) btn.disabled = false;
        if (global.showToast) global.showToast("QR expired. Try again.","error");
      }
    }, 1000);

    // Start unified poll (checks both backend AND localStorage)
    startPoll(token);
  }

  /* ─── QR image loader — tries QRCode.js first, then qrserver.com ─────── */
  function loadQR(url) {
    var slot = document.getElementById("upiQrSlot");
    if (!slot) return;

    // Try QRCode.js (needs a div)
    if (global.QRCode) {
      try {
        slot.innerHTML = "";
        var div = document.createElement("div");
        slot.appendChild(div);
        new global.QRCode(div, {
          text: url, width: 200, height: 200,
          colorDark: "#000000", colorLight: "#ffffff",
          correctLevel: global.QRCode.CorrectLevel.M
        });
        // Verify after render
        setTimeout(function() {
          var img = div.querySelector("img");
          if (!img || img.naturalWidth === 0) fallbackQR(slot, url);
        }, 500);
        return;
      } catch(e) {}
    }
    fallbackQR(slot, url);
  }

  function fallbackQR(slot, url) {
    slot.innerHTML = "";
    var img = document.createElement("img");
    img.width = 200; img.height = 200;
    img.style.display = "block";
    img.style.borderRadius = "4px";
    img.src = "https://api.qrserver.com/v1/create-qr-code/?size=200x200&data="
              + encodeURIComponent(url) + "&margin=4&format=png&ecc=M";
    img.onerror = function() {
      img.src = "https://chart.googleapis.com/chart?chs=200x200&cht=qr&choe=UTF-8&chl="
                + encodeURIComponent(url);
    };
    slot.appendChild(img);
  }

  /* ─── Render: Processing ─────────────────────────────────────────────── */
  var STEPS = [
    "Connecting to UPI network…",
    "Verifying payment signature…",
    "Confirming with ParkEase…",
    "Allocating parking slot…",
    "Generating confirmation…"
  ];

  function showProcessing() {
    state.phase = "processing";
    var body = document.getElementById("upiBody");
    body.innerHTML =
      '<div class="upi-proc-wrap">'
        +'<div class="upi-proc-ring"><div class="upi-proc-inner">💳</div></div>'
        +'<div class="upi-proc-title">Processing Payment</div>'
        +'<div class="upi-proc-sub">Please wait, do not close this page</div>'
        +'<div class="upi-proc-steps">'
          + STEPS.map(function(s,i){
              return '<div class="upi-proc-row" id="uPR'+i+'"><div class="upi-proc-dot" id="uPD'+i+'">·</div><span>'+s+'</span></div>';
            }).join("")
        +'</div>'
      +'</div>';

    var si = 0;
    function advance() {
      var prev = document.getElementById("uPR"+(si-1));
      if (prev) {
        prev.classList.remove("active"); prev.classList.add("done");
        var pd = document.getElementById("uPD"+(si-1));
        if (pd) pd.textContent = "✓";
      }
      if (si < STEPS.length) {
        var row = document.getElementById("uPR"+si);
        var dot = document.getElementById("uPD"+si);
        if (row) row.classList.add("active");
        if (dot) dot.textContent = "•";
        si++;
        setTimeout(advance, 550 + Math.random()*350);
      } else {
        var last = document.getElementById("uPR"+(STEPS.length-1));
        var ldot = document.getElementById("uPD"+(STEPS.length-1));
        if (last) { last.classList.remove("active"); last.classList.add("done"); }
        if (ldot) ldot.textContent = "✓";
        setTimeout(showSuccess, 600);
      }
    }
    advance();
  }

  /* ─── Render: Success ────────────────────────────────────────────────── */
  function showSuccess() {
    state.phase = "success";
    var info = getBookingInfo();
    var body = document.getElementById("upiBody");
    var autoSec = 3;

    body.innerHTML =
      '<div class="upi-success-wrap">'
        +'<div class="upi-success-ring">✓</div>'
        +'<div class="upi-success-title">Payment Successful!</div>'
        +'<div class="upi-success-sub">Taking you to your ticket…</div>'
        +'<div class="upi-txn-card">'
          +'<div class="upi-txn-row"><span class="upi-txn-lbl">Amount Paid</span><span class="upi-txn-val green">'+fmt(info.amount)+'</span></div>'
          +'<div class="upi-txn-row"><span class="upi-txn-lbl">Transaction ID</span><span class="upi-txn-val" style="font-size:.72rem">'+state.txnId+'</span></div>'
          +'<div class="upi-txn-row"><span class="upi-txn-lbl">UPI Ref No.</span><span class="upi-txn-val" style="font-size:.72rem">'+state.upiRef+'</span></div>'
          +'<div class="upi-txn-row"><span class="upi-txn-lbl">Payment Method</span><span class="upi-txn-val">UPI · QR</span></div>'
          +'<div class="upi-txn-row"><span class="upi-txn-lbl">Status</span><span class="upi-txn-val" style="color:#00e5a0;font-weight:800">✓ SUCCESS</span></div>'
          +'<div class="upi-txn-row"><span class="upi-txn-lbl">Time</span><span class="upi-txn-val">'+new Date().toLocaleTimeString("en-IN",{hour:"2-digit",minute:"2-digit",second:"2-digit"})+'</span></div>'
        +'</div>'
        +'<button class="upi-continue-btn" id="upiTicketBtn" onclick="UPI_Payment._confirmBooking()">'
          +'🎟 View Parking Ticket → <span id="upiAutoCount" style="opacity:.7;font-size:.85rem">('+autoSec+'s)</span>'
        +'</button>'
      +'</div>';

    if (global.confetti) global.confetti({particleCount:130,spread:90,origin:{y:0.5}});

    // ── Auto-advance countdown ──────────────────────────────────────────
    var left = autoSec;
    var autoTimer = setInterval(function() {
      left--;
      var el = document.getElementById("upiAutoCount");
      if (el) el.textContent = "(" + left + "s)";
      if (left <= 0) {
        clearInterval(autoTimer);
        UPI_Payment._confirmBooking();
      }
    }, 1000);
  }

  /* ─── Public API ─────────────────────────────────────────────────────── */
  var UPI_Payment = {

    open: function() {
      buildModal();
      var info = getBookingInfo();
      state.amount             = info.amount;
      state.phase              = "qr";
      state.token              = "";
      state.txnId              = "";
      state.upiRef             = "";
      state.usingLocalFallback = false;

      document.getElementById("upiPayModal").classList.add("open");

      // Show loading state
      var body = document.getElementById("upiBody");
      body.innerHTML =
        '<div style="text-align:center;padding:40px 0">'
          +'<div style="width:40px;height:40px;border:3px solid #1e2840;border-top-color:#00e5a0;'
          +'border-radius:50%;animation:qrSpin .7s linear infinite;margin:0 auto 14px"></div>'
          +'<div style="color:#5a6a8a;font-size:.85rem">Preparing secure session…</div>'
        +'</div>';

      // Create QR session on backend
      fetch(getAPI() + "/api/payments/qr-session", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          amount:     info.amount,
          lot_name:   info.lotName,
          slot_label: info.slot,
          user_name:  info.userName,
          user_phone: info.userPhone,
        })
      })
      .then(function(r){ return r.json(); })
      .then(function(d){
        if (d.success && d.token) {
          state.token = d.token;
          state.usingLocalFallback = false;
          renderQR(info, d.token);
        } else {
          throw new Error("No token");
        }
      })
      .catch(function(err){
        // Backend unreachable — use a local token and rely on localStorage poll only
        console.warn("[ParkEase UPI] Backend unavailable, using local token:", err);
        var fallbackToken = "LOCAL_" + Math.random().toString(36).slice(2).toUpperCase();
        state.token = fallbackToken;
        state.usingLocalFallback = true;  // ← tells startPoll to skip backend fetch
        renderQR(info, fallbackToken);
        // renderQR already calls startPoll, which handles localStorage too
      });
    },

    _confirmBooking: function() {
      closeModal();

      // Stamp ST with UPI payment info
      if (global.ST) {
        global.ST.payMethod = "UPI";
        global.ST.upiTxnId  = state.txnId;
        global.ST.upiRef    = state.upiRef;
      }

      // Reset any UI locks left over from the Pay Now button
      var btn = document.getElementById("payNowBtn");
      if (btn) btn.disabled = false;
      var ovl = document.getElementById("ovl");
      if (ovl) ovl.classList.remove("on");

      // Call the bridge defined at the bottom of ParkEase.html
      if (global._upiOrigProcessPayment) {
        global._upiOrigProcessPayment();
      } else if (global.showTicket) {
        global.showTicket();
      }
    },

    close: closeModal,
    getTxnId:  function(){ return state.txnId; },
    getUpiRef: function(){ return state.upiRef; },
  };

  global.UPI_Payment = UPI_Payment;

})(window);
