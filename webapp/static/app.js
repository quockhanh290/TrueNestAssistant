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

  // ---------- bottom nav is wired in the new-views section ----------

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
        staleCount: d.stale_count || 0,
        staleIds: d.stale_ids || [],
        cooldownUntil: d.propose_cooldown_until || 0,
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

    // Stale listings banner (Khanh 2026-10-16, revised): >60-day listings
    // are hidden from propose and require re-verification.
    if (st.staleCount > 0) {
      html += '<div class="propose-warn">⚠️ ' + st.staleCount +
        " tin của anh quá cũ (&gt;60 ngày) nên bị ẩn<br>" +
        "Hãy kiểm tra thực tế rồi cập nhật để mở lại.<br>" +
        '<button class="btn btn-primary btn-sm" id="propose-refresh-all" ' +
        'style="margin-top:8px">🔄 Kiểm tra &amp; cập nhật</button></div>';
    }

    // Propose cooldown banner (Khanh 2026-10-16): 3 false refresh claims
    // -> 7-day propose ban.
    if (st.cooldownUntil && st.cooldownUntil > Date.now() / 1000) {
      var cd = new Date(st.cooldownUntil * 1000);
      var cstr = ("0" + cd.getDate()).slice(-2) + "/" +
        ("0" + (cd.getMonth() + 1)).slice(-2) + "/" + cd.getFullYear();
      html += '<div class="propose-warn">🔒 Anh đang bị hạn chế đề xuất đến ' +
        esc(cstr) + " do báo sai trạng thái tin 3 lần.</div>";
      body.innerHTML = html;
      return;
    }

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
        "% · 🤖 " + q + "đ" +
        (l.freshness_emoji
          ? ' · <span class="propose-fresh" title="' +
            esc(l.freshness_label || "") + '">' +
            esc(l.freshness_emoji) + " " +
            esc(Math.floor(l.age_days || 0) + " ngày") + "</span>"
          : "") +
        "</div>";
      // Freshness nudge (Khanh 2026-10-16, revised): push brokers to keep
      // status fresh. 30-60d listings are NOT hidden (market reality) but
      // get a 0.5 multiplier + warning.
      var fe = l.freshness_emoji || "";
      if (fe === "🟡" || fe === "🟠" || fe === "🔴") {
        card += '<div class="propose-fresh-tip">💡 Cập nhật trạng thái để tăng độ tin cậy' +
          ' <button class="btn btn-sm propose-refresh" data-id="' + esc(l.id) +
          '" data-title="' + esc(l.title) + '">🔄 Cập nhật</button></div>';
      }
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
        // "Cập nhật" freshness — stop propagation, open verify modal
        if (e.target.classList.contains("propose-refresh")) {
          e.stopPropagation();
          refreshProposeListing(id,
            e.target.getAttribute("data-title") || "");
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
    var rAll = document.getElementById("propose-refresh-all");
    if (rAll) rAll.onclick = function () { refreshAllStale(); };
    var sub = document.getElementById("propose-submit");
    if (sub) sub.onclick = function () { proposePreSubmitCheck(); };
  }

  function refreshProposeListing(id, title) {
    // Confirmation modal (Khanh 2026-10-16, revised): refresh is NOT 1-tap.
    // Broker must confirm real-world verification; false claims are penalized.
    var st = proposeState;
    var ov = document.createElement("div");
    ov.className = "modal-overlay";
    ov.innerHTML =
      '<div class="modal">' +
      "<h3>🔄 Cập nhật tin</h3>" +
      '<p><b>"' + esc(title || id) + '"</b></p>' +
      "<p>Anh đã kiểm tra thực tế tin này chưa?</p>" +
      '<button class="btn btn-primary" id="rf-available" ' +
      'style="width:100%;margin-bottom:8px">✅ Còn trống — cập nhật</button>' +
      '<button class="btn" id="rf-rented" ' +
      'style="width:100%;margin-bottom:8px">❌ Đã cho thuê</button>' +
      '<button class="btn" id="rf-cancel" ' +
      'style="width:100%">Để sau</button>' +
      '<p class="modal-warn">⚠️ Lưu ý: Cập nhật mà không kiểm tra thực tế, ' +
      "nếu bị phát hiện sẽ bị trừ điểm uy tín và ảnh hưởng chất lượng hồ sơ của anh.</p>" +
      "</div>";
    document.getElementById("propose-body").appendChild(ov);
    function close() { ov.remove(); }
    function send(status) {
      api("/api/listing/" + encodeURIComponent(id) + "/refresh",
          { method: "POST", body: { status: status } }).then(function (d) {
        close();
        if (d.error) {
          toast(d.error_vi || "Cập nhật thất bại");
          return;
        }
        if (status === "rented") {
          toast("Đã đánh dấu đã cho thuê.");
        } else {
          toast("Đã cập nhật ✅" + (d.warning_vi ? " " + d.warning_vi : ""));
        }
        openPropose(st.requestId);  // reload: ages + scores recomputed
      }).catch(function () {
        close();
        toast("Cập nhật thất bại");
      });
    }
    ov.querySelector("#rf-available").onclick = function () { send("available"); };
    ov.querySelector("#rf-rented").onclick = function () { send("rented"); };
    ov.querySelector("#rf-cancel").onclick = close;
    ov.onclick = function (e) { if (e.target === ov) close(); };
  }

  function refreshAllStale() {
    // Bulk refresh (Khanh 2026-10-16, revised): one confirmation modal for
    // all stale listings — broker confirms real-world verification.
    var st = proposeState;
    var ids = st.staleIds || [];
    if (!ids.length) return;
    var ov = document.createElement("div");
    ov.className = "modal-overlay";
    ov.innerHTML =
      '<div class="modal">' +
      "<h3>🔄 Cập nhật " + ids.length + " tin cũ?</h3>" +
      "<p>Anh đã kiểm tra thực tế các tin này chưa?</p>" +
      '<button class="btn btn-primary" id="rf-all-available" ' +
      'style="width:100%;margin-bottom:8px">✅ Tất cả còn trống — cập nhật</button>' +
      '<button class="btn" id="rf-all-cancel" ' +
      'style="width:100%">Để sau</button>' +
      '<p class="modal-warn">⚠️ Lưu ý: Cập nhật mà không kiểm tra thực tế, ' +
      "nếu bị phát hiện sẽ bị trừ điểm uy tín và ảnh hưởng chất lượng hồ sơ của anh.</p>" +
      "</div>";
    document.getElementById("propose-body").appendChild(ov);
    function close() { ov.remove(); }
    ov.querySelector("#rf-all-cancel").onclick = close;
    ov.onclick = function (e) { if (e.target === ov) close(); };
    ov.querySelector("#rf-all-available").onclick = function () {
      ov.querySelector("#rf-all-available").disabled = true;
      toast("Đang cập nhật " + ids.length + " tin...");
      var done = 0;
      (function next(i) {
        if (i >= ids.length) {
          close();
          toast("Đã cập nhật " + done + "/" + ids.length + " tin ✅");
          openPropose(st.requestId);  // reload: stale listings reappear
          return;
        }
        api("/api/listing/" + encodeURIComponent(ids[i]) + "/refresh",
            { method: "POST", body: { status: "available" } }).then(function (d) {
          if (!d.error) done++;
          next(i + 1);
        }).catch(function () { next(i + 1); });
      })(0);
    };
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

  // ============================================================
  // NEW VIEWS (2026-10-16): navigation, filter sheet, clients,
  // suggest, share-create, profile, upgrade, commission, notify
  // ============================================================

  // ---------- bottom nav ----------
  function navTo(view) {
    ["nav-listings", "nav-clients", "nav-more"].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.classList.remove("active");
    });
    if (view === "view-list") {
      document.getElementById("nav-listings").classList.add("active");
      show("view-list");
      loadListings();
    } else if (view === "view-clients") {
      document.getElementById("nav-clients").classList.add("active");
      openClients();
    }
  }
  document.getElementById("nav-listings").onclick = function () { navTo("view-list"); };
  document.getElementById("nav-clients").onclick = function () { navTo("view-clients"); };
  document.getElementById("nav-more").onclick = function () {
    document.getElementById("more-menu").style.display = "flex";
  };
  document.getElementById("menu-close").onclick = function () {
    document.getElementById("more-menu").style.display = "none";
  };
  document.getElementById("more-menu").onclick = function (e) {
    if (e.target === this) this.style.display = "none";
  };
  document.getElementById("avatar-btn").onclick = function () { openProfile(); };
  function closeMore() {
    document.getElementById("more-menu").style.display = "none";
  }

  // ---------- ⋯ menu wiring ----------
  document.getElementById("menu-commission").onclick = function () {
    closeMore(); openCommission();
  };
  document.getElementById("menu-xbroker").onclick = function () {
    closeMore();
    document.getElementById("nav-more").classList.add("active");
    openXbroker();
  };
  document.getElementById("menu-upgrade").onclick = function () {
    closeMore(); openUpgrade();
  };
  document.getElementById("menu-notify").onclick = function () {
    closeMore(); openNotifySettings();
  };
  document.getElementById("menu-profile").onclick = function () {
    closeMore(); openProfile();
  };

  // ---------- filter bottom sheet ----------
  var advFilters = {
    min_price: null, max_price: null, bedrooms: [],
    district: "", furnishing: "", pet: false,
    min_area: null, min_score: null, status: "",
  };

  var FILTER_GROUPS = [
    { key: "price", icon: "💰", title: "Giá thuê (triệu/tháng)", type: "range",
      fields: ["min_price", "max_price"], placeholders: ["Từ", "Đến"] },
    { key: "rooms", icon: "🛏️", title: "Phòng ngủ", type: "chips",
      field: "bedrooms",
      options: [["0", "Studio"], ["1", "1PN"], ["2", "2PN"],
                ["3", "3PN"], ["4", "4PN+"]] },
    { key: "location", icon: "📍", title: "Quận", type: "select",
      field: "district",
      options: [["", "—"], ["Ngũ Hành Sơn", "Ngũ Hành Sơn"],
                ["Sơn Trà", "Sơn Trà"], ["Hải Châu", "Hải Châu"],
                ["Thanh Khê", "Thanh Khê"], ["Liên Chiểu", "Liên Chiểu"],
                ["Cẩm Lệ", "Cẩm Lệ"]] },
    { key: "amenities", icon: "✨", title: "Tiện ích", type: "amenities" },
    { key: "quality", icon: "🤖", title: "Chất lượng AI", type: "chips",
      field: "min_score",
      options: [["", "Tất cả"], ["50", "≥50đ"], ["70", "≥70đ"], ["80", "≥80đ"]] },
    { key: "status", icon: "📊", title: "Trạng thái", type: "chips",
      field: "status",
      options: [["", "Tất cả"], ["submitted", "Còn trống"],
                ["rented", "Đã cho thuê"]] },
  ];

  function renderFilterGroups() {
    var el = document.getElementById("filter-groups");
    el.innerHTML = FILTER_GROUPS.map(function (g) {
      var body = "";
      if (g.type === "range") {
        body = '<div class="frange">' +
          '<input type="number" inputmode="decimal" id="ff-min_price" ' +
          'placeholder="' + g.placeholders[0] + '" value="' +
          (advFilters.min_price || "") + '">' +
          '<span>—</span>' +
          '<input type="number" inputmode="decimal" id="ff-max_price" ' +
          'placeholder="' + g.placeholders[1] + '" value="' +
          (advFilters.max_price || "") + '">' +
          "</div>";
      } else if (g.type === "chips") {
        body = '<div class="fchips">' + g.options.map(function (o) {
          var active;
          if (g.field === "bedrooms") {
            active = advFilters.bedrooms.indexOf(o[0]) >= 0;
          } else {
            active = String(advFilters[g.field] || "") === o[0];
          }
          return '<button class="fchip' + (active ? " active" : "") +
            '" data-fgroup="' + g.key + '" data-fval="' + esc(o[0]) + '">' +
            esc(o[1]) + "</button>";
        }).join("") + "</div>";
      } else if (g.type === "select") {
        body = '<select id="ff-district" class="fselect">' +
          g.options.map(function (o) {
            return '<option value="' + esc(o[0]) + '"' +
              (advFilters.district === o[0] ? " selected" : "") + ">" +
              esc(o[1]) + "</option>";
          }).join("") + "</select>";
      } else if (g.type === "amenities") {
        body = '<div class="fchips">' +
          '<button class="fchip' + (advFilters.furnishing === "full" ? " active" : "") +
          '" data-fgroup="amenities" data-fval="furn_full">Full nội thất</button>' +
          '<button class="fchip' + (advFilters.pet ? " active" : "") +
          '" data-fgroup="amenities" data-fval="pet">Cho nuôi pet</button>' +
          '<button class="fchip' + (advFilters.min_area === 50 ? " active" : "") +
          '" data-fgroup="amenities" data-fval="area50">≥50m²</button>' +
          "</div>";
      }
      return '<div class="fgroup"><div class="fgroup-title">' + g.icon +
        " " + g.title + "</div>" + body + "</div>";
    }).join("");
  }

  document.getElementById("open-filter").onclick = function () {
    renderFilterGroups();
    document.getElementById("filter-sheet").style.display = "flex";
  };
  document.getElementById("filter-sheet").onclick = function (e) {
    if (e.target === this) this.style.display = "none";
    var chip = e.target.closest(".fchip");
    if (!chip) return;
    var gv = chip.getAttribute("data-fval");
    var gk = chip.getAttribute("data-fgroup");
    if (gk === "rooms") {
      var ix = advFilters.bedrooms.indexOf(gv);
      if (ix >= 0) advFilters.bedrooms.splice(ix, 1);
      else advFilters.bedrooms.push(gv);
    } else if (gk === "amenities") {
      if (gv === "furn_full") {
        advFilters.furnishing = advFilters.furnishing === "full" ? "" : "full";
      } else if (gv === "pet") {
        advFilters.pet = !advFilters.pet;
      } else if (gv === "area50") {
        advFilters.min_area = advFilters.min_area === 50 ? null : 50;
      }
    } else if (gk === "quality") {
      advFilters.min_score = gv === "" ? null : parseFloat(gv);
    } else if (gk === "status") {
      advFilters.status = gv;
    }
    renderFilterGroups();
  };
  document.getElementById("filter-clear").onclick = function () {
    advFilters = { min_price: null, max_price: null, bedrooms: [],
      district: "", furnishing: "", pet: false,
      min_area: null, min_score: null, status: "" };
    renderFilterGroups();
  };
  document.getElementById("filter-apply").onclick = function () {
    var mp = document.getElementById("ff-min_price");
    var xp = document.getElementById("ff-max_price");
    var dd = document.getElementById("ff-district");
    advFilters.min_price = mp && mp.value ? parseFloat(mp.value) * 1000000 : null;
    advFilters.max_price = xp && xp.value ? parseFloat(xp.value) * 1000000 : null;
    advFilters.district = dd ? dd.value : "";
    document.getElementById("filter-sheet").style.display = "none";
    updateFilterCount();
    loadListings();
  };
  function updateFilterCount() {
    var n = 0;
    if (advFilters.min_price || advFilters.max_price) n++;
    if (advFilters.bedrooms.length) n++;
    if (advFilters.district) n++;
    if (advFilters.furnishing || advFilters.pet || advFilters.min_area) n++;
    if (advFilters.min_score) n++;
    if (advFilters.status) n++;
    var badge = document.getElementById("filter-count");
    badge.style.display = n ? "" : "none";
    badge.textContent = n;
  }
  // hook advanced filters into loadListings
  var _origLoadListings = loadListings;
  loadListings = function () {
    var params = "?limit=100";
    if (state.bedrooms) params += "&bedrooms=" + encodeURIComponent(state.bedrooms);
    if (state.status) params += "&status=" + encodeURIComponent(state.status);
    if (advFilters.min_price) params += "&min_price=" + advFilters.min_price;
    if (advFilters.max_price) params += "&max_price=" + advFilters.max_price;
    if (advFilters.bedrooms.length) params += "&bedrooms=" +
      advFilters.bedrooms.map(encodeURIComponent).join(",");
    if (advFilters.district) params += "&district=" +
      encodeURIComponent(advFilters.district);
    if (advFilters.furnishing) params += "&furnishing=" +
      encodeURIComponent(advFilters.furnishing);
    if (advFilters.pet) params += "&pet_friendly=true";
    if (advFilters.min_area) params += "&min_area=" + advFilters.min_area;
    if (advFilters.min_score) params += "&min_score=" + advFilters.min_score;
    if (advFilters.status) params += "&status=" +
      encodeURIComponent(advFilters.status);
    document.getElementById("listing-list").innerHTML =
      '<div class="loading">Đang tải...</div>';
    api("/api/listings" + params).then(function (data) {
      state.items = data.items || [];
      renderList();
    }).catch(function () {
      document.getElementById("listing-list").innerHTML =
        '<div class="empty"><div class="big">⚠️</div>Không tải được dữ liệu.</div>';
    });
  };

  // ---------- clients ----------
  var CLIENT_STATUS_EMOJI = {
    new: "🆕", contacted: "📞", searching: "🔍", sent: "📤",
    viewed: "👀", negotiating: "🤝", closed: "✅", cancelled: "❌",
  };

  function openClients() {
    document.getElementById("client-list").innerHTML =
      '<div class="loading">Đang tải...</div>';
    show("view-clients");
    api("/api/clients").then(function (d) {
      var cs = d.clients || [];
      if (!cs.length) {
        document.getElementById("client-list").innerHTML =
          '<div class="empty"><div class="big">👥</div>' +
          "Chưa có khách nào.<br>Bấm + Thêm để thêm khách mới.</div>";
        return;
      }
      document.getElementById("client-list").innerHTML = cs.map(function (c) {
        var em = CLIENT_STATUS_EMOJI[c.status] || "•";
        return '<div class="card" data-cid="' + esc(c.id) + '">' +
          '<div class="card-body">' +
          '<div class="card-title">' + esc(c.name) + "</div>" +
          '<div class="card-meta">Cần: ' + esc(c.req_summary) + "</div>" +
          '<div class="card-meta">' + em + " " + esc(c.status_vi) +
          (c.phone ? " · 📞 " + esc(c.phone) : "") + "</div>" +
          "</div></div>";
      }).join("");
      document.getElementById("client-list").querySelectorAll(".card")
        .forEach(function (card) {
          card.onclick = function () {
            openClientDetail(card.getAttribute("data-cid"));
          };
        });
    }).catch(function () {
      document.getElementById("client-list").innerHTML =
        '<div class="empty"><div class="big">⚠️</div>Không tải được dữ liệu.</div>';
    });
  }
  document.getElementById("client-add").onclick = function () {
    ["cf-name", "cf-phone", "cf-budget", "cf-notes"].forEach(function (id) {
      document.getElementById(id).value = "";
    });
    document.getElementById("cf-bedrooms").value = "";
    document.getElementById("cf-district").value = "";
    show("view-client-form");
  };
  document.getElementById("client-form-back").onclick = function () {
    openClients();
  };
  document.getElementById("client-form-save").onclick = function () {
    var name = document.getElementById("cf-name").value.trim();
    if (!name) { toast("Nhập tên khách đã nhé"); return; }
    var bval = parseFloat(document.getElementById("cf-budget").value);
    var body = {
      name: name,
      phone: document.getElementById("cf-phone").value.trim(),
      requirements_raw: document.getElementById("cf-notes").value.trim(),
    };
    var br = document.getElementById("cf-bedrooms").value;
    if (br !== "") body.bedrooms = parseFloat(br);
    if (!isNaN(bval)) body.budget_max = Math.round(bval * 1000000);
    var dt = document.getElementById("cf-district").value;
    if (dt) body.district = dt;
    api("/api/clients", { method: "POST", body: body }).then(function (d) {
      if (d.error) { toast(d.error_vi || "Lỗi lưu khách"); return; }
      toast("Đã thêm khách ✅");
      openClients();
    }).catch(function () { toast("Lỗi lưu khách"); });
  };
  document.getElementById("client-detail-back").onclick = function () {
    openClients();
  };

  var currentClientId = null;
  function openClientDetail(cid) {
    currentClientId = cid;
    document.getElementById("client-detail-body").innerHTML =
      '<div class="loading">Đang tải...</div>';
    show("view-client-detail");
    api("/api/client/" + encodeURIComponent(cid)).then(function (c) {
      if (c.error) { toast("Không tìm thấy khách"); openClients(); return; }
      document.getElementById("client-detail-title").textContent = c.name;
      var em = CLIENT_STATUS_EMOJI[c.status] || "•";
      var html = '<div class="detail-body">' +
        '<div class="detail-title">' + esc(c.name) + "</div>" +
        '<div class="card-meta">' + em + " " + esc(c.status_vi) + "</div>" +
        (c.phone ? '<div class="spec"><span class="k">📞 SĐT</span>' +
          '<span class="v">' + esc(c.phone) + "</span></div>" : "") +
        '<div class="section-title">Nhu cầu</div>' +
        '<div class="card-meta">' + esc(c.req_summary) + "</div>" +
        (c.requirements_raw ?
          '<div class="desc">' + esc(c.requirements_raw) + "</div>" : "") +
        '<div style="display:flex;gap:8px;margin:16px 0;flex-wrap:wrap">' +
        '<button class="btn btn-primary" id="cd-suggest">🏠 Gợi ý tin</button>' +
        '<button class="btn" id="cd-viewing">📅 Đặt lịch xem</button>' +
        "</div>";
      // sent listings
      if (c.sent_listings && c.sent_listings.length) {
        html += '<div class="section-title">Đã gửi ' + c.sent_listings.length +
          " tin</div>";
      }
      // notes
      html += '<div class="section-title">📝 Ghi chú</div>' +
        (c.notes ? '<div class="desc">' + esc(c.notes) + "</div>" :
          '<div class="card-meta">Chưa có ghi chú</div>') +
        '<div style="display:flex;gap:8px;margin-top:8px">' +
        '<input id="cd-note-input" type="text" placeholder="Thêm ghi chú..." ' +
        'style="flex:1;padding:10px;border:none;border-radius:10px;' +
        'background:var(--card2);color:var(--text)">' +
        '<button class="btn" id="cd-note-add" style="flex:0 0 auto">+</button>' +
        "</div>";
      // viewing history
      var vws = c.viewings || [];
      html += '<div class="section-title">📅 Lịch xem (' + vws.length + ")</div>";
      if (!vws.length) {
        html += '<div class="card-meta">Chưa có lịch xem nào</div>';
      } else {
        html += vws.map(function (v) {
          var dt = v.scheduled_at ?
            new Date(v.scheduled_at * 1000).toLocaleString("vi-VN",
              { day: "2-digit", month: "2-digit", hour: "2-digit",
                minute: "2-digit" }) : "—";
          return '<div class="spec"><span class="k">' + esc(dt) + "</span>" +
            '<span class="v">' + esc(v.status || "") +
            (v.listing_ids && v.listing_ids.length ?
              " · " + v.listing_ids.length + " tin" : "") + "</span></div>";
        }).join("");
      }
      html += "</div>";
      document.getElementById("client-detail-body").innerHTML = html;
      document.getElementById("cd-suggest").onclick = function () {
        openSuggest(cid);
      };
      document.getElementById("cd-viewing").onclick = function () {
        openViewingForm(cid, c.name, []);
      };
      document.getElementById("cd-note-add").onclick = function () {
        var inp = document.getElementById("cd-note-input");
        var note = inp.value.trim();
        if (!note) return;
        api("/api/client/" + encodeURIComponent(cid) + "/notes",
            { method: "POST", body: { note: note } }).then(function () {
          toast("Đã thêm ghi chú ✅");
          openClientDetail(cid);
        }).catch(function () { toast("Lỗi"); });
      };
    }).catch(function () { toast("Không tải được"); });
  }

  // ---------- suggest listings for client ----------
  var suggestState = null;
  function openSuggest(cid) {
    suggestState = { clientId: cid, client: null, items: [], selected: {} };
    document.getElementById("suggest-body").innerHTML =
      '<div class="loading">Đang tải...</div>';
    show("view-suggest");
    api("/api/client/" + encodeURIComponent(cid)).then(function (c) {
      suggestState.client = c;
      // build filter params from client requirements
      var params = "?limit=100&status=submitted";
      if (c.bedrooms != null) params += "&bedrooms=" + c.bedrooms;
      if (c.budget_max) params += "&max_price=" + c.budget_max;
      if (c.district) params += "&district=" + encodeURIComponent(c.district);
      return api("/api/listings" + params);
    }).then(function (d) {
      suggestState.items = d.items || [];
      renderSuggest();
    }).catch(function () {
      document.getElementById("suggest-body").innerHTML =
        '<div class="empty"><div class="big">⚠️</div>Không tải được.</div>';
    });
  }
  document.getElementById("suggest-back").onclick = function () {
    openClientDetail(suggestState ? suggestState.clientId : null);
  };

  function matchPct(l, c) {
    // simple client-side match estimate for display
    var s = 50;
    if (c.bedrooms != null && l.bedrooms === c.bedrooms) s += 20;
    if (c.budget_max && l.price_vnd && l.price_vnd <= c.budget_max) s += 20;
    if (c.district && l.district === c.district) s += 10;
    return Math.min(99, s);
  }

  function renderSuggest() {
    var st = suggestState;
    var c = st.client;
    var body = document.getElementById("suggest-body");
    document.getElementById("suggest-title").textContent =
      "Gợi ý cho " + (c ? c.name : "");
    var html = '<div class="propose-head">' +
      '<div class="propose-req">Cần: ' + esc(c ? c.req_summary : "—") + "</div>" +
      "</div>";
    trialCheck("send2client").then(function (trial) {
      html += trialBadgeHtml(trial);
      if (!st.items.length) {
        html += '<div class="empty"><div class="big">😔</div>' +
          "<b>Bạn không có căn nào thỏa yêu cầu</b></div>" +
          '<div style="padding:0 16px;display:flex;flex-direction:column;gap:8px">' +
          '<button class="btn btn-primary" id="sg-xbroker">🔗 Match broker khác</button>' +
          '<button class="btn" id="sg-addnew">➕ Thêm tin mới</button>' +
          "</div>";
      } else {
        html += '<div class="section-title" style="padding:0 16px">🎯 Tin phù hợp (' +
          st.items.length + ")</div>";
        html += st.items.map(function (l) {
          var sel = st.selected[l.id];
          var pct = matchPct(l, c);
          var img = (l.photo_urls && l.photo_urls.length)
            ? '<img class="propose-img" src="' + esc(l.photo_urls[0]) +
              '" loading="lazy">'
            : '<div class="propose-img-ph">🏢</div>';
          return '<div class="propose-card' + (sel ? " selected" : "") +
            '" data-id="' + esc(l.id) + '">' +
            '<div class="propose-check">' + (sel ? "☑️" : "☐") + "</div>" +
            img +
            '<div class="propose-info">' +
            '<div class="propose-title">' + esc(l.title) + "</div>" +
            '<div class="propose-meta">' + esc(l.price) + "/tháng</div>" +
            '<div class="propose-scores">🎯 Match ' + pct + "% · 🤖 " +
            (l.quality_score || 0) + "đ</div>" +
            "</div></div>";
        }).join("");
        html += '<div class="propose-bar">' +
          '<div class="propose-count">Đã chọn ' +
          Object.keys(st.selected).length + " tin</div>" +
          '<button class="btn btn-primary" id="sg-create"' +
          (Object.keys(st.selected).length ? "" : " disabled") +
          ">📤 Tạo trang chia sẻ</button></div>";
      }
      body.innerHTML = html;
      body.querySelectorAll(".propose-card").forEach(function (card) {
        card.onclick = function () {
          var id = card.getAttribute("data-id");
          if (st.selected[id]) delete st.selected[id];
          else st.selected[id] = true;
          renderSuggest();
        };
      });
      var xb = document.getElementById("sg-xbroker");
      if (xb) xb.onclick = function () { openXbroker(); };
      var an = document.getElementById("sg-addnew");
      if (an) an.onclick = function () { toast("Gửi tin mới qua bot nhé 📝"); };
      var cr = document.getElementById("sg-create");
      if (cr) cr.onclick = function () {
        trialGate("send2client", function () {
          openShareCreate(st.clientId, Object.keys(st.selected));
        });
      };
    });
  }

  // ---------- share page creation ----------
  function openShareCreate(clientId, listingIds) {
    document.getElementById("share-create-body").innerHTML =
      '<div class="loading">Đang tải...</div>';
    show("view-share-create");
    api("/api/listings?limit=100&ids=" + encodeURIComponent(listingIds.join(",")))
      .then(function (d) {
        var items = d.items || [];
        var html = '<div class="form">' +
          '<div class="field"><label>Tiêu đề trang</label>' +
          '<input id="sc-title" type="text" placeholder="Gợi ý cho khách"></div>' +
          '<div class="section-title">Đã chọn ' + items.length + " tin</div>" +
          items.map(function (l) {
            return '<div class="spec"><span class="k">' + esc(l.title) +
              "</span><span class='v'>" + esc(l.price) + "</span></div>";
          }).join("") +
          '<button class="btn btn-primary btn-block" id="sc-create">' +
          "🔗 Tạo link chia sẻ</button>" +
          '<div id="sc-result"></div>' +
          "</div>";
        document.getElementById("share-create-body").innerHTML = html;
        document.getElementById("sc-create").onclick = function () {
          var btn = this;
          btn.disabled = true;
          btn.textContent = "Đang tạo...";
          trialUse("send2client").then(function () {
            return api("/api/share", {
              method: "POST",
              body: {
                listing_ids: listingIds,
                title: document.getElementById("sc-title").value.trim(),
                client_id: clientId,
              },
            });
          }).then(function (r) {
            if (r.error) {
              toast(r.error_vi || "Tạo thất bại");
              btn.disabled = false;
              btn.textContent = "🔗 Tạo link chia sẻ";
              return;
            }
            document.getElementById("sc-result").innerHTML =
              '<div class="propose-done"><div class="big">✅</div>' +
              "<h3>Xong!</h3>" +
              '<div class="post-text" style="margin:12px 0">' +
              esc(r.url) + "</div>" +
              '<button class="btn btn-primary" id="sc-copy">📋 Copy link</button>' +
              '<div class="card-meta" style="margin-top:8px">👀 0 lượt xem</div>' +
              "</div>";
            document.getElementById("sc-copy").onclick = function () {
              copyText(r.url);
            };
            trialRefresh("send2client");
          }).catch(function () {
            toast("Tạo thất bại");
            btn.disabled = false;
            btn.textContent = "🔗 Tạo link chia sẻ";
          });
        };
      }).catch(function () {
        document.getElementById("share-create-body").innerHTML =
          '<div class="empty"><div class="big">⚠️</div>Không tải được.</div>';
      });
  }
  document.getElementById("share-create-back").onclick = function () {
    if (suggestState) openSuggest(suggestState.clientId);
    else openClients();
  };
  function copyText(t) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(t).then(function () {
        toast("Đã copy ✅");
      }).catch(function () { toast(t); });
    } else {
      toast(t);
    }
  }

  // ---------- viewing form ----------
  var viewingCtx = null;
  function openViewingForm(clientId, clientName, listingIds) {
    viewingCtx = { clientId: clientId, clientName: clientName,
                   listingIds: listingIds };
    document.getElementById("vf-datetime").value = "";
    document.getElementById("vf-notes").value = "";
    show("view-viewing-form");
  }
  document.getElementById("viewing-form-back").onclick = function () {
    if (viewingCtx && viewingCtx.clientId) openClientDetail(viewingCtx.clientId);
    else show("view-list");
  };
  document.getElementById("viewing-form-save").onclick = function () {
    var dt = document.getElementById("vf-datetime").value;
    if (!dt) { toast("Chọn ngày giờ đã nhé"); return; }
    var ts = Math.floor(new Date(dt).getTime() / 1000);
    api("/api/viewings", {
      method: "POST",
      body: {
        client_id: viewingCtx.clientId,
        client_name: viewingCtx.clientName,
        listing_ids: viewingCtx.listingIds,
        scheduled_at: ts,
        notes: document.getElementById("vf-notes").value.trim(),
      },
    }).then(function () {
      toast("Đã đặt lịch ✅");
      openClientDetail(viewingCtx.clientId);
    }).catch(function () { toast("Lỗi đặt lịch"); });
  };

  // ---------- broker profile ----------
  function openProfile() {
    document.getElementById("profile-body").innerHTML =
      '<div class="loading">Đang tải...</div>';
    show("view-profile");
    api("/api/profile").then(function (p) {
      if (p.error) { toast("Không tải được hồ sơ"); return; }
      var score = p.score;
      var scls = score == null ? "" :
        (score >= 80 ? "q-high" : score >= 50 ? "q-mid" : "q-low");
      var scol = score == null ? "var(--muted)" :
        (score >= 80 ? "var(--green)" : score >= 50 ? "#ffab00" : "var(--red)");
      var tierLabel = { free: "Free", pro: "Pro 💎", max: "Max 💎💎" }[p.tier] || p.tier;
      var html = '<div class="detail-body">' +
        '<div style="display:flex;gap:14px;align-items:center;margin-bottom:16px">' +
        '<div class="profile-avatar">👤</div>' +
        '<div><div class="detail-title">' + esc(p.name || "Broker") + "</div>" +
        '<div class="card-meta">' + (p.phone ? "📞 " + esc(p.phone) + " · " : "") +
        "Gói: <b>" + esc(tierLabel) + "</b></div></div></div>" +
        '<div class="section-title">🤖 Điểm uy tín ' +
        (score == null ? '<span class="qscore">—</span>' :
          '<span class="qscore ' + scls + '">' + score + "đ</span>") +
        "</div>";
      if (score != null) {
        html += '<div class="qbar"><div style="width:' + score +
          '%;background:' + scol + '"></div></div>' +
          '<div class="card-meta">📝 Chất lượng tin: ' +
          (p.completeness == null ? "—" : p.completeness + "/100") +
          " (" + p.complete_listings + " tin đầy đủ)</div>" +
          '<div class="card-meta">🔄 Độ tươi: ' +
          (p.freshness == null ? "—" : p.freshness + "/100") +
          " (" + p.fresh_listings + " tin mới)</div>";
        if (p.false_refresh_reports > 0) {
          html += '<div class="propose-warn">⚠️ Báo sai trạng thái: ' +
            p.false_refresh_reports + " lần (-" +
            (p.false_refresh_reports * 10) + "đ uy tín)</div>";
        }
      } else {
        html += '<div class="card-meta">Gửi tin đầu tiên để bắt đầu tích điểm 📝</div>';
      }
      var st = p.stats || {};
      html += '<div class="section-title">📊 Thống kê</div>' +
        '<div class="spec"><span class="k">Tổng tin</span><span class="v">' +
        (st.total_listings || 0) + "</span></div>" +
        '<div class="spec"><span class="k">Còn trống</span><span class="v">' +
        (st.active_listings || 0) + "</span></div>" +
        '<div class="spec"><span class="k">Đã cho thuê</span><span class="v">' +
        (st.rented_listings || 0) + "</span></div>" +
        '<div class="spec"><span class="k">Lượt xem trang share</span><span class="v">' +
        (st.share_views || 0) + "</span></div>" +
        '<div class="section-title">🎁 Mời bạn bè</div>' +
        '<div id="pf-referral"><div class="loading">Đang tải...</div></div>' +
        '<div style="display:flex;gap:8px;margin-top:16px">' +
        '<button class="btn btn-primary" id="pf-upgrade">⭐ Nâng cấp</button>' +
        '<button class="btn" id="pf-edit">✏️ Sửa thông tin</button>' +
        "</div></div>";
      document.getElementById("profile-body").innerHTML = html;
      document.getElementById("pf-upgrade").onclick = openUpgrade;
      document.getElementById("pf-edit").onclick = function () {
        openProfileEdit(p);
      };
      // referral section (async)
      api("/api/referral").then(function (r) {
        var el = document.getElementById("pf-referral");
        if (!el) return;
        var bar = "✅".repeat(r.qualified) +
          "⬜".repeat(Math.max(0, r.needed - r.qualified));
        var h = '<div class="card-meta" style="margin-bottom:6px">' +
          "Tiến độ: <b>" + r.qualified + "/" + r.needed + "</b> " + bar +
          "</div>" +
          '<div class="card-meta" style="margin-bottom:8px">' +
          "Mời đủ " + r.needed +
          " người (mỗi người 5 tin đạt chuẩn) → <b>1 tháng Pro free</b> 🎉</div>";
        if (r.link) {
          h += '<div style="display:flex;gap:8px">' +
            '<input id="pf-ref-link" readonly value="' + esc(r.link) +
            '" style="flex:1" onclick="this.select()">' +
            '<button class="btn btn-primary btn-sm" id="pf-ref-copy">📋 Copy</button></div>';
        }
        el.innerHTML = h;
        var cp = document.getElementById("pf-ref-copy");
        if (cp) cp.onclick = function () {
          var inp = document.getElementById("pf-ref-link");
          inp.select();
          try { document.execCommand("copy"); } catch (e) {}
          if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(inp.value).catch(function () {});
          }
          toast("Đã copy link mời 📋");
        };
      }).catch(function () {
        var el = document.getElementById("pf-referral");
        if (el) el.innerHTML = "";
      });
    }).catch(function () { toast("Không tải được hồ sơ"); });
  }
  document.getElementById("profile-back").onclick = function () {
    show("view-list");
  };

  function openProfileEdit(p) {
    var body = document.getElementById("profile-body");
    body.innerHTML = '<div class="form">' +
      '<div class="field"><label>Tên hiển thị</label>' +
      '<input id="pe-name" type="text" value="' + esc(p.name || "") + '"></div>' +
      '<div class="field"><label>Số điện thoại</label>' +
      '<input id="pe-phone" type="tel" value="' + esc(p.phone || "") + '"></div>' +
      '<div class="field"><label>Xưng hô</label>' +
      '<select id="pe-pronoun">' +
      '<option value="anh"' + (p.pronoun === "anh" ? " selected" : "") +
      ">Anh</option>" +
      '<option value="chị"' + (p.pronoun === "chị" ? " selected" : "") +
      ">Chị</option>" +
      "</select></div>" +
      '<button class="btn btn-primary btn-block" id="pe-save">💾 Lưu</button>' +
      "</div>";
    document.getElementById("pe-save").onclick = function () {
      api("/api/profile", {
        method: "PUT",
        body: { fields: {
          display_name: document.getElementById("pe-name").value.trim(),
          phone: document.getElementById("pe-phone").value.trim(),
          pronoun: document.getElementById("pe-pronoun").value,
        } },
      }).then(function () {
        toast("Đã lưu ✅");
        openProfile();
      }).catch(function () { toast("Lỗi lưu"); });
    };
  }

  // ---------- upgrade ----------
  function openUpgrade() {
    document.getElementById("upgrade-body").innerHTML =
      '<div class="loading">Đang tải...</div>';
    show("view-upgrade");
    Promise.all([trialCheck("send2client"), trialCheck("xbroker_match"),
                 api("/api/profile")]).then(function (rs) {
      var tSend = rs[0], tXb = rs[1], prof = rs[2];
      var tier = (prof && prof.tier) || "free";
      function row(feat, free, pro, max) {
        return '<tr><td>' + feat + "</td><td>" + free + "</td><td>" + pro +
          "</td><td>" + max + "</td></tr>";
      }
      var yn = function (v) { return v ? "✅" : "❌"; };
      var html = '<div class="detail-body">' +
        '<div class="card-meta" style="margin-bottom:12px">Gói hiện tại: <b>' +
        esc({ free: "Free", pro: "Pro 💎", max: "Max 💎💎" }[tier] || tier) +
        "</b></div>" +
        '<table class="tier-table">' +
        "<tr><th></th><th>Free</th><th>Pro<br>99k/th</th><th>Max<br>199k/th</th></tr>" +
        row("Số tin", "20", "∞", "∞") +
        row("Match tin của mình", yn(true), yn(true), yn(true)) +
        row("Đặt lịch xem", yn(true), yn(true), yn(true)) +
        row("Gửi tin cho khách", "3 lượt thử", yn(true), yn(true)) +
        row("Match liên broker", "3 lượt thử", "3 lượt thử", yn(true)) +
        row("Filter nâng cao", yn(false), yn(true), yn(true)) +
        row("Thống kê chi tiết", yn(false), yn(false), yn(true)) +
        "</table>" +
        '<div class="card-meta" style="margin:12px 0">' +
        "🎁 Lượt thử còn lại — Gửi tin: " +
        (tSend.remaining < 0 ? "∞" : tSend.remaining + "/3") +
        " · Match liên broker: " +
        (tXb.remaining < 0 ? "∞" : tXb.remaining + "/3") +
        "</div>";
      if (tier === "free") {
        html += '<button class="btn btn-primary btn-block" id="up-pro">' +
          "⭐ Nâng cấp Pro — 99k/tháng</button>" +
          '<button class="btn btn-block" id="up-max">' +
          "💎💎 Nâng cấp Max — 199k/tháng</button>";
      } else if (tier === "pro") {
        html += '<button class="btn btn-primary btn-block" id="up-max">' +
          "💎💎 Lên Max — 199k/tháng</button>";
      } else {
        html += '<div class="empty"><div class="big">💎💎</div>' +
          "Bạn đang dùng gói cao nhất!</div>";
      }
      html += "</div>";
      document.getElementById("upgrade-body").innerHTML = html;
      var up = document.getElementById("up-pro");
      if (up) up.onclick = function () { requestUpgrade("pro"); };
      var um = document.getElementById("up-max");
      if (um) um.onclick = function () { requestUpgrade("max"); };
    }).catch(function () { toast("Không tải được"); });
  }
  document.getElementById("upgrade-back").onclick = function () {
    show("view-list");
  };

  function requestUpgrade(tier) {
    var label = tier === "pro" ? "Pro — 99k/tháng" : "Max — 199k/tháng";
    api("/api/premium/request", {
      method: "POST", body: { tier: tier },
    }).then(function (d) {
      if (d.error === "already_pending") {
        toast("Yêu cầu đang chờ duyệt ⏳");
        return;
      }
      if (d.error) { toast("Lỗi, thử lại nhé"); return; }
      var body = document.getElementById("upgrade-body");
      body.innerHTML = '<div class="detail-body">' +
        '<div class="propose-done"><div class="big">⭐</div>' +
        "<h3>Đã gửi yêu cầu " + esc(label) + "</h3>" +
        '<p style="color:var(--muted);margin:12px 0">' +
        "Chuyển khoản theo hướng dẫn trong bot, admin sẽ duyệt trong 24h.</p>" +
        '<p style="color:var(--muted)">Mở bot Linh và làm theo hướng dẫn thanh toán nhé 💳</p>' +
        "</div></div>";
      toast("Đã gửi yêu cầu ✅");
    }).catch(function () { toast("Lỗi, thử lại nhé"); });
  }

  // ---------- commission ----------
  function openCommission() {
    document.getElementById("commission-body").innerHTML =
      '<div class="loading">Đang tải...</div>';
    show("view-commission");
    api("/api/deals").then(function (d) {
      var total = d.month_total || 0;
      var fmtM = function (v) {
        return (v / 1000000).toFixed(1).replace(/\.0$/, "") + "tr";
      };
      var html = '<div class="detail-body">' +
        '<div class="propose-head"><div class="propose-req">Tổng tháng ' +
        esc(d.month) + ": <b>" + esc(fmtM(total)) + "</b></div></div>";
      var closed = d.closed || [];
      html += '<div class="section-title">✅ Đã chốt (' + closed.length + ")</div>";
      if (!closed.length) html += '<div class="card-meta">Chưa có</div>';
      html += closed.map(function (x) {
        return '<div class="spec"><span class="k">' +
          esc(x.client_name || x.listing_id || "—") + "</span>" +
          '<span class="v">' + esc(fmtM(x.commission_vnd)) + "</span></div>";
      }).join("");
      var neg = d.negotiating || [];
      html += '<div class="section-title">🤝 Đang đàm phán (' + neg.length + ")</div>";
      if (!neg.length) html += '<div class="card-meta">Chưa có</div>';
      html += neg.map(function (x) {
        return '<div class="spec"><span class="k">' +
          esc(x.client_name || x.listing_id || "—") + "</span>" +
          '<span class="v">' + esc(fmtM(x.commission_vnd)) + "</span></div>";
      }).join("");
      html += '<button class="btn btn-primary btn-block" id="cm-add">' +
        "+ Thêm giao dịch</button></div>";
      document.getElementById("commission-body").innerHTML = html;
      document.getElementById("cm-add").onclick = openDealForm;
    }).catch(function () { toast("Không tải được"); });
  }
  document.getElementById("commission-back").onclick = function () {
    show("view-list");
  };

  function openDealForm() {
    var body = document.getElementById("commission-body");
    body.innerHTML = '<div class="form">' +
      '<div class="field"><label>Tên khách</label>' +
      '<input id="df-client" type="text"></div>' +
      '<div class="field"><label>Hoa hồng (triệu)</label>' +
      '<input id="df-amount" type="number" inputmode="decimal" placeholder="7.5"></div>' +
      '<div class="field"><label>Ghi chú</label>' +
      '<input id="df-notes" type="text" placeholder="VD: 2PN An Thượng"></div>' +
      '<button class="btn btn-primary btn-block" id="df-save">💾 Lưu</button>' +
      '<button class="btn btn-block" id="df-cancel">Hủy</button></div>';
    document.getElementById("df-cancel").onclick = openCommission;
    document.getElementById("df-save").onclick = function () {
      var amt = parseFloat(document.getElementById("df-amount").value);
      api("/api/deals", {
        method: "POST",
        body: {
          client_name: document.getElementById("df-client").value.trim(),
          commission_amount: isNaN(amt) ? 0 : Math.round(amt * 1000000),
          notes: document.getElementById("df-notes").value.trim(),
        },
      }).then(function () {
        toast("Đã lưu ✅");
        openCommission();
      }).catch(function () { toast("Lỗi lưu"); });
    };
  }

  // ---------- notification settings ----------
  function openNotifySettings() {
    document.getElementById("notify-body").innerHTML =
      '<div class="loading">Đang tải...</div>';
    show("view-notify");
    api("/api/notify/prefs").then(function (d) {
      var prefs = d.prefs || [];
      var html = '<div class="detail-body">' +
        '<div class="card-meta" style="margin-bottom:12px">' +
        "Bot sẽ báo cho bạn qua Telegram khi có:</div>" +
        prefs.map(function (p) {
          return '<div class="spec"><span class="k">' + esc(p.label) +
            '</span><button class="toggle' + (p.enabled ? " on" : "") +
            '" data-pref="' + esc(p.key) + '">' +
            (p.enabled ? "Bật" : "Tắt") + "</button></div>";
        }).join("") + "</div>";
      document.getElementById("notify-body").innerHTML = html;
      document.getElementById("notify-body").querySelectorAll(".toggle")
        .forEach(function (t) {
          t.onclick = function () {
            var pref = t.getAttribute("data-pref");
            var now = t.classList.contains("on");
            api("/api/notify/prefs", {
              method: "PUT",
              body: { pref: pref, enabled: !now },
            }).then(function () {
              t.classList.toggle("on");
              t.textContent = now ? "Tắt" : "Bật";
              toast(now ? "Đã tắt 🔕" : "Đã bật 🔔");
            }).catch(function () { toast("Lỗi"); });
          };
        });
    }).catch(function () { toast("Không tải được"); });
  }
  document.getElementById("notify-back").onclick = function () {
    show("view-list");
  };
})();
