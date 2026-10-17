"""Public share pages: GET /s/<token> (no auth).

Standalone mobile-first pages a broker sends to clients via any channel
(Zalo/SMS/...). Light theme, Vietnamese, TrueNest branding + broker
attribution for commission tracking. Stdlib only.
"""
import html
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db  # noqa: E402
import market  # noqa: E402
import schema as master_schema  # noqa: E402


def _esc(v):
    return html.escape(str(v or ""), quote=True)


def _fmt_price(vnd):
    if not vnd:
        return "—"
    try:
        tr = float(vnd) / 1_000_000
    except (TypeError, ValueError):
        return "—"
    s = f"{tr:.1f}".rstrip("0").rstrip(".")
    return f"{s}tr"


def _bedroom_label(br, ptype):
    if ptype == "studio":
        return "Studio"
    try:
        return f"{int(float(br))}PN"
    except (TypeError, ValueError):
        return ""


def _listing_card(lst, idx):
    """One listing card: photo, title, price, specs, market badge, book btn."""
    p = master_schema.normalize_parsed(lst.get("parsed") or {})
    title_bits = [
        _bedroom_label(p.get("bedrooms"), p.get("property_type")),
        p.get("building_name") or p.get("district") or "",
    ]
    title = " ".join(b for b in title_bits if b) or "Căn hộ cho thuê"

    specs = []
    if p.get("bathrooms"):
        try:
            specs.append(f"{int(float(p['bathrooms']))} WC")
        except (TypeError, ValueError):
            pass
    if p.get("area_m2"):
        specs.append(f"{p['area_m2']}m²")
    if p.get("furnishing"):
        specs.append(str(p["furnishing"]))
    specs_html = " · ".join(_esc(s) for s in specs)

    photo_urls = lst.get("photo_urls") or []
    if photo_urls:
        img = (f'<img class="photo" src="{_esc(photo_urls[0])}" alt=""'
               ' loading="lazy" onerror="this.remove()">')
    else:
        img = '<div class="photo photo-ph">🏠</div>'

    insight = market.get_market_insight(p, exclude_id=lst.get("id"))
    badge = _insight_badge(insight)

    # Privacy: never show exact street address to clients.
    # Broker's detailed address is for internal dedup/matching only.
    # Clients see district + building name until they choose the broker.
    addr_bits = [p.get("building_name"), p.get("district")]
    addr = ", ".join(a for a in addr_bits if a)

    return f"""
    <article class="card" id="listing-{idx}">
      {img}
      <div class="card-body">
        <h2>{_esc(title)}</h2>
        <div class="price">{_esc(_fmt_price(p.get('price_vnd')))}<span>/tháng</span></div>
        {f'<div class="specs">{specs_html}</div>' if specs_html else ''}
        {f'<div class="addr">📍 {_esc(addr)}</div>' if addr else ''}
        {badge}
        <button class="book-btn" onclick="toggleForm({idx})">📅 Đặt lịch xem</button>
        <form class="book-form" id="form-{idx}" onsubmit="return submitBooking(event, {idx}, '{_esc(lst['id'])}')">
          <input name="name" placeholder="Họ tên của bạn *" required maxlength="80">
          <input name="phone" placeholder="Số điện thoại *" required maxlength="20" inputmode="tel">
          <input name="date" type="date" placeholder="Ngày muốn xem">
          <textarea name="note" placeholder="Ghi chú thêm (khung giờ, yêu cầu...)" rows="2" maxlength="300"></textarea>
          <button type="submit">Gửi yêu cầu →</button>
          <div class="form-msg" id="msg-{idx}"></div>
        </form>
        <button class="report-btn" onclick="openReport({idx}, '{_esc(lst['id'])}')">🚩 Báo tin sai</button>
        <div class="report-modal" id="report-{idx}" style="display:none">
          <div class="report-box">
            <h3>Tin này có vấn đề gì?</h3>
            <label><input type="radio" name="rr-{idx}" value="rented"> Đã cho thuê rồi</label>
            <label><input type="radio" name="rr-{idx}" value="price_wrong"> Giá không đúng</label>
            <label><input type="radio" name="rr-{idx}" value="photo_wrong"> Ảnh không đúng thực tế</label>
            <label><input type="radio" name="rr-{idx}" value="address_wrong"> Địa chỉ sai</label>
            <label><input type="radio" name="rr-{idx}" value="amenity_wrong"> Tiện ích không đúng thực tế</label>
            <div class="report-actions">
              <button onclick="submitReport(event, {idx}, '{_esc(lst['id'])}')">Gửi báo cáo</button>
              <button onclick="closeReport({idx})" class="cancel">Hủy</button>
            </div>
            <div class="form-msg" id="rmsg-{idx}"></div>
          </div>
        </div>
      </div>
    </article>"""


