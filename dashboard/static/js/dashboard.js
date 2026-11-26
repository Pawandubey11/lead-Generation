/**
 * LeadPulse Scraper & Verified Exporter - Client Engine
 * Streamlined Single-Page Architecture for Fast B2B Prospecting & Filtered Export
 */

(function () {
  'use strict';

  // --- Available Exportable Data Fields ---
  const ALL_FIELDS = [
    { key: 'business_name', label: 'Company Name', default: true },
    { key: 'email', label: 'Verified Email', default: true },
    { key: 'phone', label: 'Phone Number', default: true },
    { key: 'website', label: 'Website', default: true },
    { key: 'city', label: 'City', default: true },
    { key: 'address', label: 'Street Address', default: true },
    { key: 'lead_score', label: 'Quality Score (0-100)', default: true },
    { key: 'priority', label: 'Priority (Hot/Warm/Cold)', default: true },
    { key: 'linkedin', label: 'LinkedIn URL', default: false },
    { key: 'instagram', label: 'Instagram Handle', default: false },
    { key: 'facebook', label: 'Facebook Page', default: false },
  ];

  // --- State ---
  const state = {
    leads: [],
    filteredLeads: [],
    search: '',
    industry: '',
    city: '',
    country: '',
    verifiedOnly: true,
    selectedLeadIds: new Set(),
    selectedFields: new Set(ALL_FIELDS.filter(f => f.default).map(f => f.key)),
    scraper: {
      pollingInterval: null,
      isRunning: false,
    }
  };

  // --- Helpers ---
  function $(id) {
    return document.getElementById(id);
  }

  function showToast(msg, isSuccess = true) {
    const container = $('toast-container');
    if (!container) return;
    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.style.borderLeftColor = isSuccess ? '#10B981' : '#EF4444';
    toast.textContent = msg;
    container.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateY(-10px)';
      toast.style.transition = 'all 0.3s ease';
      setTimeout(() => toast.remove(), 300);
    }, 3500);
  }

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function safeWebsiteUrl(rawUrl) {
    if (!rawUrl) return '';
    try {
      const url = new URL(String(rawUrl), window.location.origin);
      if (url.protocol !== 'https:' && url.protocol !== 'http:') return '';
      return url.href;
    } catch (err) {
      return '';
    }
  }

  // --- Initialization ---
  async function init() {
    renderFieldChips();
    bindEvents();
    await loadInitialLeads();
    checkScraperStatus();
  }

  function renderFieldChips() {
    const container = $('field-chips-container');
    container.innerHTML = '';
    ALL_FIELDS.forEach(field => {
      const chip = document.createElement('div');
      const isSelected = state.selectedFields.has(field.key);
      chip.className = `field-chip ${isSelected ? 'selected' : ''}`;
      chip.innerHTML = `
        <span>${isSelected ? '✓' : '+'}</span>
        <span>${field.label}</span>
      `;
      chip.addEventListener('click', () => toggleField(field.key, chip));
      container.appendChild(chip);
    });
    $('selected-fields-count').textContent = state.selectedFields.size;
  }

  function toggleField(key, chipElement) {
    if (state.selectedFields.has(key)) {
      if (state.selectedFields.size <= 1) {
        showToast('At least one data field must remain selected.', false);
        return;
      }
      state.selectedFields.delete(key);
      chipElement.classList.remove('selected');
      chipElement.querySelector('span').textContent = '+';
    } else {
      state.selectedFields.add(key);
      chipElement.classList.add('selected');
      chipElement.querySelector('span').textContent = '✓';
    }
    $('selected-fields-count').textContent = state.selectedFields.size;
  }

  function selectAllFields() {
    ALL_FIELDS.forEach(f => state.selectedFields.add(f.key));
    renderFieldChips();
    showToast('All data fields selected for export.');
  }

  function bindEvents() {
    // Search keyword input
    $('filter-search').addEventListener('input', (e) => {
      state.search = e.target.value.trim().toLowerCase();
      applyLocalFilter();
    });

    // Industry filter input
    $('filter-industry').addEventListener('input', (e) => {
      state.industry = e.target.value.trim();
      applyLocalFilter();
    });

    // City filter input
    $('filter-city').addEventListener('input', (e) => {
      state.city = e.target.value.trim();
      applyLocalFilter();
    });

    // Country filter input
    $('filter-country').addEventListener('input', (e) => {
      state.country = e.target.value.trim();
      applyLocalFilter();
    });
  }

  // --- Data Loading ---
  async function loadInitialLeads() {
    try {
      const res = await fetch('/api/leads?page=1&page_size=2000');
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      const data = await res.json();
      state.leads = data.data || data.leads || [];
      
      applyLocalFilter();
    } catch (err) {
      console.error('Error loading leads:', err);
      showToast('Error fetching leads dataset.', false);
    }
  }

  async function refreshLeadsWithoutToast() {
    try {
      const res = await fetch('/api/leads?page=1&page_size=2000', {
        cache: 'no-store',
        headers: { 'Cache-Control': 'no-cache' },
      });
      if (!res.ok) return;
      const data = await res.json();
      state.leads = data.data || data.leads || [];
      applyLocalFilter();
    } catch (err) {
      console.error('Error refreshing live leads:', err);
    }
  }

  // --- Local Filtering & Verification Check ---
  function isLeadVerified(lead) {
    if (!lead) return false;
    const email = String(lead.email || '').trim();
    const hasValidEmail = email.includes('@') && email.includes('.') && !email.toLowerCase().includes('example') && !email.toLowerCase().includes('domain');
    const completeness = Number(lead.contact_completeness) || 0;
    const hasPhone = Boolean(lead.phone && String(lead.phone).trim());
    return hasValidEmail || (completeness >= 40 && hasPhone);
  }

  function applyLocalFilter() {
    state.filteredLeads = state.leads.filter(lead => {
      // 1. Verification check
      if (state.verifiedOnly && !isLeadVerified(lead)) {
        return false;
      }

      // 2. Search keyword filter
      if (state.search) {
        const q = state.search;
        const name = (lead.business_name || '').toLowerCase();
        const email = (lead.email || '').toLowerCase();
        const city = (lead.city || '').toLowerCase();
        const phone = (lead.phone || '').toLowerCase();
        const spin = (lead.spin || '').toLowerCase();
        
        let match = name.includes(q) || email.includes(q) || city.includes(q) || phone.includes(q) || spin.includes(q);
        if (!match && (q === 'b2b' || q === 'b2b software' || q === 'b2b companies')) {
          const b2bTerms = ['software', 'it', 'saas', 'cloud', 'web', 'agency', 'consulting', 'cyber', 'analytics', 'erp', 'wholesale', 'b2b', 'distributor', 'manufacturing', 'logistics', 'unternehmen'];
          match = b2bTerms.some(term => spin.includes(term) || name.includes(term));
        }
        if (!match) {
          return false;
        }
      }

      // 3. Industry filter
      if (state.industry && state.industry.toLowerCase() !== 'all') {
        const ind = state.industry.toLowerCase();
        const spin = (lead.spin || '').toLowerCase();
        const name = (lead.business_name || '').toLowerCase();
        
        let match = false;
        if (ind === 'b2b' || ind === 'b2b software' || ind === 'b2b companies') {
          const b2bTerms = ['software', 'it', 'saas', 'cloud', 'web', 'agency', 'consulting', 'cyber', 'analytics', 'erp', 'wholesale', 'b2b', 'distributor', 'manufacturing', 'logistics', 'unternehmen'];
          match = b2bTerms.some(term => spin.includes(term) || name.includes(term));
        } else {
          match = spin.includes(ind) || name.includes(ind);
        }
        if (!match) {
          return false;
        }
      }

      // 4. City filter
      if (state.city && state.city.toLowerCase() !== 'all') {
        const c = state.city.toLowerCase();
        const leadCity = (lead.city || '').toLowerCase();
        const addr = (lead.address || '').toLowerCase();
        if (!leadCity.includes(c) && !addr.includes(c)) {
          return false;
        }
      }

      // 5. Country filter
      if (state.country && state.country.toLowerCase() !== 'all') {
        const cntry = state.country.toLowerCase();
        const spin = (lead.spin || '').toLowerCase();
        const addr = (lead.address || '').toLowerCase();
        const city = (lead.city || '').toLowerCase();
        if (!spin.includes(cntry) && !addr.includes(cntry) && !city.includes(cntry)) {
          return false;
        }
      }

      return true;
    });

    // Auto select all currently matching
    state.selectedLeadIds = new Set(state.filteredLeads.map((_, idx) => idx));

    renderTable();
    updateExportSummary();
    updateFilenamePreview();
  }

  function renderTable() {
    const tbody = $('leads-table-body');
    tbody.innerHTML = '';

    if (state.filteredLeads.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="7" style="text-align:center; padding:3.5rem 1rem; color:#64748B;">
            <div style="font-size:1.15rem; font-weight:700; color:#CBD5E1; margin-bottom:0.4rem;">No leads matching active filters</div>
            <div>Try adjusting your Industry, City, or Country filters above, or launch a new scrape job.</div>
          </td>
        </tr>
      `;
      return;
    }

    state.filteredLeads.forEach((lead, idx) => {
      const isChecked = state.selectedLeadIds.has(idx);
      const isVerified = isLeadVerified(lead);
      const score = Math.round(Number(lead.lead_score) || 0);

      let scoreClass = 'low';
      if (score >= 70) scoreClass = 'high';
      else if (score >= 40) scoreClass = 'mid';

      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td>
          <input type="checkbox" style="accent-color:var(--primary); cursor:pointer;" ${isChecked ? 'checked' : ''} onchange="window.LeadScraperApp.toggleLeadSelect(${idx}, this.checked)">
        </td>
        <td>
          <div class="biz-name-block">
            <span class="biz-name-text">
              ${escapeHtml(lead.business_name || 'Business')}
              ${isVerified ? '<span class="verified-icon" title="Validated & Verified Lead">✓</span>' : ''}
            </span>
            <span class="biz-sub-text">${escapeHtml(lead.spin || lead.address || '')}</span>
          </div>
        </td>
        <td>
          ${lead.email ? `
            <div class="email-copy-pill" onclick="window.LeadScraperApp.copyText('${escapeHtml(lead.email)}', 'Email copied!')" title="Click to copy">
              <span>✉</span>
              <span>${escapeHtml(lead.email)}</span>
            </div>
          ` : '<span style="color:#64748B;">—</span>'}
        </td>
        <td>
          <span style="font-family:var(--font-mono); font-size:0.8rem; color:#E2E8F0;">
            ${escapeHtml(lead.phone || '—')}
          </span>
        </td>
        <td>
          ${safeWebsiteUrl(lead.website) ? `
            <a href="${escapeHtml(safeWebsiteUrl(lead.website))}" target="_blank" rel="noopener noreferrer" style="font-size:0.8rem;">
              Visit Website ↗
            </a>
          ` : '<span style="color:#64748B;">—</span>'}
        </td>
        <td>
          <span style="font-size:0.85rem; color:#CBD5E1;">${escapeHtml(lead.city || '—')}</span>
        </td>
        <td style="text-align:right;">
          <span class="score-badge ${scoreClass}">${score}</span>
        </td>
      `;

      tbody.appendChild(tr);
    });

    $('header-total-leads').textContent = state.filteredLeads.length.toLocaleString();
  }

  function updateExportSummary() {
    const count = state.selectedLeadIds.size;
    const total = state.filteredLeads.length;
    $('export-summary-text').innerHTML = `Ready to export <strong>${count}</strong> of <strong>${total}</strong> filtered leads`;
    $('select-all-leads').checked = count === total && total > 0;
  }

  function getCalculatedFilename(extension = 'xlsx') {
    let ind = state.industry.trim();
    let loc = state.city.trim() || state.country.trim();

    if (!ind && state.filteredLeads.length > 0) {
      const firstSpin = state.filteredLeads[0].spin || '';
      if (firstSpin && firstSpin.includes(' in ')) {
        const parts = firstSpin.split(' in ');
        ind = parts[0].trim();
        if (!loc) loc = parts[1].trim();
      } else if (firstSpin) {
        ind = firstSpin.trim();
      }
    }

    let parts = [];
    if (ind) parts.push(ind.replace(/[^\w\s-]/g, '').trim().replace(/\s+/g, '_'));
    if (loc) parts.push(loc.replace(/[^\w\s-]/g, '').trim().replace(/\s+/g, '_'));
    if (parts.length === 0 && state.search) {
      parts.push(state.search.replace(/[^\w\s-]/g, '').trim().replace(/\s+/g, '_'));
    }

    if (parts.length === 0) {
      return `verified_leads_export.${extension}`;
    }

    return `${parts.join('_')}_leads.${extension}`;
  }

  function updateFilenamePreview() {
    const fn = getCalculatedFilename('xlsx');
    const el = $('export-filename-preview');
    if (el) {
      el.textContent = `Target filename: ${fn}`;
    }
  }

  // --- Row Checkbox Toggles ---
  function toggleLeadSelect(idx, checked) {
    if (checked) {
      state.selectedLeadIds.add(idx);
    } else {
      state.selectedLeadIds.delete(idx);
    }
    updateExportSummary();
  }

  function toggleSelectAll(checked) {
    if (checked) {
      state.filteredLeads.forEach((_, idx) => state.selectedLeadIds.add(idx));
    } else {
      state.selectedLeadIds.clear();
    }
    renderTable();
    updateExportSummary();
  }

  // --- Reset Filters ---
  function resetFilters() {
    state.search = '';
    state.industry = '';
    state.city = '';
    state.country = '';
    state.verifiedOnly = true;

    $('filter-search').value = '';
    $('filter-industry').value = '';
    $('filter-city').value = '';
    $('filter-country').value = '';

    const btn = $('toggle-verified');
    const check = $('verified-toggle-checkbox');
    btn.classList.remove('inactive');
    check.textContent = '☑';

    applyLocalFilter();
    showToast('Filters reset to default.');
  }

  // --- Verified Toggle ---
  function toggleVerifiedOnly() {
    state.verifiedOnly = !state.verifiedOnly;
    const btn = $('toggle-verified');
    const check = $('verified-toggle-checkbox');

    if (state.verifiedOnly) {
      btn.classList.remove('inactive');
      check.textContent = '☑';
      showToast('Filtering for Validated & Verified leads only.');
    } else {
      btn.classList.add('inactive');
      check.textContent = '☐';
      showToast('Showing all raw scraped entries.');
    }

    applyLocalFilter();
  }

  function toggleFieldSelector() {
    const panel = $('field-selector-panel');
    panel.style.display = panel.style.display === 'none' ? 'flex' : 'none';
  }

  function setIndustry(name) {
    $('input-industry').value = name;
    $('filter-industry').value = name;
    state.industry = name;
    applyLocalFilter();
  }

  function copyText(text, successMessage) {
    if (navigator.clipboard) {
      navigator.clipboard.writeText(text).then(() => {
        showToast(successMessage);
      });
    }
  }

  // --- Scraper Operations ---
  let _localityModeEnabled = false;
  let _discoveredLocalities = [];

  function onLocalityModeToggle(enabled) {
    _localityModeEnabled = enabled;
    const statusEl = $('locality-mode-status');
    if (!statusEl) return;
    if (enabled) {
      statusEl.style.display = 'inline';
      statusEl.textContent = 'Localities will be auto-discovered when you start scraping.';
    } else {
      statusEl.style.display = 'none';
      statusEl.textContent = '';
    }
  }

  async function discoverLocalities(city, country, businessType) {
    try {
      const statusEl = $('locality-mode-status');
      if (statusEl) { statusEl.style.display = 'inline'; statusEl.textContent = '🔍 Discovering localities…'; }
      const params = new URLSearchParams({ city, country: country || 'India', business_type: businessType });
      const res = await fetch(`/api/locality/discover?${params}`);
      if (!res.ok) throw new Error('Discovery API error');
      const data = await res.json();
      _discoveredLocalities = data.localities || [];
      if (statusEl) statusEl.textContent = `✅ Found ${_discoveredLocalities.length} localities via ${data.source || 'OSM'}`;
      return _discoveredLocalities;
    } catch (err) {
      const statusEl = $('locality-mode-status');
      if (statusEl) statusEl.textContent = '⚠️ Discovery failed — using city-level search';
      return [];
    }
  }

  async function startScrape() {
    const industry = $('input-industry').value.trim();
    const location = $('input-location').value.trim();
    const maxCities = parseInt($('input-max-cities').value, 10) || 10;
    const maxLeadsPerCity = parseInt($('input-max-leads-per-city')?.value, 10) || 20;

    if (!industry) {
      showToast('Please enter a target industry.', false);
      $('input-industry').focus();
      return;
    }
    if (!location) {
      showToast('Please enter a city or country.', false);
      $('input-location').focus();
      return;
    }

    // Set active filters to match the current scrape immediately
    $('filter-industry').value = industry;
    state.industry = industry;

    const commonCountries = ['germany', 'united states', 'usa', 'united kingdom', 'uk', 'india', 'canada', 'australia', 'france', 'uae'];
    const locationParts = location.split(',').map(part => part.trim()).filter(Boolean);
    const isCountryCityPair = locationParts.length === 2;
    const isCountry = !isCountryCityPair && commonCountries.includes(location.toLowerCase());

    if (isCountryCityPair) {
      $('filter-city').value = locationParts[0];
      state.city = locationParts[0];
      $('filter-country').value = locationParts[1];
      state.country = locationParts[1];
    } else if (isCountry) {
      $('filter-country').value = location;
      state.country = location;
      $('filter-city').value = '';
      state.city = '';
    } else {
      $('filter-city').value = location;
      state.city = location;
      $('filter-country').value = '';
      state.country = '';
    }

    updateFilenamePreview();

    let payload = {
      business_type: industry,
      scope: isCountry ? 'country' : 'city',
      country: isCountry ? location : (isCountryCityPair ? locationParts[1] : null),
      cities: isCountry ? null : (isCountryCityPair ? locationParts[0] : location),
      max_cities: maxCities,
      max_leads_per_city: maxLeadsPerCity,
    };

    if (_localityModeEnabled && !isCountry) {
      $('btn-start-scrape').disabled = true;
      const targetCity = isCountryCityPair ? locationParts[0] : location;
      const countryGuess = isCountryCityPair ? locationParts[1] : 'India';
      const localities = await discoverLocalities(targetCity, countryGuess, industry);
      $('btn-start-scrape').disabled = false;
      if (localities.length > 0) {
        payload = {
          business_type: industry,
          scope: 'city',
          city: targetCity,
          country: countryGuess,
          localities: localities.map(l => l.name),
          max_cities: maxCities,
          max_leads_per_city: maxLeadsPerCity,
        };
        showToast(`🗺️ Locality mode: ${localities.length} areas in ${targetCity}`);
      } else {
        showToast('⚠️ No localities found — using standard city search');
      }
    }

    try {
      $('btn-start-scrape').style.display = 'none';
      $('btn-stop-scrape').style.display = 'inline-flex';
      $('scraper-progress-banner').style.display = 'block';

      const res = await fetch('/api/scrape/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json();

      if (data.status === 'started' || data.status === 'already_running') {
        showToast(`Scraper launched for "${industry}" in ${location}!`);
        state.scraper.isRunning = true;
        startPolling();
      } else {
        showToast(data.message || 'Could not start scraper', false);
        resetScraperButtons();
      }
    } catch (err) {
      showToast('Failed to connect to scraper service.', false);
      resetScraperButtons();
    }
  }

  async function stopScrape() {
    try {
      await fetch('/api/scrape/stop', { method: 'POST' });
      showToast('Stopping crawler operations...');
    } catch (err) {
      showToast('Error requesting stop.', false);
    }
  }

  function startPolling() {
    if (state.scraper.pollingInterval) clearInterval(state.scraper.pollingInterval);
    state.scraper.pollingInterval = setInterval(checkScraperStatus, 1000);
  }

  function renderCoveragePanel(s) {
    const panel = document.getElementById('coverage-panel');
    if (!panel) return;
    const localities = s.localities || [];
    const completed = s.localities_completed || [];
    const failed = s.localities_failed || [];
    const inProgress = (s.state === 'running') ? (s.current_locality || '') : '';
    const leadCounts = s.locality_lead_counts || {};
    const total = localities.length;
    const coveragePct = total > 0 ? Math.round((completed.length / total) * 100) : 0;
    const pending = localities.filter(l => !completed.includes(l) && !failed.includes(l) && l !== inProgress);

    if (!s.is_locality_mode && total === 0) { panel.style.display = 'none'; return; }
    panel.style.display = 'block';

    const setText = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
    setText('coverage-city-label', s.country ? `— ${s.country}` : '');
    setText('coverage-done-count', completed.length);
    setText('coverage-inprogress-count', inProgress ? 1 : 0);
    setText('coverage-pending-count', pending.length);
    setText('coverage-failed-count', failed.length);
    setText('coverage-pct', `${coveragePct}%`);

    const bar = document.getElementById('coverage-progress-bar');
    if (bar) bar.style.width = `${coveragePct}%`;

    const grid = document.getElementById('coverage-locality-grid');
    if (grid && total > 0) {
      grid.innerHTML = localities.map(loc => {
        let bg = '#1e293b', border = '#334155', color = '#94A3B8', emoji = '⏳';
        if (completed.includes(loc)) { bg = '#14532d33'; border = '#22c55e'; color = '#22c55e'; emoji = '✅'; }
        else if (failed.includes(loc)) { bg = '#7f1d1d33'; border = '#ef4444'; color = '#ef4444'; emoji = '❌'; }
        else if (loc === inProgress) { bg = '#78350f33'; border = '#f59e0b'; color = '#f59e0b'; emoji = '🔄'; }
        const count = leadCounts[loc] !== undefined ? ` (${leadCounts[loc]})` : '';
        return `<span style="display:inline-flex;align-items:center;gap:0.3rem;padding:0.25rem 0.6rem;border-radius:999px;font-size:0.75rem;border:1px solid ${border};background:${bg};color:${color};">${emoji} ${escapeHtml(loc)}${count}</span>`;
      }).join('');
    }

    const tableWrap = document.getElementById('coverage-table-wrap');
    const tbody = document.getElementById('coverage-table-body');
    if (tbody && total > 0) {
      tableWrap.style.display = 'block';
      tbody.innerHTML = localities.map(loc => {
        let statusBadge = '<span style="color:#94A3B8;">⏳ Pending</span>';
        if (completed.includes(loc)) statusBadge = '<span style="color:#22c55e;">✅ Completed</span>';
        else if (failed.includes(loc)) statusBadge = '<span style="color:#ef4444;">❌ Failed</span>';
        else if (loc === inProgress) statusBadge = '<span style="color:#f59e0b;">🔄 In Progress</span>';
        const count = leadCounts[loc] !== undefined ? leadCounts[loc] : '—';
        return `<tr style="border-bottom:1px solid #1e293b;">
          <td style="padding:0.35rem 0.5rem;">${escapeHtml(loc)}</td>
          <td style="text-align:center;padding:0.35rem 0.5rem;">${statusBadge}</td>
          <td style="text-align:right;padding:0.35rem 0.5rem;color:#38bdf8;font-weight:600;">${count}</td>
        </tr>`;
      }).join('');
    }
  }

  async function checkScraperStatus() {
    try {
      const res = await fetch('/api/scrape/status');
      const s = await res.json();

      const running = s.state === 'running' || s.state === 'stopping';
      if (s.is_locality_mode || (s.localities && s.localities.length > 0)) {
        renderCoveragePanel(s);
      }

      if (running) {
        state.scraper.isRunning = true;
        if (!state.scraper.pollingInterval) {
          startPolling();
        }
        $('btn-start-scrape').style.display = 'none';
        $('btn-stop-scrape').style.display = 'inline-flex';
        $('scraper-progress-banner').style.display = 'block';

        const areaLabel = s.is_locality_mode
          ? (s.current_locality ? `Locality: ${s.current_locality} (${s.locality_index || 0}/${s.total_localities || 0})` : 'Discovering localities…')
          : (s.current_city ? `Hub: ${s.current_city}` : 'Initializing...');

        $('progress-state-text').textContent = `Crawling: ${s.business_type || 'Leads'}`;
        $('progress-city-text').textContent = areaLabel;
        $('progress-leads-count').textContent = (s.total_leads_found || 0).toLocaleString();
        $('progress-pct-text').textContent = `${s.progress_pct || 0}%`;
        $('progress-fill-bar').style.width = `${s.progress_pct || 0}%`;
        await refreshLeadsWithoutToast();
      } else {
        if (state.scraper.isRunning) {
          state.scraper.isRunning = false;
          clearInterval(state.scraper.pollingInterval);
          state.scraper.pollingInterval = null;
          resetScraperButtons();
          showToast('Scraping completed! Fresh dataset loaded.');
          await loadInitialLeads();
          renderCoveragePanel(s);
        }
      }
    } catch (err) {
      // Ignore network hiccup
    }
  }

  function resetScraperButtons() {
    $('btn-start-scrape').style.display = 'inline-flex';
    $('btn-stop-scrape').style.display = 'none';
  }

  // --- Export Engine ---
  function exportData(format) {
    const fields = Array.from(state.selectedFields).join(',');
    const verifiedOnly = state.verifiedOnly ? 'true' : 'false';
    const search = state.search ? encodeURIComponent(state.search) : '';
    const industry = state.industry ? encodeURIComponent(state.industry) : '';
    const city = state.city ? encodeURIComponent(state.city) : '';
    const country = state.country ? encodeURIComponent(state.country) : '';

    const url = `/api/export/custom?format=${format}&fields=${fields}&verified_only=${verifiedOnly}&search=${search}&industry=${industry}&city=${city}&country=${country}`;
    showToast(`Downloading ${format.toUpperCase()} export matching current filters...`);
    window.location.href = url;
  }

  async function reloadLeads() {
    showToast('Refreshing leads from server...');
    await loadInitialLeads();
    showToast(`Loaded ${state.leads.length} leads successfully!`);
  }

  // --- Public API ---
  window.LeadScraperApp = {
    startScrape,
    stopScrape,
    setIndustry,
    toggleFieldSelector,
    selectAllFields,
    toggleVerifiedOnly,
    toggleLeadSelect,
    toggleSelectAll,
    resetFilters,
    reloadLeads,
    copyText,
    exportData,
    onLocalityModeToggle,
  };

  document.addEventListener('DOMContentLoaded', init);
})();

