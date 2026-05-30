(function () {
  const state = {
    payload: null,
    rows: [],
    filteredRows: [],
    selected: new Set(),
    activeRowId: '',
    sort: { key: 'current_value', dir: 'asc' },
    runInFlight: false,
    activePane: 'detail',
    previewMode: 'selected',
  };

  const el = {
    sourcePath: document.getElementById('sourcePath'),
    runButton: document.getElementById('runButton'),
    exportButton: document.getElementById('exportButton'),
    searchInput: document.getElementById('searchInput'),
    bucketFilter: document.getElementById('bucketFilter'),
    caseFilter: document.getElementById('caseFilter'),
    reasonFilter: document.getElementById('reasonFilter'),
    warningFilter: document.getElementById('warningFilter'),
    selectAllButton: document.getElementById('selectAllButton'),
    deselectAllButton: document.getElementById('deselectAllButton'),
    rowsBody: document.getElementById('rowsBody'),
    detailTab: document.getElementById('detailTab'),
    previewTab: document.getElementById('previewTab'),
    previewModeBar: document.getElementById('previewModeBar'),
    selectedPreviewButton: document.getElementById('selectedPreviewButton'),
    libraryPreviewButton: document.getElementById('libraryPreviewButton'),
    detailPane: document.getElementById('detailPane'),
    previewPane: document.getElementById('previewPane'),
  };

  el.sourcePath.value = window.DEFAULT_SOURCE || '';

  function renderRunButton() {
    el.runButton.textContent = state.runInFlight ? 'Running' : 'Run Normalize';
    el.runButton.disabled = state.runInFlight;
    el.runButton.classList.toggle('is-running', state.runInFlight);
  }

  function renderSelectionButtons() {
    const filteredCount = state.filteredRows.length;
    const selectedVisibleCount = state.filteredRows.filter(row => state.selected.has(row.result_id)).length;
    el.selectAllButton.disabled = !filteredCount;
    el.deselectAllButton.disabled = !selectedVisibleCount;
    el.selectAllButton.textContent = filteredCount ? `Select all (${filteredCount})` : 'Select all';
    el.deselectAllButton.textContent = selectedVisibleCount ? `Deselect all (${selectedVisibleCount})` : 'Deselect all';
  }

  function renderPaneTabs() {
    const previewVisible = state.activePane === 'preview';
    el.detailTab.classList.toggle('is-active', !previewVisible);
    el.previewTab.classList.toggle('is-active', previewVisible);
    el.detailPane.hidden = previewVisible;
    el.previewPane.hidden = !previewVisible;
    el.previewModeBar.hidden = !previewVisible;
    el.selectedPreviewButton.classList.toggle('is-active', state.previewMode === 'selected');
    el.libraryPreviewButton.classList.toggle('is-active', state.previewMode === 'library');
  }

  function escapeHtml(value) {
    return String(value || '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  }

  function activeRows() {
    return (state.payload?.movie_results || []).map(row => ({
      ...row,
      reason_bucket: buildReasonBucket(row),
      linked_changes: (row.linked_changes || []).length ? row.linked_changes : linkedChangesForRow(row),
    }));
  }

  function linkedChangesForRow(row) {
    const changes = state.payload?.proposed_changes || [];
    const ids = new Set(row.change_ids || []);
    return changes.filter(change => ids.has(change.item_id));
  }

  function buildReasonBucket(row) {
    const codes = row.reason_codes || [];
    if (codes.some(code => code.includes('collision'))) return 'collision';
    if (codes.some(code => code.includes('artifact'))) return 'artifact';
    if (codes.some(code => code.includes('package'))) return 'package';
    if (codes.some(code => code.includes('subtitle_merge'))) return 'subtitle';
    return codes[0] || (row.confidence === 'unchanged' ? 'unchanged' : 'normalized');
  }

  function applyFilters() {
    const query = el.searchInput.value.trim().toLowerCase();
    const bucket = el.bucketFilter.value;
    const caseFilter = el.caseFilter.value;
    const reasonFilter = el.reasonFilter.value;
    const warningFilter = el.warningFilter.value;
    let rows = activeRows().filter(row => {
      if (bucket === 'actionable' && !row.actionable) return false;
      if (bucket === 'unchanged' && row.confidence !== 'unchanged') return false;
      if ((bucket === 'safe' || bucket === 'review') && row.confidence !== bucket) return false;
      if (query) {
        const haystack = `${row.current_value} ${row.projected_path}`.toLowerCase();
        if (!haystack.includes(query)) return false;
      }
      if (reasonFilter && !(row.reason_codes || []).includes(reasonFilter)) return false;
      if (warningFilter && !(row.warning_codes || []).includes(warningFilter)) return false;
      if (caseFilter === 'package' && row.reason_bucket !== 'package') return false;
      if (caseFilter === 'collision' && row.reason_bucket !== 'collision') return false;
      if (caseFilter === 'artifact' && row.reason_bucket !== 'artifact') return false;
      if (caseFilter === 'subtitle' && row.reason_bucket !== 'subtitle') return false;
      return true;
    });
    rows.sort((a, b) => {
      const av = String(a[state.sort.key] || '').toLowerCase();
      const bv = String(b[state.sort.key] || '').toLowerCase();
      return state.sort.dir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av);
    });
    state.rows = activeRows();
    state.filteredRows = rows;
  }

  function renderFilters() {
    const rows = activeRows();
    const reasonCodes = [...new Set(rows.flatMap(row => row.reason_codes || []))].sort();
    const warningCodes = [...new Set(rows.flatMap(row => row.warning_codes || []))].sort();
    el.reasonFilter.innerHTML = `<option value="">reason code</option>${reasonCodes.map(code => `<option value="${escapeHtml(code)}">${escapeHtml(code)}</option>`).join('')}`;
    el.warningFilter.innerHTML = `<option value="">warning code</option>${warningCodes.map(code => `<option value="${escapeHtml(code)}">${escapeHtml(code)}</option>`).join('')}`;
  }

  function renderRows() {
    applyFilters();
    renderSelectionButtons();
    if (!state.filteredRows.length) {
      el.rowsBody.innerHTML = '<tr><td colspan="5">No rows for the active filters.</td></tr>';
      return;
    }
    el.rowsBody.innerHTML = state.filteredRows.map(row => `
      <tr class="${state.activeRowId === row.result_id ? 'active' : ''}" data-row-id="${escapeHtml(row.result_id)}">
        <td><input type="checkbox" data-row-check="${escapeHtml(row.result_id)}" ${state.selected.has(row.result_id) ? 'checked' : ''}></td>
        <td>${escapeHtml(row.current_value)}</td>
        <td>${escapeHtml(row.projected_path)}</td>
        <td>${escapeHtml(row.confidence)}</td>
        <td>${escapeHtml(row.reason_bucket)}</td>
      </tr>
    `).join('');
    el.rowsBody.querySelectorAll('tr[data-row-id]').forEach(rowEl => {
      rowEl.addEventListener('click', event => {
        if (event.target instanceof HTMLInputElement) return;
        state.activeRowId = rowEl.dataset.rowId || '';
        renderSidePanel();
      });
    });
    el.rowsBody.querySelectorAll('input[data-row-check]').forEach(input => {
      input.addEventListener('change', () => {
        const id = input.dataset.rowCheck || '';
        if (input.checked) state.selected.add(id);
        else state.selected.delete(id);
        state.activeRowId = id;
        renderSidePanel();
      });
    });
  }

  function rowById(rowId) {
    return state.rows.find(item => item.result_id === rowId) || state.filteredRows.find(item => item.result_id === rowId) || null;
  }

  function buildReviewCauses(row, changes) {
    const seen = new Set();
    const causes = [];
    [
      ...(row.warning_messages || []),
      ...(row.reason_messages || []),
      ...changes.map(change => change.reason).filter(Boolean),
    ].forEach(message => {
      const key = String(message || '').trim();
      if (!key || seen.has(key)) return;
      seen.add(key);
      causes.push(key);
    });
    return causes;
  }

  function renderDetailPane() {
    const row = rowById(state.activeRowId) || state.filteredRows[0] || null;
    if (!row) {
      el.detailPane.textContent = 'Run normalize to inspect rows.';
      return;
    }
    state.activeRowId = row.result_id;
    const changes = row.linked_changes || [];
    const reviewCauses = buildReviewCauses(row, changes);
    el.detailPane.innerHTML = `
      <div><strong>${escapeHtml(row.current_value)}</strong></div>
      <div>Confidence: <span class="chip">${escapeHtml(row.confidence)}</span></div>
      <div>Actionable: ${row.actionable ? 'yes' : 'no'}</div>
      <div>Why this is ${escapeHtml(row.confidence)}:</div>
      <div>${reviewCauses.length ? reviewCauses.map(message => `- ${escapeHtml(message)}`).join('\n') : 'No extra review cause recorded.'}</div>
      <div>Reason codes: ${(row.reason_codes || []).map(code => `<span class="chip">${escapeHtml(code)}</span>`).join('') || 'none'}</div>
      <div>Warning codes: ${(row.warning_codes || []).map(code => `<span class="chip">${escapeHtml(code)}</span>`).join('') || 'none'}</div>
      <div>Warning messages:</div>
      <div>${escapeHtml((row.warning_messages || []).join('\n') || 'none')}</div>
      <div>Title source: ${escapeHtml(row.title_source)}</div>
      <div>Year source: ${escapeHtml(row.year_source)}</div>
      <div>Parse source: ${escapeHtml(row.parse_source_path)}</div>
      <div>Parse evidence:</div>
      <div>${escapeHtml((row.reason_messages || []).join('\n') || 'none')}</div>
      <div>Compact token traces:</div>
      <div>${escapeHtml((row.compact_token_traces || []).join('\n') || 'none')}</div>
    `;
  }

  function selectedRows() {
    return state.filteredRows.filter(row => state.selected.has(row.result_id));
  }

  function flattenPreviewTree(node, lines, depth) {
    Object.keys(node).filter(key => !key.startsWith('_')).sort((a, b) => a.localeCompare(b)).forEach(key => {
      const entry = node[key];
      lines.push({ label: `${key}/`, depth, mutated: Boolean(entry._mutated), selected: Boolean(entry._selected), kind: 'dir' });
      flattenPreviewTree(entry, lines, depth + 1);
    });
    (node._files || []).sort((a, b) => a.name.localeCompare(b.name)).forEach(file => {
      lines.push({ label: file.name, depth, mutated: Boolean(file.mutated), selected: Boolean(file.selected), kind: 'file' });
    });
  }

  function buildPreviewTree(rows) {
    if (!rows.length) return '';
    const tree = {};
    rows.forEach(row => {
      const path = String(row.projected_path || row.current_value || '');
      const parts = path.split('/').filter(Boolean);
      const mutated = row.projected_path !== row.current_value;
      const selected = state.selected.has(row.result_id);
      let node = tree;
      parts.forEach((part, index) => {
        const isFile = index === parts.length - 1;
        if (isFile) {
          if (!node._files) node._files = [];
          node._files.push({ name: part, mutated, selected });
          return;
        }
        node[part] = node[part] || {};
        if (mutated) node[part]._mutated = true;
        if (selected) node[part]._selected = true;
        node = node[part];
      });
    });
    const lines = [];
    flattenPreviewTree(tree, lines, 0);
    return `
      <div class="lab-tree">
        ${lines.map(line => `
          <div class="lab-tree-line lab-indent-${Math.min(line.depth, 5)} ${line.mutated ? 'is-mutated' : ''} ${line.selected ? 'is-selected' : ''}">
            ${escapeHtml(line.label)}
          </div>
        `).join('')}
      </div>
    `;
  }

  function renderSelectedPreview() {
    const rows = selectedRows();
    if (!state.payload) {
      el.previewPane.textContent = 'Run normalize to inspect projected output.';
      return;
    }
    if (!rows.length) {
      el.previewPane.innerHTML = `
        <div class="lab-preview-empty">
          <strong>No rows selected.</strong>
          <div>Select rows in the table to stage a preview of the output that would change.</div>
        </div>
      `;
      return;
    }
    el.previewPane.innerHTML = `
      <div class="lab-preview-summary">
        <strong>${rows.length}</strong> selected row${rows.length === 1 ? '' : 's'} in preview.
      </div>
      ${buildPreviewTree(rows)}
    `;
  }

  function renderLibraryPreview() {
    if (!state.payload) {
      el.previewPane.textContent = 'Run normalize to inspect projected output.';
      return;
    }
    const rows = state.filteredRows;
    if (!rows.length) {
      el.previewPane.textContent = 'No rows match the current filters.';
      return;
    }
    const mutatedCount = rows.filter(row => row.projected_path !== row.current_value).length;
    el.previewPane.innerHTML = `
      <div class="lab-preview-summary">
        <strong>${rows.length}</strong> row${rows.length === 1 ? '' : 's'} in the current filtered library view.
        ${mutatedCount ? `<span class="chip">${mutatedCount} mutated</span>` : '<span class="chip">0 mutated</span>'}
      </div>
      ${buildPreviewTree(rows)}
    `;
  }

  function renderPreviewPane() {
    if (state.previewMode === 'library') renderLibraryPreview();
    else renderSelectedPreview();
  }

  function renderSidePanel() {
    renderPaneTabs();
    renderDetailPane();
    renderPreviewPane();
  }

  async function runNormalize() {
    state.runInFlight = true;
    renderRunButton();
    try {
      const response = await fetch('/api/movies/normalize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source: el.sourcePath.value }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || 'normalize failed');
      state.payload = payload;
      state.selected = new Set();
      state.activeRowId = '';
      state.activePane = 'detail';
      state.previewMode = 'selected';
      renderFilters();
      renderRows();
      renderSidePanel();
    } finally {
      state.runInFlight = false;
      renderRunButton();
    }
  }

  async function exportSelected() {
    const rows = state.rows.filter(row => state.selected.has(row.result_id));
    if (!rows.length) return;
    const response = await fetch('/api/movies/parser-tester-ui/export', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source: el.sourcePath.value, rows }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'export failed');
    el.previewPane.textContent = `Exported ${payload.exported} rows to ${payload.path}`;
  }

  document.querySelectorAll('.sort').forEach(button => {
    button.addEventListener('click', () => {
      const key = button.dataset.sort;
      if (!key) return;
      state.sort = { key, dir: state.sort.key === key && state.sort.dir === 'asc' ? 'desc' : 'asc' };
      renderRows();
      renderSidePanel();
    });
  });
  [el.searchInput, el.bucketFilter, el.caseFilter, el.reasonFilter, el.warningFilter].forEach(control => {
    control.addEventListener('change', () => { renderRows(); renderSidePanel(); });
    if (control === el.searchInput) control.addEventListener('input', () => { renderRows(); renderSidePanel(); });
  });
  el.selectAllButton.addEventListener('click', () => {
    state.filteredRows.forEach(row => state.selected.add(row.result_id));
    if (state.filteredRows[0]) state.activeRowId = state.filteredRows[0].result_id;
    state.activePane = 'preview';
    state.previewMode = 'selected';
    renderRows();
    renderSidePanel();
  });
  el.deselectAllButton.addEventListener('click', () => {
    state.filteredRows.forEach(row => state.selected.delete(row.result_id));
    renderRows();
    renderSidePanel();
  });
  el.detailTab.addEventListener('click', () => {
    state.activePane = 'detail';
    renderSidePanel();
  });
  el.previewTab.addEventListener('click', () => {
    state.activePane = 'preview';
    renderSidePanel();
  });
  el.selectedPreviewButton.addEventListener('click', () => {
    state.previewMode = 'selected';
    renderSidePanel();
  });
  el.libraryPreviewButton.addEventListener('click', () => {
    state.previewMode = 'library';
    renderSidePanel();
  });
  renderRunButton();
  renderSelectionButtons();
  renderPaneTabs();
  renderSidePanel();
  el.runButton.addEventListener('click', () => { runNormalize().catch(error => { el.detailPane.textContent = error.message; }); });
  el.exportButton.addEventListener('click', () => { exportSelected().catch(error => { el.previewPane.textContent = error.message; }); });
})();
