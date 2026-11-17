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
          ${lead.website ? `
            <a href="${escapeHtml(lead.website)}" target="_blank" rel="noopener" style="font-size:0.8rem;">
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
  async function startScrape() {
    const industry = $('input-industry').value.trim();
    const location = $('input-location').value.trim();
    const maxCities = parseInt($('input-max-cities').value, 10) || 10;

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
    const isCountry = commonCountries.includes(location.toLowerCase());

    if (isCountry) {
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

    const payload = {
      business_type: industry,
      scope: isCountry ? 'country' : 'city',
      country: isCountry ? location : null,
      cities: isCountry ? null : location,
      max_cities: maxCities,
    };

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

  async function checkScraperStatus() {
    try {
      const res = await fetch('/api/scrape/status');
      const s = await res.json();

      const running = s.state === 'running' || s.state === 'stopping';
      if (running) {
        state.scraper.isRunning = true;
        if (!state.scraper.pollingInterval) {
          startPolling();
        }
        $('btn-start-scrape').style.display = 'none';
        $('btn-stop-scrape').style.display = 'inline-flex';
        $('scraper-progress-banner').style.display = 'block';

        $('progress-state-text').textContent = `Crawling: ${s.business_type || 'Leads'}`;
        $('progress-city-text').textContent = s.current_city ? `Hub: ${s.current_city}` : 'Initializing...';
        $('progress-leads-count').textContent = (s.total_leads_found || 0).toLocaleString();
        $('progress-pct-text').textContent = `${s.progress_pct || 0}%`;
        $('progress-fill-bar').style.width = `${s.progress_pct || 0}%`;
      } else {
        if (state.scraper.isRunning) {
          state.scraper.isRunning = false;
          clearInterval(state.scraper.pollingInterval);
          state.scraper.pollingInterval = null;
          resetScraperButtons();
          showToast('Scraping completed! Fresh dataset loaded.');
          await loadInitialLeads();
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
  };

  document.addEventListener('DOMContentLoaded', init);
})();
