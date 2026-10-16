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
      var meta = [i.bedroom_label];
      if (i.bathrooms) meta.push(i.bathrooms + " WC");
      if (i.area_m2) meta.push(i.area_m2 + "m²");
      if (i.photo_count) meta.push("📸 " + i.photo_count);
      return (
        '<div class="card" data-id="' + esc(i.id) + '">' +
        '<div class="card-img">🏢</div>' +
        '<div class="card-body">' +
        '<div class="card-title">' + esc(i.title) + badge + "</div>" +
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
    var html =
      '<div class="detail-img">🏢</div><div class="detail-body">' +
      '<div class="detail-title">' + esc(d.title) + "</div>" +
      '<div class="detail-price">' + esc(d.price) + "/tháng</div>" +
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
  function openEdit(id) {
    currentId = id;
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
    show("view-detail");
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
      openDetail(currentId, "info");
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
  loadListings();
})();
