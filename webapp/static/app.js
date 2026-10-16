/* TrueNest broker webapp — vanilla JS */
(function () {
  "use strict";

  var tg = window.Telegram && window.Telegram.WebApp;
  var qs = new URLSearchParams(location.search);
  var DEMO = qs.get("demo") === "1";
  var brokerId = null;
  var initData = "";

  // ---------- auth ----------
  if (tg && tg.initData) {
    initData = tg.initData;
    try {
      var u = tg.initDataUnsafe && tg.initDataUnsafe.user;
      if (u && u.id) brokerId = u.id;
    } catch (e) {}
    tg.ready();
    tg.expand();
  }
  if (DEMO) {
    brokerId = parseInt(qs.get("broker_id") || "0", 10) || null;
  }
  if (!brokerId) {
    document.getElementById("listing-list").innerHTML =
      '<div class="empty"><div class="big">🔒</div>' +
      "Mở web app từ bot Telegram để xem dữ liệu của bạn.<br><br>" +
      '<span style="font-size:12px">Hoặc thêm ?demo=1&broker_id=ID vào URL để test.</span></div>';
    return;
  }

  // ---------- http ----------
  function headers() {
    var h = { "Content-Type": "application/json" };
    if (initData) h["X-Telegram-Init-Data"] = initData;
    return h;
  }
  function api(path, opts) {
    opts = opts || {};
    var url = path + (path.indexOf("?") >= 0 ? "&" : "?") +
      "broker_id=" + brokerId + (DEMO ? "&demo=1" : "");
    return fetch(url, {
      method: opts.method || "GET",
      headers: headers(),
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    }).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    });
  }

  // ---------- ui helpers ----------
  function toast(msg) {
    var t = document.getElementById("toast");
    t.textContent = msg;
    t.classList.add("show");
    setTimeout(function () { t.classList.remove("show"); }, 2200);
    if (tg && tg.HapticFeedback) tg.HapticFeedback.notificationOccurred("success");
  }
  function show(id) {
    document.querySelectorAll(".view").forEach(function (v) {
      v.classList.remove("active");
    });
    document.getElementById(id).classList.add("active");
    window.scrollTo(0, 0);
  }
  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  // ---------- trial / upsell helpers ----------
  var TIER_LABEL = { pro: "Pro 💎", max: "Max 💎💎" };
  var TIER_PRICE = { pro: "99k/tháng", max: "199k/tháng" };
  var TRIAL_FEATURE_NAMES = {
    xbroker_match: "Match liên broker",
    send2client: "Gửi tin cho khách",
  };
  var _trialCache = {};

  function trialCheck(feature) {
    // GET /api/trial/<feature> — cached per session; use trialRefresh() to bust.
    if (_trialCache[feature]) return Promise.resolve(_trialCache[feature]);
    return api("/api/trial/" + feature).then(function (d) {
      _trialCache[feature] = d;
      return d;
    });
  }
  function trialRefresh(feature) {
    if (feature) delete _trialCache[feature];
    else _trialCache = {};
  }
  function trialUse(feature) {
    // POST /api/trial/<feature>/use — consume one trial use.
    return api("/api/trial/" + feature + "/use", { method: "POST" })
      .then(function (d) {
        trialRefresh(feature);
        return d;
      });
  }
  function trialBadgeHtml(trial) {
    // "Dùng thử: còn X/3 lượt" — hidden when unlimited (remaining === -1).
    if (!trial || trial.remaining < 0) return "";
    return '<span class="trial-badge">🎁 Dùng thử: còn ' +
      trial.remaining + "/" + trial.limit + " lượt</span>";
  }
  function showUpgradeModal(requiredTier, feature) {
    var old = document.getElementById("upgrade-modal");
    if (old) old.remove();
    var fname = TRIAL_FEATURE_NAMES[feature] || "Tính năng này";
    var label = TIER_LABEL[requiredTier] || requiredTier;
    var price = TIER_PRICE[requiredTier] || "";
    var m = document.createElement("div");
    m.id = "upgrade-modal";
    m.className = "modal-overlay";
    m.innerHTML =
      '<div class="modal">' +
      '<div class="modal-title">🔒 Hết lượt dùng thử</div>' +
      '<div class="modal-body">' + esc(fname) + " cần gói <b>" + esc(label) +
      "</b>" + (price ? " (" + esc(price) + ")" : "") + ".</div>" +
      '<button class="btn btn-primary" id="um-upgrade">⭐ Nâng cấp ngay</button>' +
      '<button class="btn" id="um-later">Để sau</button>' +
      "</div>";
    document.body.appendChild(m);
    document.getElementById("um-later").onclick = function () { m.remove(); };
    document.getElementById("um-upgrade").onclick = function () {
      m.remove();
      // Broker completes the upgrade inside the bot chat (/premium flow).
      toast("Mở bot và gõ /premium để nâng cấp ⭐");
      if (tg && tg.close) { setTimeout(function () { tg.close(); }, 1200); }
    };
    m.onclick = function (e) { if (e.target === m) m.remove(); };
  }
  function trialGate(feature, fn) {
    // Check trial before running fn. Shows upgrade modal when exhausted.
    // fn receives the trial status object.
    return trialCheck(feature).then(function (t) {
      if (!t.allowed) {
        showUpgradeModal(t.required_tier, feature);
        return null;
      }
      return fn(t);
    }).catch(function () { toast("Không kiểm tra được lượt dùng thử"); });
  }

  // ---------- list view ----------
  var state = { q: "", bedrooms: "", status: "", items: [] };

  function loadListings() {
    var params = "?limit=100";
    if (state.bedrooms) params += "&bedrooms=" + encodeURIComponent(state.bedrooms);
    if (state.status) params += "&status=" + encodeURIComponent(state.status);
    document.getElementById("listing-list").innerHTML =
      '<div class="loading">Đang tải...</div>';
    api("/api/listings" + params).then(function (data) {
      state.items = data.items || [];
      renderList();
    }).catch(function () {
      document.getElementById("listing-list").innerHTML =
        '<div class="empty"><div class="big">⚠️</div>Không tải được dữ liệu.</div>';
    });
  }

  function renderList() {
    var q = state.q.toLowerCase();
    var items = state.items.filter(function (i) {
      return !q || (i.title || "").toLowerCase().indexOf(q) >= 0;
    });
    var el = document.getElementById("listing-list");
    if (!items.length) {
      el.innerHTML = '<div class="empty"><div class="big">🏠</div>Chưa có căn nào.</div>';
      return;
    }
    el.innerHTML = items.map(function (i) {
      var badge = i.status === "rented"
        ? '<span class="badge rented">ĐÃ THUÊ</span>'
        : (i.has_post ? "" : '<span class="badge">MỚI</span>');
      var q = i.quality_score || 0;
      var qcls = q >= 80 ? "q-high" : (q >= 50 ? "q-mid" : "q-low");
      var score = '<span class="qscore ' + qcls + '" title="AI chấm điểm theo schema chuẩn">🤖 ' + q + "đ</span>";
      var meta = [i.bedroom_label];
      if (i.bathrooms) meta.push(i.bathrooms + " WC");
      if (i.area_m2) meta.push(i.area_m2 + "m²");
      if (i.photo_count) meta.push("📸 " + i.photo_count);
      // Show first R2 photo if available, else emoji placeholder.
      var img = (i.photo_urls && i.photo_urls.length)
        ? '<img class="card-photo" src="' + esc(i.photo_urls[0]) +
          '" alt="" loading="lazy" onerror="this.outerHTML=\'<div class=&quot;card-img&quot;>🏢</div>\'">'
        : '<div class="card-img">🏢</div>';
      return (
        '<div class="card" data-id="' + esc(i.id) + '">' +
        img +
        '<div class="card-body">' +
        '<div class="card-title">' + esc(i.title) + badge + score + "</div>" +
        '<div class="card-meta">' + esc(meta.join(" · ")) + "</div>" +
        '<div class="card-price">' + esc(i.price) + "/tháng</div>" +
        '<div class="card-actions">' +
        '<button class="btn" data-act="edit">✏️ Sửa</button>' +
        '<button class="btn btn-primary" data-act="post">📝 Bài đăng</button>' +
        "</div></div></div>"
      );
    }).join("");
  }

  document.getElementById("listing-list").addEventListener("click", function (e) {
    var card = e.target.closest(".card");
    if (!card) return;
    var id = card.getAttribute("data-id");
    var act = e.target.getAttribute("data-act");
    if (act === "edit") openEdit(id);
    else openDetail(id, act === "post" ? "post" : "info");
  });

  var searchTimer = null;
  document.getElementById("search").addEventListener("input", function (e) {
    clearTimeout(searchTimer);
    var v = e.target.value;
    searchTimer = setTimeout(function () {
      state.q = v;
      renderList();
    }, 250);
  });

  document.getElementById("filters").addEventListener("click", function (e) {
    var b = e.target.closest(".filter");
    if (!b) return;
    document.querySelectorAll("#filters .filter").forEach(function (x) {
      x.classList.remove("active");
    });
    b.classList.add("active");
    state.bedrooms = b.getAttribute("data-br") || "";
    state.status = b.getAttribute("data-st") || "";
    loadListings();
  });

  // ---------- detail view ----------
  var currentId = null;
  var currentLangs = [];
  var currentLang = "vi";

  function openDetail(id, tab) {
    currentId = id;
    api("/api/listing/" + id).then(function (d) {
      document.getElementById("detail-heading").textContent = d.title || "Chi tiết";
      renderInfo(d);
      currentLangs = d.post_langs || [];
      currentLang = currentLangs.indexOf("vi") >= 0 ? "vi" :
        (currentLangs[0] || "vi");
      renderPostTabs();
      loadPost();
      switchTab(tab || "info");
      show("view-detail");
    }).catch(function () { toast("Không tải được chi tiết"); });
  }

  function fmtVal(v) {
    if (v === null || v === undefined || v === "") return "—";
    return esc(v);
  }

  function renderInfo(d) {
    var rows = [
      ["💰 Giá", d.price + "/tháng"],
      ["🛏️ Phòng ngủ", d.bedroom_label],
      ["🛁 WC", d.bathrooms || "—"],
      ["📐 Diện tích", d.area_m2 ? d.area_m2 + "m²" : "—"],
      ["📍 Địa chỉ", d.address || "—"],
      ["🏢 Tòa nhà", d.building_name || "—"],
      ["📌 Quận", d.district || "—"],
      ["🛋️ Nội thất", d.furnished || "—"],
      ["🐾 Pet", d.pet_friendly === true ? "Cho nuôi" :
        d.pet_friendly === false ? "Không" : "—"],
      ["💵 Cọc", d.deposit || "—"],
      ["📸 Ảnh", d.photo_count + " ảnh"],
      ["📊 Trạng thái", statusLabel(d.status)],
    ];
    var html;
    // Photo gallery: R2 URLs if available, else placeholder.
    if (d.photo_urls && d.photo_urls.length) {
      html = '<div class="gallery">' + d.photo_urls.map(function (u, ix) {
        return '<img class="gallery-img" src="' + esc(u) + '" alt="" loading="lazy"' +
          (ix > 0 ? ' style="display:none"' : "") + '>';
      }).join("") + "</div>";
      if (d.photo_urls.length > 1) {
        html += '<div class="gallery-nav">' +
          '<button class="btn" id="g-prev">‹</button>' +
          '<span id="g-count">1/' + d.photo_urls.length + "</span>" +
          '<button class="btn" id="g-next">›</button></div>';
      }
      html += '<div class="detail-body">';
    } else {
      html = '<div class="detail-img">🏢</div><div class="detail-body">';
    }
    html +=
      '<div class="detail-title">' + esc(d.title) + "</div>" +
      '<div class="detail-price">' + esc(d.price) + "/tháng</div>";
    // quality score
    var qs = d.quality_score || 0;
    var qcls = qs >= 80 ? "q-high" : (qs >= 50 ? "q-mid" : "q-low");
    var qcol = qs >= 80 ? "var(--green)" : (qs >= 50 ? "#ffab00" : "var(--red)");
    html += '<div class="section-title">🤖 AI chấm điểm <span class="qscore ' + qcls + '">' + qs + "đ</span></div>" +
      '<div class="qbar"><div style="width:' + qs + '%;background:' + qcol + '"></div></div>';
    if (d.quality_missing && d.quality_missing.length) {
      html += '<div class="q-missing">Thiếu: <b>' + esc(d.quality_missing.join(", ")) + "</b></div>";
    } else {
      html += '<div class="q-missing">✅ Đầy đủ thông tin</div>';
    }
    html += '<div class="section-title" style="margin-top:12px">Thông số</div>' +
      rows.map(function (r) {
        return '<div class="spec"><span class="k">' + r[0] +
          '</span><span class="v">' + fmtVal(r[1]) + "</span></div>";
      }).join("");
    if (d.raw_text) {
      html += '<div class="section-title">Mô tả gốc</div>' +
        '<div class="desc">' + esc(d.raw_text) + "</div>";
    }
    html += '<div style="display:flex;gap:8px;margin-top:16px">' +
      '<button class="btn" id="d-edit">✏️ Sửa thông tin</button>';
    if (d.status === "rented") {
      html += '<button class="btn" id="d-unrent">↩️ Còn trống</button>';
    } else {
      html += '<button class="btn btn-danger" id="d-rent">✅ Đã cho thuê</button>';
    }
    html += "</div></div>";
    document.getElementById("detail-info").innerHTML = html;

    document.getElementById("d-edit").onclick = function () { openEdit(currentId); };
    var dr = document.getElementById("d-rent");
    if (dr) dr.onclick = function () { changeStatus("rented"); };
    var du = document.getElementById("d-unrent");
    if (du) du.onclick = function () { changeStatus("submitted"); };
    // gallery swipe buttons
    var gp = document.getElementById("g-prev");
    var gn = document.getElementById("g-next");
    if (gp && gn) {
      var imgs = document.querySelectorAll(".gallery-img");
      var idx = 0;
      var gc = document.getElementById("g-count");
      var showIx = function (n) {
        idx = (n + imgs.length) % imgs.length;
        imgs.forEach(function (im, k) {
          im.style.display = k === idx ? "" : "none";
        });
        if (gc) gc.textContent = (idx + 1) + "/" + imgs.length;
      };
      gp.onclick = function () { showIx(idx - 1); };
      gn.onclick = function () { showIx(idx + 1); };
    }
  }

  function statusLabel(s) {
    return { draft: "Nháp", pending_info: "Thiếu TT",
      submitted: "Còn trống", rented: "Đã thuê",
      negotiating: "Đang đàm phán", deposited: "Đã cọc" }[s] || s;
  }

  function changeStatus(s) {
    api("/api/listing/" + currentId + "/status", {
      method: "PUT", body: { status: s },
    }).then(function () {
      toast(s === "rented" ? "Đã đánh dấu cho thuê ✅" : "Đã mở lại ✅");
      openDetail(currentId, "info");
      loadListings();
    }).catch(function () { toast("Lỗi cập nhật trạng thái"); });
  }

  function switchTab(which) {
    var info = which === "info";
    document.getElementById("tab-info").classList.toggle("active", info);
    document.getElementById("tab-post").classList.toggle("active", !info);
    document.getElementById("detail-info").style.display = info ? "" : "none";
    document.getElementById("detail-post").style.display = info ? "none" : "";
  }
  document.getElementById("tab-info").onclick = function () { switchTab("info"); };
  document.getElementById("tab-post").onclick = function () { switchTab("post"); };
  document.getElementById("detail-back").onclick = function () { show("view-list"); };

  // ---------- post tab ----------
  var LANG_NAMES = { vi: "🇻🇳 VI", en: "🇬🇧 EN", ko: "🇰🇷 KO",
                     zh: "🇨🇳 ZH", ru: "🇷🇺 RU" };

  function renderPostTabs() {
    var el = document.getElementById("post-langs");
    if (!currentLangs.length) {
      el.innerHTML = '<span style="color:var(--muted);font-size:13px">' +
        "Chưa có bài đăng. Bài tiếng Việt tự tạo khi thêm căn mới.</span>";
      return;
    }
    el.innerHTML = currentLangs.map(function (l) {
      return '<button class="lang' + (l === currentLang ? " active" : "") +
        '" data-lang="' + l + '">' + (LANG_NAMES[l] || l) + "</button>";
    }).join("");
  }

  document.getElementById("post-langs").addEventListener("click", function (e) {
    var b = e.target.closest(".lang");
    if (!b) return;
    currentLang = b.getAttribute("data-lang");
    renderPostTabs();
    loadPost();
  });

  function loadPost() {
    document.getElementById("post-text").textContent = "Đang tải...";
    api("/api/post/" + currentId + "?lang=" + currentLang).then(function (d) {
      document.getElementById("post-text").textContent =
        d.text || "(chưa có bài " + currentLang + ")";
    }).catch(function () {
      document.getElementById("post-text").textContent = "Lỗi tải bài đăng.";
    });
  }

  document.getElementById("post-edit-btn").onclick = function () {
    document.getElementById("pe-lang").value = currentLang;
    api("/api/post/" + currentId + "?lang=" + currentLang).then(function (d) {
      document.getElementById("pe-text").value = d.text || "";
      document.getElementById("postedit-title").textContent =
        "Sửa bài đăng (" + currentLang.toUpperCase() + ")";
      show("view-postedit");
    });
  };
  document.getElementById("postedit-back").onclick = function () {
    show("view-detail");
  };
  document.getElementById("postedit-save").onclick = function () {
    var lang = document.getElementById("pe-lang").value;
    var text = document.getElementById("pe-text").value;
    api("/api/post/" + currentId, {
      method: "PUT", body: { lang: lang, text: text },
    }).then(function (d) {
      currentLangs = d.langs || [];
      currentLang = lang;
      renderPostTabs();
      loadPost();
      show("view-detail");
      switchTab("post");
      toast("Đã lưu bài đăng ✅");
    }).catch(function () { toast("Lỗi lưu bài đăng"); });
  };

  // ---------- edit view ----------
  var editReturnTo = null;  // {view: "propose", requestId} or null
  function openEdit(id, returnTo) {
    currentId = id;
    editReturnTo = returnTo || null;
    api("/api/listing/" + id).then(function (d) {
      document.getElementById("f-price").value =
        d.price_vnd ? (d.price_vnd / 1000000) : "";
      document.getElementById("f-area").value = d.area_m2 || "";
      var br = d.bedrooms;
      document.getElementById("f-bedrooms").value =
        (br === 0 || br === "0") ? "0" : (br != null ? String(Math.round(br)) : "");
      document.getElementById("f-bathrooms").value = d.bathrooms || "";
      document.getElementById("f-street").value = d.address || "";
      document.getElementById("f-building").value = d.building_name || "";
      document.getElementById("f-district").value = d.district || "";
      document.getElementById("f-deposit").value = d.deposit || "";
      document.getElementById("f-furnished").value = d.furnished || "";
      document.getElementById("f-pet").value =
        d.pet_friendly === true ? "1" : d.pet_friendly === false ? "0" : "";
      document.getElementById("f-desc").value = d.raw_text || "";
      show("view-edit");
    }).catch(function () { toast("Không tải được thông tin"); });
  }
  document.getElementById("edit-back").onclick = function () {
    if (editReturnTo && editReturnTo.view === "propose") {
      var rid = editReturnTo.requestId;
      editReturnTo = null;
      openPropose(rid);
    } else {
      show("view-detail");
    }
  };
  document.getElementById("edit-save").onclick = function () {
    var priceTr = parseFloat(document.getElementById("f-price").value);
    var fields = {
      price_vnd: isNaN(priceTr) ? null : Math.round(priceTr * 1000000),
      area_m2: parseFloat(document.getElementById("f-area").value) || null,
      bathrooms: parseFloat(document.getElementById("f-bathrooms").value) || null,
      street: document.getElementById("f-street").value.trim(),
      building_name: document.getElementById("f-building").value.trim(),
      district: document.getElementById("f-district").value.trim(),
      deposit: document.getElementById("f-deposit").value.trim(),
      furnished: document.getElementById("f-furnished").value,
      description: document.getElementById("f-desc").value.trim(),
    };
    var br = document.getElementById("f-bedrooms").value;
    fields.bedrooms = br === "" ? null : parseFloat(br);
    var pet = document.getElementById("f-pet").value;
    fields.pet_friendly = pet === "" ? null : pet === "1";
    // drop empty strings (keep nulls for numeric clears)
    Object.keys(fields).forEach(function (k) {
      if (fields[k] === "") fields[k] = null;
    });
    var btn = document.getElementById("edit-save");
    btn.disabled = true;
    btn.textContent = "Đang lưu...";
    api("/api/listing/" + currentId, {
      method: "PUT", body: { fields: fields },
    }).then(function () {
      toast("Đã lưu ✅");
      if (editReturnTo && editReturnTo.view === "propose") {
        var rid = editReturnTo.requestId;
        editReturnTo = null;
        openPropose(rid);  // refresh propose view with updated scores
      } else {
        openDetail(currentId, "info");
      }
      loadListings();
    }).catch(function () { toast("Lỗi lưu"); })
    .finally(function () {
      btn.disabled = false;
      btn.textContent = "💾 Lưu thay đổi";
    });
  };

  // ---------- placeholder tabs ----------
  ["tab-soon1", "tab-soon2", "tab-soon3"].forEach(function (id) {
    document.getElementById(id).onclick = function () {
      toast("Tính năng đang phát triển 🚧");
    };
  });

  // ---------- init ----------
  if (tg) {
    tg.BackButton.onClick(function () { show("view-list"); });
  }
  // Deep links: ?view=listing&id=<id>[&tab=post], ?view=batch&ids=id1,id2,
  // ?view=propose&request_id=<rid>, or ?view=intake[&return=<url>]
  var dlView = qs.get("view");
  var dlId = qs.get("id");
  var dlIds = qs.get("ids");
  var dlTab = qs.get("tab") || "info";
  var dlReqId = qs.get("request_id");
  var dlReturn = qs.get("return");
  if (dlView === "propose" && dlReqId) {
    openPropose(dlReqId);
  } else if (dlView === "xbroker") {
    openXbroker();
  } else if (dlView === "intake") {
    openIntake(dlReturn);
  } else if (dlView === "listing" && dlId) {
    openDetail(dlId, dlTab);
    // also load list in background for back navigation
    loadListings();
  } else if (dlView === "batch" && dlIds) {
    loadBatch(dlIds);
  } else {
    loadListings();
  }

  // ---------- propose view (broker picks listings after reserving slot) ----------
  var proposeState = null;
  var proposeTimer = null;

  function openPropose(requestId) {
    document.getElementById("propose-body").innerHTML =
      '<div class="loading">Đang tải...</div>';
    show("view-propose");
    api("/api/propose/" + encodeURIComponent(requestId)).then(function (d) {
      if (d.error) {
        document.getElementById("propose-body").innerHTML =
          '<div class="empty"><div class="big">⚠️</div>' +
          esc(d.error_vi || "Không tải được yêu cầu.") + "</div>";
        return;
      }
      proposeState = {
        requestId: requestId,
        request: d.request,
        hasSlot: d.has_slot,
        slotReleased: d.slot_released || false,
        maxListings: d.max_listings || 5,
        listings: d.listings || [],
        failedSummary: d.failed_summary || {},
        selected: {},
        submitted: false,
        expanded: {},
        qExpanded: {},
        showAll: false,
      };
      // pre-select already submitted
      (d.already_submitted || []).forEach(function (id) {
        proposeState.selected[id] = true;
      });
      renderPropose();
      startProposeTimer();
    }).catch(function () {
      document.getElementById("propose-body").innerHTML =
        '<div class="empty"><div class="big">⚠️</div>Không tải được dữ liệu.</div>';
    });
  }

  function proposeCountdown() {
    if (!proposeState || !proposeState.request.expires_at) return "";
    var left = Math.max(0, proposeState.request.expires_at - Date.now() / 1000);
    var m = Math.floor(left / 60), s = Math.floor(left % 60);
    return { text: "⏰ Còn " + m + " phút " + s + " giây", urgent: left < 600, left: left };
  }

  function startProposeTimer() {
    if (proposeTimer) clearInterval(proposeTimer);
    proposeTimer = setInterval(function () {
      if (!proposeState || proposeState.submitted) {
        clearInterval(proposeTimer);
        return;
      }
      var cd = proposeCountdown();
      var el = document.getElementById("propose-timer");
      if (el && cd) {
        el.innerHTML = esc(cd.text);
        el.className = "propose-timer" + (cd.urgent ? " urgent" : "");
      }
      if (cd && cd.left <= 0) {
        clearInterval(proposeTimer);
        autoSubmitPropose();
      }
    }, 1000);
  }

  function autoSubmitPropose() {
    var ids = Object.keys(proposeState.selected);
    toast("Hết giờ, đã tự động gửi " + ids.length + " tin ⏰");
    submitPropose(true);
  }

  function fmtBR(v) {
    if (v === 0 || v === "0") return "Studio";
    return v + "PN";
  }
  function fmtTr(v) {
    var t = v / 1000000;
    return (t % 1 === 0 ? t.toFixed(0) : t.toFixed(1)) + "tr";
  }
  function proposeCriteriaHtml(fs, req) {
    var lines = [];
    if (fs.bedrooms) {
      var have = (fs.bedrooms.have || []).map(fmtBR).join(", ");
      lines.push("• " + fmtBR(fs.bedrooms.required) +
        (have ? " (bạn có: " + esc(have) + ")" : " (tin của bạn thiếu thông tin)"));
    }
    if (fs.budget) {
      var over = (fs.budget.over || []).map(fmtTr).join(", ");
      lines.push("• Dưới " + fmtTr(fs.budget.max) +
        (over ? " (tin bạn: " + esc(over) + ")" : " (tin của bạn thiếu giá)"));
    }
    if (fs.district) {
      var dhave = (fs.district.have || []).join(", ");
      lines.push("• " + esc(fs.district.required) +
        (dhave ? " (tin bạn: " + esc(dhave) + ")" : " (tin của bạn thiếu khu vực)"));
    }
    if (fs.property_type) {
      var phave = (fs.property_type.have || []).join(", ");
      lines.push("• Loại: " + esc(fs.property_type.required) +
        (phave ? " (tin bạn: " + esc(phave) + ")" : ""));
    }
    if (fs.status) {
      lines.push("• " + fs.status.failed +
        " tin chưa đủ điều kiện (nháp/đã thuê)");
    }
    return lines.map(function (l) {
      return '<div class="propose-criterion">' + l + "</div>";
    }).join("");
  }

  // ---------- xbroker view (cross-broker match for missed slots) ----------
  function openXbroker() {
    document.getElementById("xbroker-body").innerHTML =
      '<div class="loading">Đang tải...</div>';
    show("view-xbroker");
    // Trial gate: 3 free uses of xbroker_match, then Max required
    trialGate("xbroker_match", function (trial) {
      api("/api/xbroker").then(function (d) {
        renderXbroker(d, trial);
      }).catch(function () {
        document.getElementById("xbroker-body").innerHTML =
          '<div class="empty"><div class="big">⚠️</div>Không tải được dữ liệu.</div>';
      });
    });
  }

  function renderXbroker(d, trial) {
    var reqs = d.requests || [];
    var html = "";
    // Trial badge
    if (trial && trial.remaining >= 0) {
      html += '<div class="trial-badge">🎁 Dùng thử: còn ' + trial.remaining +
        '/3 lượt</div>';
    }
    html += '<div class="propose-mechanism">' +
      "ℹ️ <b>Match liên broker</b><br>" +
      "• Các yêu cầu đang mở mà bạn chưa phản hồi<br>" +
      "• Chọn tin phù hợp từ kho của bạn để đề xuất<br>" +
      "• Không cần reserve slot trước" +
      "</div>";
    if (!reqs.length) {
      html += '<div class="empty"><div class="big">📭</div>' +
        "Hiện không có yêu cầu nào cần hỗ trợ.<br>" +
        "Theo dõi kênh broadcast để không bỏ lỡ nhé!</div>";
    } else {
      html += reqs.map(function (r) {
        var spots = (r.max_responders || 3) - (r.response_count || 0);
        return '<div class="card"><div class="card-body">' +
          '<div class="card-title">🔍 ' + esc(r.summary) + "</div>" +
          '<div class="card-meta">' +
          (r.bedrooms ? esc(fmtBR(r.bedrooms)) + " · " : "") +
          (r.budget_max ? "≤ " + esc(fmtTr(r.budget_max)) + " · " : "") +
          (r.district ? esc(r.district) : "") +
          "</div>" +
          '<div class="card-meta">👥 ' + (r.response_count || 0) + "/" +
          (r.max_responders || 3) + " đã phản hồi" +
          (spots > 0 ? ' · <b>' + spots + " slot trống</b>" : "") +
          "</div>" +
          '<div class="card-actions">' +
          '<button class="btn btn-primary" data-xb="' + esc(r.id) + '">' +
          "🏠 Đề xuất tin</button>" +
          "</div></div></div>";
      }).join("");
    }
    document.getElementById("xbroker-body").innerHTML = html;
    // Wire propose buttons: consume trial on click, then open propose view
    document.getElementById("xbroker-body").addEventListener("click", function (e) {
      var b = e.target.closest("[data-xb]");
      if (!b) return;
      var rid = b.getAttribute("data-xb");
      trialUse("xbroker_match").then(function () {
        openPropose(rid);
      }).catch(function () {
        showUpgradeModal("max", "xbroker_match");
      });
    });
  }

  var intakeReturnUrl = null;
  function openIntake(returnUrl) {    intakeReturnUrl = returnUrl || null;
    document.getElementById("intake-body").innerHTML =
      '<div class="empty"><div class="big">📝</div>' +
      "<b>Nhập tin mới từ bot</b><br><br>" +
      "Quay lại chat với em Linh và forward tin nhắn " +
      "hoặc gửi ảnh + mô tả như bình thường nhé.<br><br>" +
      "Tin mới sẽ tự động vào kho của anh." +
      (intakeReturnUrl
        ? '<br><br><button class="btn btn-primary" id="intake-back" ' +
          'style="width:100%">⬅️ Quay lại đề xuất</button>'
        : "") +
      "</div>";
    show("view-intake");
    var back = document.getElementById("intake-back");
    if (back) {
      back.onclick = function () {
        var m = /request_id=([^&]+)/.exec(intakeReturnUrl || "");
        if (m) openPropose(decodeURIComponent(m[1]));
        else show("view-list");
      };
    }
  }

  function renderPropose() {
    var st = proposeState;
    var req = st.request;
    var body = document.getElementById("propose-body");

    if (!st.hasSlot) {
      body.innerHTML = '<div class="empty"><div class="big">🔒</div>' +
        "Anh chưa giữ slot cho yêu cầu này.</div>";
      return;
    }
    if (req.expired) {
      body.innerHTML = '<div class="empty"><div class="big">⏰</div>' +
        "Hết giờ rồi ạ, slot đã chuyển cho người tiếp theo.</div>";
      return;
    }
    if (st.submitted) {
      var n = Object.keys(st.selected).length;
      body.innerHTML = '<div class="propose-done"><div class="big">✅</div>' +
        "<h3>Đã gửi " + n + " tin, chờ khách duyệt</h3>" +
        '<p style="color:var(--muted)">Em sẽ báo khi có kết quả.</p></div>';
      return;
    }

    var cd = proposeCountdown();
    var html = '<div class="propose-mechanism">' +
      '<div class="propose-mech-title">ℹ️ Cơ chế đề xuất</div>' +
      '<div class="propose-mech-body">' +
      "• Ai cũng có quyền reserve — 5 người nhanh nhất được chọn<br>" +
      "• Spot đóng 1 giờ sau broadcast<br>" +
      "• Khách chọn dựa trên: chất lượng tin (điểm AI) + độ đầy đủ thông tin<br>" +
      "• Tin càng đầy đủ → càng dễ được khách chọn" +
      "</div></div>" +
      '<div class="propose-head">' +
      '<div class="propose-req">Cần: ' + esc(req.summary || req.requirements_raw || "—") + "</div>" +
      (cd ? '<div class="propose-timer' + (cd.urgent ? " urgent" : "") +
       '" id="propose-timer">' + esc(cd.text) + "</div>" : "") +
      "</div>" +
      '<div class="propose-sort">Sắp xếp theo: điểm match × điểm chất lượng</div>';

    if (!st.listings.length) {
      var fs = st.failedSummary || {};
      var fsKeys = Object.keys(fs);
      // Slot released notice (Khanh 2026-10-16): broker's inventory had 0
      // eligible listings, so their slot was freed for others.
      if (st.slotReleased) {
        html += '<div class="propose-warn">📢 Slot của bạn đã được giải phóng'
          + " vì không có tin nào đạt tiêu chí.<br>"
          + "Slot đã mở lại cho broker khác trong kênh.</div>";
      }
      if (fsKeys.length) {
        // Hard-filtered out everything — show which criteria failed.
        html += '<div class="empty"><div class="big">😔</div>' +
          "<b>Không có tin nào đạt tiêu chí của lead</b></div>" +
          '<div class="propose-criteria"><div class="section-title">Tiêu chí cứng:</div>' +
          proposeCriteriaHtml(fs, st.request.requirements || {}) +
          "</div>" +
          '<button class="btn btn-primary" id="propose-addnew" ' +
          'style="width:100%;margin-top:12px">➕ Thêm tin mới phù hợp</button>';
        body.innerHTML = html;
        document.getElementById("propose-addnew").onclick = function () {
          openIntake("?view=propose&request_id=" +
            encodeURIComponent(st.requestId));
        };
      } else {
        html += '<div class="empty"><div class="big">🏠</div>' +
          "Anh chưa có tin nào trong kho.<br>Gửi tin vào bot trước đã nhé! 📝</div>";
        body.innerHTML = html;
      }
      return;
    }

    var visible = st.showAll ? st.listings : st.listings.slice(0, 10);
    html += visible.map(function (l) {
      var sel = st.selected[l.id];
      var exp = st.expanded[l.id];
      var qExp = st.qExpanded[l.id];
      var img = (l.photo_urls && l.photo_urls.length)
        ? '<img class="propose-img" src="' + esc(l.photo_urls[0]) +
          '" loading="lazy" onerror="this.outerHTML=\'<div class=&quot;propose-img-ph&quot;>🏢</div>\'">'
        : '<div class="propose-img-ph">🏢</div>';
      var q = l.quality_score || 0;
      var card = '<div class="propose-card' + (sel ? " selected" : "") +
        '" data-id="' + esc(l.id) + '">' +
        '<div class="propose-check">' + (sel ? "☑️" : "☐") + "</div>" +
        img +
        '<div class="propose-info">' +
        '<div class="propose-title">' + esc(l.title) + "</div>" +
        '<div class="propose-meta">' + esc(l.price) + "/tháng</div>" +
        '<div class="propose-scores">🎯 Match ' + (l.match_score || 0) +
        "% · 🤖 " + q + "đ</div>";
      // Quality improvement suggestions (Khanh 2026-10-16)
      if (q < 80 && l.quality_missing && l.quality_missing.length) {
        if (qExp) {
          card += '<div class="propose-qtip">' +
            '<div class="propose-qtip-title">💡 Để tăng khả năng được chọn:</div>' +
            l.quality_missing.map(function (m) {
              return '<div class="propose-qtip-item">• ' + esc(m.label) +
                " (+" + m.weight + "đ)</div>";
            }).join("") +
            '<div class="propose-qtip-potential">→ Có thể đạt ' +
            (l.potential_score || q) + "đ (hiện tại " + q + "đ)</div>" +
            '<button class="btn btn-sm propose-qfix" data-id="' + esc(l.id) +
            '">✏️ Bổ sung ngay</button>' +
            '<div class="propose-expand propose-q-toggle">▴ Ẩn gợi ý</div></div>';
        } else {
          card += '<div class="propose-expand propose-q-toggle">💡 Cách tăng điểm</div>';
        }
      }
      if (exp) {
        card += '<div class="propose-detail">' +
          (l.photo_count ? "📸 " + l.photo_count + " ảnh<br>" : "") +
          (l.district ? "📍 " + esc(l.district) + "<br>" : "") +
          (l.area_m2 ? "📐 " + l.area_m2 + "m²<br>" : "") +
          (l.bedroom_label ? "🛏️ " + esc(l.bedroom_label) : "") +
          "</div>" +
          '<div class="propose-expand">▴ Thu gọn</div>';
      } else {
        card += '<div class="propose-expand">▾ Xem chi tiết</div>';
      }
      card += "</div></div>";
      return card;
    }).join("");

    if (!st.showAll && st.listings.length > 10) {
      html += '<button class="btn" id="propose-more" style="width:100%;margin-bottom:10px">' +
        "Xem thêm " + (st.listings.length - 10) + " tin khác</button>";
    }

    var nSel = Object.keys(st.selected).length;
    html += '<div class="propose-bar">' +
      '<div class="propose-count">Đã chọn ' + nSel + "/" + st.maxListings + " tin</div>" +
      '<button class="btn btn-primary" id="propose-submit" ' +
      (nSel ? "" : "disabled") + ">📤 Gửi đề xuất</button></div>";

    body.innerHTML = html;

    // wire events
    body.querySelectorAll(".propose-card").forEach(function (card) {
      card.onclick = function (e) {
        var id = card.getAttribute("data-id");
        // quality tip toggle
        if (e.target.classList.contains("propose-q-toggle")) {
          st.qExpanded[id] = !st.qExpanded[id];
          renderPropose();
          return;
        }
        // "Bổ sung ngay" — stop propagation, open edit with return
        if (e.target.classList.contains("propose-qfix")) {
          e.stopPropagation();
          openEdit(id, { view: "propose", requestId: st.requestId });
          return;
        }
        // toggle expand on "xem chi tiết" click, else toggle select
        if (e.target.classList.contains("propose-expand")) {
          st.expanded[id] = !st.expanded[id];
        } else {
          if (st.selected[id]) {
            delete st.selected[id];
          } else {
            if (Object.keys(st.selected).length >= st.maxListings) {
              toast("Tối đa " + st.maxListings + " tin");
              return;
            }
            st.selected[id] = true;
          }
          st.warnedLowQ = false;  // re-check on selection change
        }
        renderPropose();
      };
    });
    var more = document.getElementById("propose-more");
    if (more) more.onclick = function () { st.showAll = true; renderPropose(); };
    var sub = document.getElementById("propose-submit");
    if (sub) sub.onclick = function () { proposePreSubmitCheck(); };
  }

  function proposePreSubmitCheck() {
    var st = proposeState;
    var lowQ = Object.keys(st.selected).filter(function (id) {
      var l = st.listings.find(function (x) { return x.id === id; });
      return l && (l.quality_score || 0) < 50;
    });
    if (lowQ.length && !st.warnedLowQ) {
      st.warnedLowQ = true;
      var body = document.getElementById("propose-body");
      var warn = document.createElement("div");
      warn.className = "propose-warn";
      warn.id = "propose-lowq-warn";
      warn.innerHTML =
        "⚠️ " + lowQ.length + " tin bạn chọn có điểm dưới 50đ<br>" +
        "Tin điểm thấp khó được khách chọn.<br>" +
        '<div style="display:flex;gap:8px;margin-top:10px">' +
        '<button class="btn" id="propose-improve">💡 Cải thiện trước</button>' +
        '<button class="btn btn-primary" id="propose-sendanyway">Vẫn gửi</button>' +
        "</div>";
      body.insertBefore(warn, body.firstChild);
      warn.scrollIntoView({ behavior: "smooth", block: "start" });
      document.getElementById("propose-improve").onclick = function () {
        warn.remove();
        // expand quality tips for low-score selected listings
        lowQ.forEach(function (id) { st.qExpanded[id] = true; });
        renderPropose();
        // re-add the warning state so it doesn't re-trigger
        st.warnedLowQ = true;
      };
      document.getElementById("propose-sendanyway").onclick = function () {
        warn.remove();
        submitPropose(false);
      };
      return;
    }
    submitPropose(false);
  }

  function submitPropose(isAuto) {
    var st = proposeState;
    var ids = Object.keys(st.selected);
    api("/api/propose/" + encodeURIComponent(st.requestId),
        { method: "POST", body: { listing_ids: ids } }).then(function (d) {
      if (d.error) {
        toast(d.error_vi || "Gửi thất bại");
        return;
      }
      st.submitted = true;
      if (proposeTimer) clearInterval(proposeTimer);
      if (!isAuto) toast("Đã gửi " + d.submitted_count + " tin ✅");
      renderPropose();
    }).catch(function () {
      toast("Gửi thất bại, thử lại nhé");
    });
  }

  function loadBatch(ids) {
    document.getElementById("listing-list").innerHTML =
      '<div class="loading">Đang tải...</div>';
    api("/api/listings?limit=100&ids=" + encodeURIComponent(ids)).then(function (data) {
      state.items = data.items || [];
      renderList();
      var n = state.items.length;
      toast(n ? ("Đã nhập " + n + " căn trong đợt này ✅") : "Không tìm thấy căn nào");
    }).catch(function () {
      document.getElementById("listing-list").innerHTML =
        '<div class="empty"><div class="big">⚠️</div>Không tải được dữ liệu.</div>';
    });
  }
})();