// ================================================================
// AI Business Intelligence � SystemaOps Opportunity Intelligence
// ================================================================

const AI = {
  selectedNames: new Set(),
  pollTimer: null,
  currentReport: null,
  currentTab: 'overview',
  allLeads: [],
};

// ---- Initialisation ----
async function initAIPanel() {
  try {
    const cfg = await fetch('/api/ai/config').then(r => r.json());
    const badge = document.getElementById('ai-mode-badge');
    if (badge) {
      badge.textContent = cfg.mock_mode ? 'MOCK MODE' : cfg.provider.toUpperCase() + ' / ' + cfg.model;
      badge.style.background = cfg.mock_mode ? '#4c1d95' : '#065f46';
      badge.style.color = cfg.mock_mode ? '#c4b5fd' : '#6ee7b7';
    }
  } catch (e) { /* non-critical */ }
  await refreshAILeadList();
  startAIStatusPoll();
}

async function refreshAILeadList() {
  try {
    const data = await fetch('/api/leads?page=1&page_size=200').then(r => r.json());
    AI.allLeads = data.data || data.leads || [];
    renderAILeadRows();
    document.getElementById('ai-stat-total').textContent = AI.selectedNames.size;
  } catch (e) { console.warn('AI lead list refresh error', e); }
}

function renderAILeadRows() {
  const container = document.getElementById('ai-lead-rows');
  if (!container) return;
  const reports = window._aiReports || {};
  container.innerHTML = AI.allLeads.map((ld, i) => {
    const name = ld.business_name || '';
    const checked = AI.selectedNames.has(name);
    const rep = reports[name];
    let dotColor = '#4b5563';
    let statusText = '';
    if (rep) {
      if (rep.research_status === 'completed') { dotColor = '#34d399'; statusText = '?'; }
      else if (rep.research_status === 'failed') { dotColor = '#f87171'; statusText = '?'; }
      else { dotColor = '#fbbf24'; statusText = '�'; }
    }
    return '<div class="ai-lead-row">' +
      '<input type="checkbox" ' + (checked ? 'checked' : '') +
        ' onchange="toggleAILead(\'' + name.replace(/'/g, "\\'") + '\', this.checked)">' +
      '<span class="ai-status-dot" style="background:' + dotColor + '"></span>' +
      '<span style="flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">' + (name || 'Unknown') + '</span>' +
      '<span style="font-size:0.7rem; color:#6b7280;">' + statusText + '</span>' +
      (rep && rep.research_status === 'completed'
        ? '<button class="ai-view-btn" onclick="viewAIReport(\'' + name.replace(/'/g, "\\'") + '\')">View ?</button>'
        : '') +
      '</div>';
  }).join('');
}

function toggleAILead(name, checked) {
  if (checked) AI.selectedNames.add(name);
  else AI.selectedNames.delete(name);
  document.getElementById('ai-stat-total').textContent = AI.selectedNames.size;
}

function aiSelectAll() {
  AI.allLeads.forEach(ld => { if (ld.business_name) AI.selectedNames.add(ld.business_name); });
  renderAILeadRows();
  document.getElementById('ai-stat-total').textContent = AI.selectedNames.size;
}

// ---- Research control ----
async function startAIResearch() {
  if (AI.selectedNames.size === 0) {
    showToast('Select at least one lead first', 'warning'); return;
  }
  try {
    const res = await fetch('/api/ai/research/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ business_names: Array.from(AI.selectedNames) }),
    }).then(r => r.json());

    if (res.ok === false) { showToast('Error: ' + res.error, 'error'); return; }
    showToast('AI research started for ' + (res.total || '?') + ' companies', 'success');
    document.getElementById('btn-ai-stop').style.display = '';
    document.getElementById('ai-progress-row').style.display = '';
  } catch (e) { showToast('Failed to start research: ' + e, 'error'); }
}

async function stopAIResearch() {
  await fetch('/api/ai/research/stop', { method: 'POST' });
  showToast('Research stopping�', 'info');
}

async function retryFailedResearch() {
  const res = await fetch('/api/ai/research/retry', { method: 'POST' }).then(r => r.json());
  if (res.ok) showToast('Retrying failed companies�', 'info');
  else showToast('Nothing to retry', 'warning');
}

// ---- Status polling ----
function startAIStatusPoll() {
  if (AI.pollTimer) clearInterval(AI.pollTimer);
  AI.pollTimer = setInterval(pollAIStatus, 3000);
}

async function pollAIStatus() {
  try {
    const st = await fetch('/api/ai/status').then(r => r.json());
    updateAIProgressUI(st);

    if (st.state === 'completed' || st.state === 'error') {
      const reps = await fetch('/api/ai/reports').then(r => r.json());
      window._aiReports = reps;
      renderAILeadRows();
      document.getElementById('btn-ai-stop').style.display = 'none';
      if (Object.values(reps).some(r => r.research_status === 'failed')) {
        document.getElementById('btn-ai-retry').style.display = '';
      }
    }
  } catch (e) { /* non-critical */ }
}

function updateAIProgressUI(st) {
  document.getElementById('ai-stat-done').textContent = st.completed || 0;
  document.getElementById('ai-stat-failed').textContent = st.failed || 0;
  document.getElementById('ai-stat-queue').textContent = (st.queue || []).length;
  const pct = st.total > 0 ? Math.round(((st.completed + st.failed) / st.total) * 100) : 0;
  document.getElementById('ai-progress-bar').style.width = pct + '%';
  document.getElementById('ai-progress-counts').textContent =
    (st.completed + st.failed) + ' / ' + st.total;
  const label = document.getElementById('ai-progress-label');
  if (st.state === 'running') {
    label.textContent = st.current_company ? 'Researching: ' + st.current_company : 'Starting�';
  } else if (st.state === 'completed') {
    label.textContent = '? Research complete';
  } else if (st.state === 'error') {
    label.textContent = '? Error: ' + (st.error || 'unknown');
  }
}

// ---- Report viewer ----
async function viewAIReport(name) {
  try {
    const rep = await fetch('/api/ai/report/' + encodeURIComponent(name)).then(r => r.json());
    AI.currentReport = rep;
    document.getElementById('ai-report-title').textContent = '?? ' + name;
    document.getElementById('ai-report-section').style.display = '';
    switchAITab(AI.currentTab);
  } catch (e) { showToast('Could not load report: ' + e, 'error'); }
}

function closeAIReport() {
  document.getElementById('ai-report-section').style.display = 'none';
  AI.currentReport = null;
}

function switchAITab(tab) {
  AI.currentTab = tab;
  document.querySelectorAll('.ai-tab').forEach(b => b.classList.remove('active'));
  const btn = document.getElementById('tab-' + tab);
  if (btn) btn.classList.add('active');
  renderAITabContent(tab);
}

function renderAITabContent(tab) {
  const r = AI.currentReport;
  const el = document.getElementById('ai-tab-content');
  if (!r || !el) return;
  let html = '';
  switch (tab) {
    case 'overview':
      html = section('Company Overview', r.company_overview) +
             section('Industry', r.industry + ' | ' + r.business_model) +
             section('Products & Services', r.products_services) +
             section('Existing Capabilities', r.existing_capabilities) +
             section('Technology Signals', r.technology_signals);
      break;
    case 'website':
      html = badge('Website Status', r.website_status) +
             section('Website Summary', r.website_summary) +
             section('? Strengths', r.website_strengths) +
             section('?? Problems', r.website_problems) +
             section('?? Improvement Opportunities', r.website_improvement_opportunities) +
             section('?? Recommendations', r.website_recommendations);
      break;
    case 'opportunity':
      html = section('SystemaOps Opportunity', r.systemaops_business_opportunity) +
             badge('Priority', r.opportunity_priority) + ' ' + badge('Confidence', r.recommendation_confidence) + '<br><br>' +
             section('Strongest Match', r.strongest_opportunity) +
             section('Recommended Services', r.recommended_services) +
             section('Business Challenge', r.potential_business_challenge) +
             section('Evidence', r.evidence) +
             section('Expected Benefit', r.expected_benefit);
      break;
    case 'meeting':
      html = section('Meeting Opening', r.meeting_opening) +
             section('Discovery Questions', r.discovery_questions) +
             section('Sales Pitch', r.sales_pitch) +
             section('Next Step', r.suggested_next_action);
      break;
    case 'outreach':
      html = copyBox('Email Subject', r.email_subject) +
             copyBox('Personalized Email', r.personalized_email) +
             copyBox('LinkedIn Message', r.linkedin_message) +
             copyBox('Follow-up Message', r.follow_up_message);
      break;
    case 'content':
      html = section('Post Topic', r.post_topic) +
             copyBox('Post Text', r.post_text) +
             section('Call to Action', r.call_to_action);
      break;
  }
  el.innerHTML = html || '<span style="color:#6b7280">No data</span>';
}

function section(title, text) {
  if (!text) return '';
  return '<div style="margin-bottom:0.9rem;"><div style="font-size:0.7rem; font-weight:700; color:#7c3aed; text-transform:uppercase; margin-bottom:0.3rem;">' +
    title + '</div><div style="color:#d1d5db;">' + escHtml(text) + '</div></div>';
}
function badge(label, value) {
  if (!value) return '';
  const colors = { high:'#dc2626', medium:'#d97706', low:'#059669', completed:'#059669', available:'#059669' };
  const bg = colors[String(value).toLowerCase()] || '#4c1d95';
  return '<span style="font-size:0.7rem; background:' + bg + '; color:#fff; padding:0.2rem 0.5rem; border-radius:4px; font-weight:600;">' +
    label + ': ' + value + '</span>';
}
function copyBox(title, text) {
  if (!text) return '';
  const id = 'copy-' + Math.random().toString(36).slice(2);
  return '<div style="margin-bottom:0.9rem;"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.3rem;">' +
    '<div style="font-size:0.7rem; font-weight:700; color:#7c3aed; text-transform:uppercase;">' + title + '</div>' +
    '<button onclick="copyAIText(\'' + id + '\')" style="font-size:0.65rem;background:#2d2d4e;color:#a78bfa;border:none;padding:0.2rem 0.5rem;border-radius:4px;cursor:pointer;">Copy</button>' +
    '</div><div id="' + id + '" style="color:#d1d5db; background:#0f0f1a; border-radius:6px; padding:0.6rem; white-space:pre-wrap;">' + escHtml(text) + '</div></div>';
}
function escHtml(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
function copyAIText(id) {
  const el = document.getElementById(id);
  if (el) navigator.clipboard.writeText(el.textContent).then(() => showToast('Copied!', 'success'));
}

async function exportEnrichedCSV() {
  window.location.href = '/api/ai/export/enriched';
}

// ---- Expose to global ----
window.startAIResearch = startAIResearch;
window.stopAIResearch = stopAIResearch;
window.retryFailedResearch = retryFailedResearch;
window.aiSelectAll = aiSelectAll;
window.toggleAILead = toggleAILead;
window.viewAIReport = viewAIReport;
window.closeAIReport = closeAIReport;
window.switchAITab = switchAITab;
window.copyAIText = copyAIText;
window.exportEnrichedCSV = exportEnrichedCSV;

// Auto-init when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initAIPanel);
} else {
  setTimeout(initAIPanel, 500);
}