def _insight_badge(insight):
    if insight.get("insufficient_data"):
        return ('<div class="insight insight-na">'
                '📊 Chưa đủ dữ liệu thị trường để so sánh</div>')
    label = insight["label"]
    pct = insight["vs_median_pct"]
    cls = ("good" if label in ("Rất tốt", "Tốt")
           else "fair" if label == "Hợp lý" else "high")
    emoji = "💰" if cls == "good" else "⚖️" if cls == "fair" else "📈"
    text = market.insight_badge_text(insight)
    count = insight["count"]
    return (f'<div class="insight insight-{cls}">{emoji} <b>Giá {label.lower()}</b>'
            f' — {html.escape(text or "")}<br>'
            f'<small>Dựa trên {count} tin cùng khu vực · TrueNest phân tích</small></div>')


PAGE_CSS = """
:root{--bg:#f7f8fa;--card:#fff;--text:#1a2332;--muted:#6b7686;--accent:#0d9488;--accent-d:#0b7d74;--line:#e8ecf1}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:var(--bg);color:var(--text);line-height:1.5}
.wrap{max-width:520px;margin:0 auto;padding:0 0 40px}
.brand{background:#fff;border-bottom:1px solid var(--line);padding:14px 20px;display:flex;align-items:center;gap:10px;position:sticky;top:0;z-index:10}
.brand .logo{font-size:24px}
.brand .name{font-weight:800;font-size:18px}
.brand .tag{font-size:11px;color:var(--muted)}
.hero{padding:22px 20px 6px}
.hero h1{font-size:20px;margin-bottom:4px}
.hero .sub{color:var(--muted);font-size:13px}
.broker{background:#fff;border:1px solid var(--line);border-radius:14px;margin:14px 20px;padding:14px 16px;display:flex;align-items:center;gap:12px}
.broker .avatar{width:44px;height:44px;border-radius:50%;background:var(--accent);color:#fff;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:18px;flex:none}
.broker .who{font-size:14px}
.broker .who b{display:block;font-size:15px}
.broker .who a{color:var(--accent);text-decoration:none;font-weight:600}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;margin:14px 20px;overflow:hidden}
.photo{width:100%;aspect-ratio:16/10;object-fit:cover;display:block;background:#eef1f5}
.photo-ph{display:flex;align-items:center;justify-content:center;font-size:48px}
.card-body{padding:16px}
.card-body h2{font-size:17px;margin-bottom:6px}
.price{font-size:22px;font-weight:800;color:var(--accent-d)}
.price span{font-size:13px;font-weight:400;color:var(--muted)}
.specs{font-size:13px;color:var(--muted);margin-top:4px}
.addr{font-size:13px;color:var(--muted);margin-top:2px}
.insight{border-radius:10px;padding:10px 12px;font-size:13px;margin-top:10px}
.insight small{color:var(--muted)}
.insight-good{background:#ecfdf5;border:1px solid #a7f3d0}
.insight-fair{background:#eff6ff;border:1px solid #bfdbfe}
.insight-high{background:#fff7ed;border:1px solid #fed7aa}
.insight-na{background:#f3f4f6;border:1px solid var(--line);color:var(--muted)}
.book-btn{width:100%;margin-top:12px;padding:12px;border:none;border-radius:10px;background:var(--accent);color:#fff;font-size:15px;font-weight:700;cursor:pointer}
.book-btn:active{background:var(--accent-d)}
.book-form{display:none;margin-top:10px}
.book-form.open{display:block}
.book-form input,.book-form textarea{width:100%;padding:10px 12px;margin-bottom:8px;border:1px solid var(--line);border-radius:8px;font-size:14px;font-family:inherit}
.book-form button{width:100%;padding:11px;border:none;border-radius:8px;background:#1a2332;color:#fff;font-size:14px;font-weight:700;cursor:pointer}
.form-msg{font-size:13px;margin-top:6px;min-height:18px}
.form-msg.ok{color:#0d9488}
.form-msg.err{color:#dc2626}
.report-btn{width:100%;margin-top:8px;padding:8px;border:1px solid var(--line);border-radius:8px;background:transparent;color:var(--muted);font-size:13px;cursor:pointer}
.report-modal{position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.5);z-index:100;display:flex;align-items:center;justify-content:center;padding:20px}
.report-box{background:#fff;border-radius:16px;padding:20px;max-width:360px;width:100%}
.report-box h3{font-size:16px;margin-bottom:12px}
.report-box label{display:block;padding:10px 0;font-size:14px;border-bottom:1px solid var(--line);cursor:pointer}
.report-box label input{margin-right:8px}
.report-actions{display:flex;gap:8px;margin-top:16px}
.report-actions button{flex:1;padding:11px;border:none;border-radius:8px;background:var(--accent);color:#fff;font-size:14px;font-weight:700;cursor:pointer}
.report-actions button.cancel{background:#f1f3f5;color:var(--text)}
.footer{text-align:center;color:var(--muted);font-size:12px;padding:24px 20px}
.footer b{color:var(--text)}
.error-wrap{max-width:520px;margin:0 auto;padding:60px 24px;text-align:center}
.error-wrap .big{font-size:48px;margin-bottom:12px}
.error-wrap h1{font-size:18px;margin-bottom:8px}
.error-wrap p{color:var(--muted);font-size:14px}
"""


