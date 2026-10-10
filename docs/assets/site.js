/* PolTrends Australia — interactions (no dependencies) */
(function () {
  "use strict";

  // Reveal on scroll
  var io = "IntersectionObserver" in window ? new IntersectionObserver(function (entries) {
    entries.forEach(function (e) { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } });
  }, { rootMargin: "0px 0px -8% 0px" }) : null;
  document.querySelectorAll(".reveal").forEach(function (el) { io ? io.observe(el) : el.classList.add("in"); });

  // Copy link
  document.querySelectorAll("[data-copy]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var url = btn.getAttribute("data-copy") || location.href;
      (navigator.clipboard ? navigator.clipboard.writeText(url) : Promise.reject()).then(function () {
        var t = btn.textContent; btn.textContent = "Copied"; setTimeout(function () { btn.textContent = t; }, 1600);
      }).catch(function () {});
    });
  });

  // Days left (same rule as the countdown: whole days until polls open, 8am AEDT)
  var POLLS_OPEN = new Date("2026-11-28T08:00:00+11:00").getTime();
  var daysLeft = Math.max(0, Math.floor((POLLS_OPEN - Date.now()) / 864e5));
  document.querySelectorAll("[data-days-left]").forEach(function (el) { el.textContent = daysLeft; });

  // Countdown
  var cd = document.querySelector("[data-countdown]");
  if (cd) {
    var target = new Date(cd.getAttribute("data-countdown")).getTime();
    var set = function (unit, v) { var el = cd.querySelector('[data-u="' + unit + '"]'); if (el) el.textContent = v; };
    var tick = function () {
      var ms = Math.max(0, target - Date.now());
      set("d", Math.floor(ms / 864e5));
      set("h", String(Math.floor(ms / 36e5) % 24).padStart(2, "0"));
      set("m", String(Math.floor(ms / 6e4) % 60).padStart(2, "0"));
      set("s", String(Math.floor(ms / 1e3) % 60).padStart(2, "0"));
    };
    tick(); setInterval(tick, 1000);
  }

  // ---------------- Pendulum ----------------
  var dataEl = document.getElementById("seat-data");
  var svg = document.getElementById("pendulum");
  if (!dataEl || !svg) return;

  var D = JSON.parse(dataEl.textContent);
  var seats = D.seats, MAJ = D.majority, TOTAL = seats.length;
  var COL = { ALP: "#F0524A", LIB: "#3D8BFD", NAT: "#F2C230", LNP: "#3D8BFD", GRN: "#3FCB6E", IND: "#9AA4B2" };
  var NAME = { ALP: "Labor", LIB: "Liberal", NAT: "Nationals", LNP: "Coalition", GRN: "Greens", IND: "Independent" };
  var NS = "http://www.w3.org/2000/svg";
  var W = 1000, BASE = 210, R = 7, STEP = 15.5, MINM = -19, MAXM = 25;
  var scale = W / (MAXM - MINM), cx = -MINM * scale;
  var coalition = function (p) { return p === "LIB" || p === "NAT" || p === "LNP"; };

  var classic = seats.filter(function (s) { return s.classic; });
  var other = seats.filter(function (s) { return !s.classic; });

  // Stack classic seats in 1-point bins on each side of the centre line.
  var bins = {};
  classic.sort(function (a, b) { return a.margin - b.margin; }).forEach(function (s) {
    var side = s.holder === "ALP" ? -1 : 1;
    var b = Math.floor(s.margin);
    var key = side + ":" + b;
    bins[key] = (bins[key] || 0) + 1;
    s._x = cx + side * (b + 0.5) * scale;
    s._y = BASE - R - 2 - (bins[key] - 1) * STEP;
  });
  var tallest = Math.min.apply(null, classic.map(function (s) { return s._y; }));
  var top = Math.max(0, tallest - 40);
  var H = BASE + 46 - top;
  svg.setAttribute("viewBox", "0 " + top + " " + W + " " + H);

  function el(tag, attrs, parent) {
    var n = document.createElementNS(NS, tag);
    for (var k in attrs) n.setAttribute(k, attrs[k]);
    (parent || svg).appendChild(n);
    return n;
  }

  var shade = el("rect", { x: cx, y: top, width: 0, height: BASE - top, fill: "rgba(61,139,253,0.10)" });
  el("line", { x1: 0, x2: W, y1: BASE, y2: BASE, stroke: "rgba(255,255,255,0.14)" });
  [0, 5, 10, 15, 20].forEach(function (m) {
    [-1, 1].forEach(function (side) {
      if (m === 0 && side === 1) return;
      if (side === -1 && m > -MINM) return;
      var x = cx + side * m * scale;
      el("line", { x1: x, x2: x, y1: BASE, y2: BASE + 6, stroke: "rgba(255,255,255,0.25)" });
      var t = el("text", { x: x, y: BASE + 20, "text-anchor": "middle", class: "axis-label" });
      t.textContent = m + (m ? "%" : "");
    });
  });
  var lt = el("text", { x: 4, y: BASE + 40, class: "axis-title", fill: COL.ALP }); lt.textContent = "← SAFER LABOR";
  var rt = el("text", { x: W - 4, y: BASE + 40, "text-anchor": "end", class: "axis-title" }); rt.textContent = "SAFER COALITION →";
  var swingLine = el("line", { x1: cx, x2: cx, y1: top + 14, y2: BASE, stroke: "#fff", "stroke-width": 2, "stroke-dasharray": "4 4" });
  var swingLabel = el("text", { x: cx, y: top + 10, "text-anchor": "middle", class: "axis-title" });

  var tip = document.getElementById("seat-tip");
  var wrap = document.querySelector(".pendulum-wrap") || svg.parentNode;
  var scroller = document.getElementById("pendulum-scroll");
  function centreOnSwing() {
    if (!scroller || scroller.scrollWidth <= scroller.clientWidth) return;
    var x = (cx - current * scale) / W * scroller.scrollWidth;
    scroller.scrollLeft = Math.max(0, x - scroller.clientWidth * 0.6);
  }
  classic.forEach(function (s) {
    s._node = el("circle", { cx: s._x, cy: s._y, r: R, class: "seat", tabindex: 0, "aria-label": s.seat });
    var show = function () { showTip(s, s._node); };
    s._node.addEventListener("mouseenter", show);
    s._node.addEventListener("focus", show);
    s._node.addEventListener("click", show);
    s._node.addEventListener("mouseleave", hideTip);
    s._node.addEventListener("blur", hideTip);
  });

  function showTip(s, node) {
    if (!tip) return;
    var swing = current;
    var proj = project(s, swing);
    var falls = s.classic ? (s.holder === "ALP" ? s.margin.toFixed(1) + "% to Coalition" : s.margin.toFixed(1) + "% to Labor") : "Not a Labor v Coalition contest";
    tip.innerHTML = "<h4>" + s.seat + "</h4>" +
      '<div class="r"><span>Member</span><b>' + s.member + "</b></div>" +
      '<div class="r"><span>Held by</span><b>' + NAME[s.holder] + "</b></div>" +
      '<div class="r"><span>2022 margin</span><b>' + s.margin.toFixed(1) + "% v " + (NAME[s.vs] || s.vs) + "</b></div>" +
      '<div class="r"><span>Falls on a swing of</span><b>' + falls + "</b></div>" +
      '<div class="r"><span>Region</span><b>' + (s.region || "") + "</b></div>" +
      '<div class="r"><span>At this swing</span><b style="color:' + COL[proj] + '">' + NAME[proj] + "</b></div>" +
      (s.note ? '<div class="note" style="margin-top:6px">' + s.note + "</div>" : "");
    var box = wrap.getBoundingClientRect(), nb = node.getBoundingClientRect();
    var x = nb.left - box.left + nb.width / 2, y = nb.top - box.top;
    tip.style.left = Math.min(Math.max(8, x - 120), box.width - 268) + "px";
    tip.style.top = Math.max(0, y - tip.offsetHeight - 12) + "px";
    tip.classList.add("show");
  }
  function hideTip() { if (tip) tip.classList.remove("show"); }

  function project(s, swing) {
    if (!s.classic) return s.holder;
    if (s.holder === "ALP") return swing > s.margin ? "LNP" : "ALP";
    return swing < -s.margin ? "ALP" : s.holder;
  }

  var slider = document.getElementById("swing");
  var readout = document.getElementById("swing-readout");
  var verdict = document.getElementById("verdict");
  var flipList = document.getElementById("flip-list");
  var tallyBar = document.getElementById("tally-bar");
  var tallyLabels = document.getElementById("tally-labels");
  var current = parseFloat(slider.value);

  function render(swing) {
    current = swing;
    var t = { ALP: 0, LNP: 0, GRN: 0, IND: 0 }, flips = [];
    seats.forEach(function (s) {
      var p = project(s, swing);
      var g = coalition(p) ? "LNP" : p;
      t[g] = (t[g] || 0) + 1;
      var changed = (s.holder === "ALP" && g !== "ALP") || (coalition(s.holder) && g === "ALP");
      if (changed) flips.push({ seat: s.seat, to: g, margin: s.margin });
      if (s._node) {
        var fill = p === "LNP" ? COL.LIB : COL[p];
        s._node.setAttribute("fill", fill);
        s._node.setAttribute("stroke", changed ? "#fff" : "rgba(9,13,21,0.9)");
        s._node.setAttribute("stroke-width", changed ? 2.2 : 1.5);
      }
    });
    var x = cx - swing * scale;
    swingLine.setAttribute("x1", x); swingLine.setAttribute("x2", x);
    shade.setAttribute("x", Math.min(x, cx)); shade.setAttribute("width", Math.abs(cx - x));
    shade.setAttribute("fill", swing >= 0 ? "rgba(61,139,253,0.10)" : "rgba(240,82,74,0.10)");
    var dir = swing > 0.05 ? "to Coalition" : swing < -0.05 ? "to Labor" : "";
    swingLabel.setAttribute("x", Math.min(Math.max(x, 60), W - 60));
    swingLabel.textContent = Math.abs(swing).toFixed(1) + "% " + dir;
    readout.textContent = (Math.abs(swing) < 0.05 ? "No swing" : Math.abs(swing).toFixed(1) + "% swing " + dir);

    var parts = [["ALP", t.ALP], ["GRN", t.GRN], ["IND", t.IND], ["LNP", t.LNP]];
    tallyBar.querySelectorAll("span").forEach(function (sp) {
      var k = sp.getAttribute("data-k"), n = t[k] || 0;
      sp.style.flexBasis = (n / TOTAL * 100) + "%";
      sp.textContent = n >= 4 ? n : "";
    });
    tallyLabels.innerHTML = '<span><b style="color:' + COL.ALP + '">Labor ' + t.ALP + "</b> · Greens " + t.GRN + "</span>" +
      "<span>" + MAJ + " for majority</span>" +
      '<span><b style="color:' + COL.LIB + '">Coalition ' + t.LNP + "</b></span>";
    verdict.textContent = t.LNP >= MAJ ? "Coalition majority" : t.ALP >= MAJ ? "Labor majority" : "Hung parliament";
    verdict.style.color = t.LNP >= MAJ ? COL.LIB : t.ALP >= MAJ ? COL.ALP : "#E8ECF3";

    flips.sort(function (a, b) { return a.margin - b.margin; });
    flipList.innerHTML = flips.length ? flips.map(function (f) {
      return '<span class="chip" style="--c:' + (f.to === "ALP" ? COL.ALP : COL.LIB) + '">' + f.seat + " <b style=\"color:inherit;opacity:.7\">" + f.margin.toFixed(1) + "</b></span>";
    }).join("") : '<span class="note">No seats change hands at this swing.</span>';
    var fc = document.getElementById("flip-count");
    if (fc) fc.textContent = flips.length + (flips.length === 1 ? " seat changes hands" : " seats change hands");
    document.querySelectorAll(".presets button").forEach(function (b) {
      b.classList.toggle("on", Math.abs(parseFloat(b.getAttribute("data-swing")) - swing) < 0.05);
    });
  }

  slider.addEventListener("input", function () { hideTip(); render(parseFloat(slider.value)); });
  document.querySelectorAll(".presets button").forEach(function (b) {
    b.addEventListener("click", function () { slider.value = b.getAttribute("data-swing"); render(parseFloat(slider.value)); centreOnSwing(); });
  });
  document.addEventListener("click", function (e) { if (!e.target.classList || !e.target.classList.contains("seat")) hideTip(); });
  render(current);
  centreOnSwing();
  if (scroller) scroller.addEventListener("scroll", hideTip, { passive: true });
})();
