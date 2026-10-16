// V2 Tabs: Clients, Viewings, Deals
function switchTab(tab, el) {
  const views = {
    listings: document.querySelector('main > div.flex.flex-col.w-full.pb-6.relative:not(#view-clients):not(#view-viewings):not(#view-deals)'),
    clients: document.getElementById('view-clients'),
    viewings: document.getElementById('view-viewings'),
    deals: document.getElementById('view-deals')
  };
  document.querySelectorAll('nav a').forEach(a => {
    a.classList.remove('text-primary', 'font-semibold');
    a.classList.add('text-on-surface-variant');
  });
  el.classList.remove('text-on-surface-variant');
  el.classList.add('text-primary', 'font-semibold');
  Object.entries(views).forEach(([k, v]) => {
    if (!v) return;
    if (k === tab) { v.classList.remove('hidden'); v.classList.add('flex'); }
    else { v.classList.add('hidden'); v.classList.remove('flex'); }
  });
  if (tab === 'clients') loadClients();
  if (tab === 'viewings') loadViewings();
  if (tab === 'deals') loadDeals();
  if (window.Telegram?.WebApp) window.Telegram.WebApp.HapticFeedback?.impactOccurred('light');
}
function escHtml(s) {
  return String(s || '').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
}
function buildApiUrl(path) {
  const tg = window.Telegram?.WebApp;
  let url = path + '?';
  if (tg?.initData) url += 'init_data=' + encodeURIComponent(tg.initData);
  const uid = tg?.initDataUnsafe?.user?.id;
  if (uid) url += '&tg_user_id=' + uid;
  return url;
}
let clientsLoaded = false;
async function loadClients() {
  if (clientsLoaded) return;
  const container = document.getElementById('clients-list');
  try {
    const res = await fetch(buildApiUrl('/api/clients'));
    if (!res.ok) throw new Error('API ' + res.status);
    const data = await res.json();
    const clients = data.clients || [];
    clientsLoaded = true;
    if (!clients.length) {
      container.innerHTML = '<p class="text-center text-outline py-8">Chưa có khách hàng nào.</p>';
      return;
    }
    container.innerHTML = clients.map(cl => `
      <div class="w-full bg-surface-container rounded-xl p-4 border border-surface-variant/40">
        <div class="flex items-start justify-between mb-1">
          <h3 class="font-semibold text-[15px]">${escHtml(cl.name)}</h3>
          <span class="px-2 py-0.5 rounded-full text-[11px]">${escHtml(cl.status_vi || cl.status)}</span>
        </div>
        <p class="text-[13px] text-on-surface-variant mb-1">${escHtml(cl.req_summary)}</p>
        ${cl.phone ? `<p class="text-[13px] text-primary">📞 ${escHtml(cl.phone)}</p>` : ''}
      </div>`).join('');
  } catch (e) {
    container.innerHTML = '<p class="text-center text-error py-8">Không tải được.</p>';
  }
}
let viewingsLoaded = false;
async function loadViewings() {
  if (viewingsLoaded) return;
  const container = document.getElementById('viewings-list');
  try {
    const res = await fetch(buildApiUrl('/api/viewings'));
    if (!res.ok) throw new Error('API ' + res.status);
    const data = await res.json();
    const items = data.viewings || [];
    viewingsLoaded = true;
    if (!items.length) {
      container.innerHTML = '<p class="text-center text-outline py-8">Chưa có lịch xem nào.</p>';
      return;
    }
    container.innerHTML = items.map(v => `
      <div class="w-full bg-surface-container rounded-xl p-4 border border-surface-variant/40">
        <h3 class="font-semibold text-[15px]">${escHtml(v.client_name || 'Khách')}</h3>
        <p class="text-[13px] text-on-surface-variant">${(v.listing_ids || []).length} căn · ${escHtml(v.scheduled_at || '')}</p>
      </div>`).join('');
  } catch (e) {
    container.innerHTML = '<p class="text-center text-error py-8">Không tải được.</p>';
  }
}
let dealsLoaded = false;
async function loadDeals() {
  if (dealsLoaded) return;
  const container = document.getElementById('deals-list');
  const summaryEl = document.getElementById('deals-summary');
  try {
    const res = await fetch(buildApiUrl('/api/deals'));
    if (!res.ok) throw new Error('API ' + res.status);
    const data = await res.json();
    dealsLoaded = true;
    const total = (data.summary || {}).total_commission || 0;
    summaryEl.innerHTML = `<div class="w-full bg-primary-container/15 border border-primary-container/30 rounded-xl p-4"><p class="text-[12px] text-on-surface-variant">Tổng hoa hồng tháng này</p><p class="text-2xl font-bold text-primary-container">${(total/1000000).toFixed(1)}tr</p></div>`;
    const deals = data.deals || data.closed || [];
    if (!deals.length) {
      container.innerHTML = '<p class="text-center text-outline py-8">Chưa có deal nào.</p>';
      return;
    }
    container.innerHTML = deals.map(d => `
      <div class="w-full bg-surface-container rounded-xl p-4 border border-surface-variant/40">
        <div class="flex items-start justify-between">
          <h3 class="font-semibold text-[15px]">${escHtml(d.listing_id || d.id || '')}</h3>
          <span class="text-[13px] font-semibold text-secondary">${((d.commission_vnd||0)/1000000).toFixed(1)}tr</span>
        </div>
        <p class="text-[12px] text-outline mt-1">${d.paid ? '✅ Đã thanh toán' : '⏳ Chưa thanh toán'}</p>
      </div>`).join('');
  } catch (e) {
    container.innerHTML = '<p class="text-center text-error py-8">Không tải được.</p>';
  }
}