PAGE_JS = """
function toggleForm(i){
  var f=document.getElementById('form-'+i);
  f.classList.toggle('open');
  if(f.classList.contains('open')){f.querySelector('input').focus();}
}
function submitBooking(e,i,listingId){
  e.preventDefault();
  var f=e.target, msg=document.getElementById('msg-'+i);
  var fd=new FormData(f);
  var phone=(fd.get('phone')||'').replace(/[^0-9+]/g,'');
  if(phone.replace(/[^0-9]/g,'').length<8){msg.className='form-msg err';msg.textContent='Số điện thoại chưa đúng.';return false;}
  msg.className='form-msg';msg.textContent='Đang gửi...';
  fetch('book',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({listing_id:listingId,name:fd.get('name'),phone:fd.get('phone'),preferred_date:fd.get('date'),note:fd.get('note')})})
  .then(function(r){return r.json().then(function(j){return {s:r.status,j:j};});})
  .then(function(r){
    if(r.s===200){msg.className='form-msg ok';msg.textContent='✅ Đã gửi! Môi giới sẽ liên hệ lại sớm.';f.querySelector('button').disabled=true;}
    else{msg.className='form-msg err';msg.textContent='⚠️ '+(r.j.error_vi||'Gửi thất bại, thử lại sau.');}
  }).catch(function(){msg.className='form-msg err';msg.textContent='⚠️ Lỗi mạng, thử lại sau.';});
  return false;
}
function openReport(i,listingId){
  document.getElementById('report-'+i).style.display='block';
}
function closeReport(i){
  document.getElementById('report-'+i).style.display='none';
}
function submitReport(e,i,listingId){
  e.preventDefault();
  var sel=document.querySelector('input[name="rr-'+i+'"]:checked');
  var msg=document.getElementById('rmsg-'+i);
  if(!sel){msg.className='form-msg err';msg.textContent='Vui lòng chọn lý do.';return false;}
  msg.className='form-msg';msg.textContent='Đang gửi...';
  fetch('report',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({listing_id:listingId,reason:sel.value})})
  .then(function(r){return r.json().then(function(j){return {s:r.status,j:j};});})
  .then(function(r){
    if(r.s===200){msg.className='form-msg ok';msg.textContent='✅ Cảm ơn! Chúng tôi sẽ kiểm tra lại tin này.';closeReport(i);}
    else{msg.className='form-msg err';msg.textContent='⚠️ '+(r.j.error_vi||'Gửi thất bại.');}
  }).catch(function(){msg.className='form-msg err';msg.textContent='⚠️ Lỗi mạng, thử lại sau.';});
  return false;
}
"""


def render_share_page(token):
    """(html, status). Public — no auth."""
    page = db.get_share_page(token, bump_view=True)
    if not page:
        return _error_page(
            "Không tìm thấy trang này",
            "Liên kết có thể đã hết hạn hoặc không đúng. Hãy liên hệ môi giới để nhận link mới."
        ), 404

    broker = db.get_broker(page["broker_id"]) or {}
    bname = broker.get("display_name") or broker.get("name") or "Môi giới TrueNest"
    bphone = broker.get("phone") or ""
    initial = (bname.strip()[:1] or "T").upper()

    cards = []
    for i, lid in enumerate(page["listing_ids"] or []):
        row = db.get_listing(lid)
        if not row:
            continue
        # Only show active listings on the public page.
        if row.get("status") not in ("submitted", "uncertain"):
            continue
        cards.append(_listing_card(row, i))
    if not cards:
        return _error_page(
            "Các tin trong trang này đã gỡ",
            "Môi giới đã cập nhật danh sách. Hãy liên hệ trực tiếp để nhận gợi ý mới."
        ), 410

    title = page["title"] or "Gợi ý nhà cho thuê"
    n = len(cards)
    broker_contact = (
        f'<a href="tel:{_esc(re.sub(r"[^0-9+]", "", bphone))}">📞 {_esc(bphone)}</a>'
        if bphone else '<span class="who-note">Liên hệ qua TrueNest</span>'
    )
    body = f"""
    <div class="wrap">
      <div class="brand"><span class="logo">🏠</span>
        <div><div class="name">TrueNest</div><div class="tag">Thuê nhà Đà Nẵng tin cậy</div></div>
      </div>
      <div class="hero"><h1>{_esc(title)}</h1>
        <div class="sub">{n} gợi ý được chọn riêng cho bạn</div></div>
      <div class="broker"><div class="avatar">{_esc(initial)}</div>
        <div class="who"><b>{_esc(bname)}</b>{broker_contact}</div></div>
      {''.join(cards)}
      <div class="footer"><b>🏠 TrueNest</b><br>Nền tảng thuê nhà tin cậy tại Đà Nẵng</div>
    </div>"""
    return _page(title, body), 200


def _page(title, body):
    return f"""<!DOCTYPE html><html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)} · TrueNest</title>
<style>{PAGE_CSS}</style></head>
<body>{body}<script>{PAGE_JS}</script></body></html>"""


def _error_page(heading, sub):
    return _page(heading, f"""
    <div class="wrap"><div class="brand"><span class="logo">🏠</span>
      <div><div class="name">TrueNest</div></div></div>
      <div class="error-wrap"><div class="big">🔗</div>
        <h1>{_esc(heading)}</h1><p>{_esc(sub)}</p></div>
      <div class="footer"><b>🏠 TrueNest</b></div></div>""")


def handle_booking(token, data):
    """POST /s/<token>/book — {listing_id,name,phone,preferred_date,note}."""
    page = db.get_share_page(token, bump_view=False)
    if not page:
        return {"error": "invalid_token",
                "error_vi": "Trang này đã hết hạn."}, 404
    name = (data.get("name") or "").strip()[:80]
    phone = (data.get("phone") or "").strip()[:20]
    digits = re.sub(r"[^0-9]", "", phone)
    if not name or len(digits) < 8:
        return {"error": "invalid_input",
                "error_vi": "Vui lòng nhập họ tên và số điện thoại đúng."}, 400
    listing_id = data.get("listing_id")
    if listing_id and listing_id not in (page["listing_ids"] or []):
        listing_id = None
    bid = db.create_share_booking(
        token, page["broker_id"], name, phone, listing_id=listing_id,
        preferred_date=(data.get("preferred_date") or "")[:20],
        note=(data.get("note") or "")[:300],
    )
    # Queue real-time push to broker via bot (Khanh 2026-10-16)
    try:
        db.queue_notification(
            "booking_created", None,
            {"broker_id": page["broker_id"], "booking_id": bid,
             "name": name, "phone": phone, "listing_id": listing_id,
             "preferred_date": (data.get("preferred_date") or "")[:20]})
    except Exception:
        pass
    return {"ok": True, "booking_id": bid}, 200


def handle_report(token, data):
    """POST /s/<token>/report — client reports incorrect listing.

    Body: {listing_id, reason}. Auto-checks against recent refresh claims;
    if the broker claimed 'available' within 7 days but client says rented,
    triggers the false-refresh penalty pipeline.
    """
    page = db.get_share_page(token, bump_view=False)
    if not page:
        return {"error": "invalid_token",
                "error_vi": "Trang này đã hết hạn."}, 404
    listing_id = (data.get("listing_id") or "").strip()
    reason = (data.get("reason") or "").strip()
    if not listing_id or listing_id not in (page["listing_ids"] or []):
        return {"error": "invalid_listing",
                "error_vi": "Tin không hợp lệ."}, 400
    rid = db.create_listing_report(token, listing_id, page["broker_id"],
                                   reason)
    if not rid:
        return {"error": "invalid_reason",
                "error_vi": "Lý do không hợp lệ."}, 400
    # Anti-abuse: the link is public and unauthenticated, so one link may
    # cause at most ONE automatic strike (any listing, any number of POSTs).
    # Every report is still stored for admin review; only the automatic
    # penalty is limited. Different links still add up as before.
    # Auto-match: rented report + recent 'available' refresh claim
    # -> probable false refresh -> penalize (Khanh 2026-10-16)
    if reason == "rented":
        claim = db.check_report_against_refresh(listing_id)
        if claim and db.reserve_report_penalty(token, listing_id, rid,
                                               reason):
            try:
                db.queue_notification(
                    "false_refresh_suspect", None,
                    {"listing_id": listing_id,
                     "report_id": rid,
                     "broker_id": page["broker_id"]})
            except Exception:
                pass
    # Amenity fraud: client reports false amenities/highlights
    # -> same penalty track as false refresh (Khanh 2026-10-16)
    elif reason == "amenity_wrong" and db.reserve_report_penalty(
            token, listing_id, rid, reason):
        try:
            db.queue_notification(
                "false_amenity_suspect", None,
                {"listing_id": listing_id,
                 "report_id": rid,
                 "broker_id": page["broker_id"]})
        except Exception:
            pass
    return {"ok": True, "report_id": rid}, 200
