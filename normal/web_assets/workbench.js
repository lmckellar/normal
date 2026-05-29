(function () {
  const state = {
    page: 'dashboard',
    source: window.DEFAULT_SOURCE || '',
    normalizeFilter: 'all_results',
    junkFilter: 'all',
    qualityFilter: 'all',
    fixDefaultsTab: 'audio',
    fixDefaultsFilter: 'all',
    secondaryMode: 'selected',
    auditExpanded: false,
    fileTreeExpanded: false,
    movieNamingStyle: 'concise',
    selectedNormalizeResultIds: new Set(),
    selectedReplacementPaths: new Set(),
    selectedJunkPaths: new Set(),
    selectedDashboardKey: '',
    selectedDashboardType: '',
    selectedCanonicalId: '',
    subtitleHistory: null,
    movieAudioFixBusy: false,
    movieSubtitleFixBusy: false,
    activeRunController: null,
    statusTimer: null,
    scanStart: null,
    activityTimer: null,
    scanWarning: '',
    auditEvents: [],
    results: {
      profile: null,
      normalize: null,
      junk: null,
      canonical: null,
      replacementQueue: null,
      normalizeApply: null,
    },
  };

  const PAGE_CONFIG = {
    dashboard: {
      label: 'Dashboard',
      endpoint: '/api/movies/profile',
      primaryTitle: 'Library Inspection & Analysis',
      primaryNote: 'Cards and thresholds define the left-hand reading surface.',
      secondaryTitle: 'Library Curatorial Reading',
      mutationFlow: false,
    },
    normalize: {
      label: 'Normalize',
      endpoint: '/api/movies/normalize',
      primaryTitle: 'Normalize Inspection & Proposal',
      primaryNote: 'Inspect, sort, and select proposals on the working page.',
      secondaryTitle: 'Normalize Output Preview',
      mutationFlow: true,
    },
    quality: {
      label: 'Delete Weak Encodes',
      endpoint: '/api/movies/profile',
      primaryTitle: 'Weak Encode Inspection & Proposal',
      primaryNote: 'Selection lives here. Deletion consequence lives to the right.',
      secondaryTitle: 'Weak Encode Output Preview',
      mutationFlow: true,
    },
    fix_defaults: {
      label: 'Repair Defaults',
      endpoint: '/api/movies/profile',
      primaryTitle: 'Defaults Inspection & Proposal',
      primaryNote: 'Audio and subtitle repair selection belong on the primary page.',
      secondaryTitle: 'Defaults Output Preview',
      mutationFlow: true,
    },
    junk: {
      label: 'Delete Junk',
      endpoint: '/api/movies/junk',
      primaryTitle: 'Junk Inspection & Proposal',
      primaryNote: 'Preview the deletion consequence before committing.',
      secondaryTitle: 'Junk Output Preview',
      mutationFlow: true,
    },
    canonical_lists: {
      label: 'Canonical Lists',
      endpoint: '/api/movies/canonical-lists',
      primaryTitle: 'Canonical Inspection & Mapping',
      primaryNote: 'Left page selects the list. Right page expands the map.',
      secondaryTitle: 'Canonical Curatorial Reading',
      mutationFlow: false,
    },
  };

  const el = {
    sourcePath: document.getElementById('sourcePath'),
    pageNav: document.getElementById('pageNav'),
    runButton: document.getElementById('runButton'),
    statusDot: document.getElementById('statusDot'),
    statusText: document.getElementById('statusText'),
    statusTimer: document.getElementById('statusTimer'),
    activityDetail: document.getElementById('activityDetail'),
    contextRibbon: document.getElementById('contextRibbon'),
    sliverContent: document.getElementById('sliverContent'),
    fileTreeToggle: document.getElementById('fileTreeToggle'),
    fileTreePanel: document.getElementById('fileTreePanel'),
    primaryTitle: document.getElementById('primaryTitle'),
    primaryNote: document.getElementById('primaryNote'),
    primaryContent: document.getElementById('primaryContent'),
    secondaryTitle: document.getElementById('secondaryTitle'),
    secondaryModes: document.getElementById('secondaryModes'),
    secondaryActionBar: document.getElementById('secondaryActionBar'),
    secondaryContent: document.getElementById('secondaryContent'),
    auditToggle: document.getElementById('auditToggle'),
    auditRailContent: document.getElementById('auditRailContent'),
  };

  function pagePayload(page = state.page) {
    if (page === 'normalize') return state.results.normalize;
    if (page === 'junk') return state.results.junk;
    if (page === 'canonical_lists') return state.results.canonical;
    return state.results.profile;
  }

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, char => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;',
    }[char]));
  }

  function stripHtml(value) {
    return String(value || '').replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim();
  }

  function setStatus(text, mode) {
    el.statusText.textContent = text;
    el.statusDot.className = 'wb-status-dot' + (mode && mode !== 'idle' ? ` ${mode}` : '');
  }

  function updateRunButton() {
    const running = !!state.activeRunController;
    el.runButton.textContent = running ? 'Stop' : 'Run';
    el.runButton.className = `wb-btn ${running ? 'wb-btn-danger' : 'wb-btn-primary'}`;
  }

  function startStatusTimer() {
    clearInterval(state.statusTimer);
    state.scanStart = Date.now();
    state.statusTimer = setInterval(() => {
      if (!state.scanStart) return;
      const elapsed = Math.floor((Date.now() - state.scanStart) / 1000);
      const mins = Math.floor(elapsed / 60);
      const secs = elapsed % 60;
      el.statusTimer.textContent = mins ? `${mins}m ${secs}s` : `${secs}s`;
    }, 1000);
  }

  function stopStatusTimer() {
    clearInterval(state.statusTimer);
    state.statusTimer = null;
    state.scanStart = null;
    el.statusTimer.textContent = '';
  }

  async function fetchJson(url, options = {}) {
    const response = await fetch(url, options);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Request failed.');
    return payload;
  }

  async function fetchActivity() {
    const source = el.sourcePath.value.trim();
    if (!source) {
      el.activityDetail.textContent = 'Choose a library path to observe scan, probe, and remux activity.';
      return null;
    }
    try {
      const payload = await fetchJson('/api/activity?source=' + encodeURIComponent(source));
      const app = payload.app || [];
      const probes = payload.probes || [];
      const external = payload.external || [];
      if (probes.length) {
        const probe = probes[0];
        el.activityDetail.textContent = `${probe.label}${probe.current_path ? ` on ${(probe.current_path || '').split('/').pop()}` : ''}`;
        return payload;
      }
      if (app.length) {
        const job = app[0];
        const current = job.current_path ? ` on ${(job.current_path || '').split('/').pop()}` : '';
        el.activityDetail.textContent = `${job.label}${current}`;
        return payload;
      }
      if (external.length) {
        const process = external[0];
        el.activityDetail.textContent = `External ${process.command} detected: ${process.summary}`;
        return payload;
      }
      el.activityDetail.textContent = payload.os_note || 'No normal job or media probe detected for the selected source.';
      return payload;
    } catch (error) {
      el.activityDetail.textContent = error.message;
      return null;
    }
  }

  function startActivityPolling() {
    clearInterval(state.activityTimer);
    fetchActivity();
    state.activityTimer = setInterval(fetchActivity, 5000);
  }

  function currentSource() {
    return el.sourcePath.value.trim();
  }

  function resetSelections() {
    state.selectedNormalizeResultIds.clear();
    state.selectedReplacementPaths.clear();
    state.selectedJunkPaths.clear();
  }

  function setPage(page) {
    state.page = page;
    state.auditExpanded = false;
    resetSelections();
    renderPageNav();
    renderWorkbench();
  }

  function renderPageNav() {
    el.pageNav.innerHTML = Object.entries(PAGE_CONFIG).map(([id, page]) => (
      `<button class="${id === state.page ? 'active' : ''}" data-page="${id}">${escapeHtml(page.label)}</button>`
    )).join('');
    el.pageNav.querySelectorAll('[data-page]').forEach(button => {
      button.addEventListener('click', () => setPage(button.dataset.page));
    });
  }

  function currentMutationSelectionCount() {
    if (state.page === 'normalize') return state.selectedNormalizeResultIds.size;
    if (state.page === 'junk') return state.selectedJunkPaths.size;
    return state.selectedReplacementPaths.size;
  }

  function humanProfileLabel(label) {
    if (label === 'standard_definition') return 'Standard Definition';
    if (label === 'library_grade') return 'Library Grade';
    if (label === 'collector_grade') return 'Collector Grade';
    if (label === 'reference') return 'Reference';
    if (label === 'meets_minimum') return 'Meets Minimum';
    if (label === 'needs_review') return 'Needs Review';
    if (label === 'replacement_candidate') return 'Replacement Candidate';
    return String(label || '').split('_').map(word => word ? word[0].toUpperCase() + word.slice(1) : '').join(' ');
  }

  function formatBytes(bytes) {
    if (!bytes || !Number.isFinite(bytes)) return '—';
    if (bytes >= 1e12) return `${(bytes / 1e12).toFixed(1)} TB`;
    if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`;
    if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(1)} MB`;
    return `${Math.round(bytes / 1e3)} KB`;
  }

  function addAuditEvent(flow, title, detail) {
    state.auditEvents.unshift({
      at: new Date().toISOString(),
      flow,
      title,
      detail,
    });
    state.auditEvents = state.auditEvents.slice(0, 40);
  }

  function counter(items) {
    return items.reduce((acc, item) => {
      acc[item] = (acc[item] || 0) + 1;
      return acc;
    }, {});
  }

  function isStrictWeakMovie(item) {
    return !!item?.profile?.weak_candidate;
  }

  function movieStandardsWorkflowItems(payload) {
    return (payload?.movies || []).filter(item => {
      const label = item?.profile?.label || '';
      return item?.profile?.weak_candidate || label === 'needs_review';
    });
  }

  function movieAudioPackagingIssueCode(item) {
    const diagnostics = item?.profile?.diagnostics || [];
    if (diagnostics.some(diag => diag?.code === 'default_non_english_audio_with_weak_english')) return 'default_non_english_audio_with_weak_english';
    if (diagnostics.some(diag => diag?.code === 'default_non_english_audio')) return 'default_non_english_audio';
    return '';
  }

  function movieSubtitleSetupResult(item) {
    return (item?.profile?.domain_results || []).find(result => result?.domain === 'subtitle_setup') || null;
  }

  function movieSubtitleReadinessIssueCode(item) {
    return movieSubtitleSetupResult(item)?.code || '';
  }

  function movieDefaultSubtitleStream(item) {
    const streams = item?.facts?.subtitle_streams || [];
    return streams.find(stream => stream?.is_default) || streams[0] || null;
  }

  function subtitleStreamLanguage(stream) {
    const value = String(stream?.language || '').toLowerCase();
    if (['eng', 'en', 'english'].includes(value)) return 'english';
    if (['ita', 'it', 'italian'].includes(value)) return 'italian';
    return value;
  }

  function isEnglishSubtitleStream(stream) {
    return subtitleStreamLanguage(stream) === 'english';
  }

  function chooseBestEnglishSubtitleStream(item, options = {}) {
    const streams = item?.facts?.subtitle_streams || [];
    const forcedOnly = !!options.forcedOnly;
    const matching = streams.filter(stream => isEnglishSubtitleStream(stream) && (stream?.is_forced || !forcedOnly));
    if (!matching.length) return null;
    const currentDefault = movieDefaultSubtitleStream(item);
    if (currentDefault && matching.includes(currentDefault)) return currentDefault;
    return matching[0];
  }

  function movieDefaultAudioStream(item) {
    const streams = item?.facts?.audio_streams || [];
    return streams.find(stream => stream?.is_default) || streams[0] || null;
  }

  function audioStreamLanguage(stream) {
    const value = String(stream?.language || '').toLowerCase();
    if (['eng', 'en', 'english'].includes(value)) return 'english';
    if (['ita', 'it', 'italian'].includes(value)) return 'italian';
    return value;
  }

  function itemDefaultAudioLanguage(item) {
    return audioStreamLanguage(movieDefaultAudioStream(item)) || '';
  }

  function movieSubtitleReadinessRepairTarget(item) {
    const forced = chooseBestEnglishSubtitleStream(item, { forcedOnly: true });
    if (forced) return forced;
    if (!['', 'english'].includes(itemDefaultAudioLanguage(item))) {
      return chooseBestEnglishSubtitleStream(item);
    }
    return null;
  }

  function movieSubtitleReadinessIsRepairable(item) {
    const issueCode = movieSubtitleReadinessIssueCode(item);
    if (!issueCode) return false;
    if (!String(item?.path || '').toLowerCase().endsWith('.mkv')) return false;
    if (!Array.isArray(item?.facts?.subtitle_streams) || !item.facts.subtitle_streams.length) return false;
    if (issueCode === 'missing_default_english_subtitle') return false;
    if (issueCode === 'multiple_default_subtitles') return !!movieSubtitleReadinessRepairTarget(item) || itemDefaultAudioLanguage(item) === 'english';
    if (['english_forced_not_default', 'wrong_default_forced_subtitle', 'wrong_default_subtitle_language'].includes(issueCode)) {
      return !!movieSubtitleReadinessRepairTarget(item);
    }
    if (issueCode === 'unnecessary_default_subtitle') return true;
    return false;
  }

  function humanSubtitleReadinessIssueLabel(code) {
    const labels = {
      english_forced_not_default: 'forced English exists but is not default',
      wrong_default_forced_subtitle: 'wrong subtitle is default instead of forced English',
      missing_default_english_subtitle: 'non-English audio but no default English subtitle',
      wrong_default_subtitle_language: 'non-English audio but default subtitle is not English',
      unnecessary_default_subtitle: 'English audio should default to no subtitles',
      multiple_default_subtitles: 'multiple subtitle streams are default',
    };
    return labels[code] || String(code || '').replaceAll('_', ' ');
  }

  function describeSubtitleStream(stream) {
    if (!stream) return '—';
    const language = subtitleStreamLanguage(stream);
    return [language ? language[0].toUpperCase() + language.slice(1) : 'Unknown', stream?.is_forced ? 'forced' : null, stream?.title || null]
      .filter(Boolean)
      .join(' · ');
  }

  function audioChannelLayout(channels) {
    if (channels === null || channels === undefined) return '';
    if (channels === 1) return 'Mono';
    if (channels === 2) return '2.0';
    if (channels === 6) return '5.1';
    if (channels === 8) return '7.1';
    return `${channels}ch`;
  }

  function audioImmersiveExtension(profile, title = '') {
    const combined = `${String(profile || '').toLowerCase()} ${String(title || '').toLowerCase()}`;
    if (combined.includes('atmos') || combined.includes('dolby atmos')) return 'Atmos';
    if (combined.includes('dts:x') || combined.includes('dts-x') || combined.includes('dtsx')) return 'DTS:X';
    return '';
  }

  function audioCodecDisplayName(codec, profile = '') {
    const codecText = String(codec || '').toLowerCase();
    const profileText = String(profile || '').toLowerCase();
    if (codecText === 'aac') return 'AAC';
    if (codecText === 'ac3') return 'Dolby Digital';
    if (codecText === 'eac3') return 'Dolby Digital Plus';
    if (codecText === 'truehd') return 'Dolby TrueHD';
    if (codecText === 'dts') {
      if (profileText.includes('master audio') || /\bma\b/.test(profileText)) return 'DTS-HD MA';
      if (profileText.includes('high resolution') || /\bhra\b/.test(profileText)) return 'DTS-HD HRA';
      return 'DTS';
    }
    if (codecText === 'flac') return 'FLAC';
    if (codecText.startsWith('pcm')) return 'PCM';
    return codecText ? codecText.toUpperCase() : '';
  }

  function describeAudioFormat(stream) {
    if (!stream) return '';
    const parts = [audioCodecDisplayName(stream.codec, stream.profile), audioChannelLayout(stream.channels)].filter(Boolean);
    const immersive = audioImmersiveExtension(stream.profile, stream.title);
    return immersive ? `${parts.join(' ')} ${immersive}`.trim() : parts.join(' ');
  }

  function describeAudioStream(stream) {
    if (!stream) return '—';
    const language = audioStreamLanguage(stream);
    return [
      language ? language[0].toUpperCase() + language.slice(1) : 'Unknown',
      describeAudioFormat(stream),
      stream.bitrate_kbps ? `${Math.round(stream.bitrate_kbps).toLocaleString()} kbps` : null,
    ].filter(Boolean).join(' · ');
  }

  function filteredQualityItems(payload) {
    const items = movieStandardsWorkflowItems(payload);
    if (state.qualityFilter === 'strict_weak') return items.filter(isStrictWeakMovie);
    if (state.qualityFilter === 'needs_review') return items.filter(item => item?.profile?.label === 'needs_review');
    return items;
  }

  function filteredAudioItems(payload) {
    const items = (payload?.movies || []).filter(item => !!movieAudioPackagingIssueCode(item));
    if (state.fixDefaultsFilter === 'weak_english') return items.filter(item => movieAudioPackagingIssueCode(item) === 'default_non_english_audio_with_weak_english');
    if (state.fixDefaultsFilter === 'wrong_default') return items.filter(item => movieAudioPackagingIssueCode(item) === 'default_non_english_audio');
    return items;
  }

  function filteredSubtitleItems(payload) {
    const items = (payload?.movies || []).filter(item => movieSubtitleReadinessIsRepairable(item));
    if (state.fixDefaultsFilter === 'forced_english') return items.filter(item => ['english_forced_not_default', 'wrong_default_forced_subtitle'].includes(movieSubtitleReadinessIssueCode(item)));
    if (state.fixDefaultsFilter === 'non_english_audio') return items.filter(item => movieSubtitleReadinessIssueCode(item) === 'wrong_default_subtitle_language');
    if (state.fixDefaultsFilter === 'clear_default') return items.filter(item => ['unnecessary_default_subtitle', 'multiple_default_subtitles'].includes(movieSubtitleReadinessIssueCode(item)));
    return items;
  }

  function filteredMovieJunk(payload) {
    const items = payload?.junk || [];
    if (state.junkFilter === 'all') return items;
    return items.filter(item => item.confidence === state.junkFilter);
  }

  function currentNormalizePayload() {
    return state.results.normalize;
  }

  function selectedNormalizeResults(payload) {
    return (payload?.movie_results || []).filter(result => state.selectedNormalizeResultIds.has(result.result_id));
  }

  function normalizeRows(payload) {
    if (!payload) return [];
    if (state.normalizeFilter === 'all_results') return payload.movie_results || [];
    if (state.normalizeFilter === 'warnings') return [];
    return (payload.movie_results || []).filter(result => result.confidence === state.normalizeFilter);
  }

  function resultMapByPage() {
    return {
      dashboard: pagePayload('dashboard'),
      normalize: currentNormalizePayload(),
      quality: pagePayload('quality'),
      fix_defaults: pagePayload('fix_defaults'),
      junk: pagePayload('junk'),
      canonical_lists: pagePayload('canonical_lists'),
    };
  }

  function renderRibbon() {
    const page = state.page;
    let controls = '';
    if (page === 'normalize') {
      controls = `
        <span class="wb-kicker">Normalize</span>
        <button class="${state.normalizeFilter === 'all_results' ? 'wb-btn-primary' : ''}" data-nf="all_results">All Results</button>
        <button class="${state.normalizeFilter === 'safe' ? 'wb-btn-primary' : ''}" data-nf="safe">Safe</button>
        <button class="${state.normalizeFilter === 'review' ? 'wb-btn-primary' : ''}" data-nf="review">Review</button>
        <button class="${state.normalizeFilter === 'warnings' ? 'wb-btn-primary' : ''}" data-nf="warnings">Warnings</button>
        <button id="selectAllVisibleResults">Select Visible</button>
        <button id="clearNormalizeSelection">Clear Selection</button>
      `;
    } else if (page === 'quality') {
      controls = `
        <span class="wb-kicker">Weak Encode</span>
        <button class="${state.qualityFilter === 'all' ? 'wb-btn-primary' : ''}" data-qf="all">All</button>
        <button class="${state.qualityFilter === 'strict_weak' ? 'wb-btn-primary' : ''}" data-qf="strict_weak">Strict Weak</button>
        <button class="${state.qualityFilter === 'needs_review' ? 'wb-btn-primary' : ''}" data-qf="needs_review">Needs Review</button>
        <button id="selectAllQuality">Select Visible</button>
        <button id="clearReplacementSelection">Clear Selection</button>
      `;
    } else if (page === 'fix_defaults') {
      const audio = state.fixDefaultsTab === 'audio';
      controls = `
        <span class="wb-kicker">Repair Defaults</span>
        <button class="${audio ? 'wb-btn-primary' : ''}" data-fix-tab="audio">Audio Packaging</button>
        <button class="${!audio ? 'wb-btn-primary' : ''}" data-fix-tab="subtitle">Subtitle Readiness</button>
        ${audio ? `
          <button class="${state.fixDefaultsFilter === 'all' ? 'wb-btn-primary' : ''}" data-fix-filter="all">All</button>
          <button class="${state.fixDefaultsFilter === 'wrong_default' ? 'wb-btn-primary' : ''}" data-fix-filter="wrong_default">Wrong Default</button>
          <button class="${state.fixDefaultsFilter === 'weak_english' ? 'wb-btn-primary' : ''}" data-fix-filter="weak_english">Weak English</button>
        ` : `
          <button class="${state.fixDefaultsFilter === 'all' ? 'wb-btn-primary' : ''}" data-fix-filter="all">All</button>
          <button class="${state.fixDefaultsFilter === 'forced_english' ? 'wb-btn-primary' : ''}" data-fix-filter="forced_english">Forced English</button>
          <button class="${state.fixDefaultsFilter === 'non_english_audio' ? 'wb-btn-primary' : ''}" data-fix-filter="non_english_audio">Non-English Audio</button>
          <button class="${state.fixDefaultsFilter === 'clear_default' ? 'wb-btn-primary' : ''}" data-fix-filter="clear_default">Clear Default</button>
        `}
        <button id="selectAllDefaults">Select Visible</button>
        <button id="clearDefaultsSelection">Clear Selection</button>
      `;
    } else if (page === 'junk') {
      controls = `
        <span class="wb-kicker">Junk</span>
        <button class="${state.junkFilter === 'all' ? 'wb-btn-primary' : ''}" data-jf="all">All</button>
        <button class="${state.junkFilter === 'high' ? 'wb-btn-primary' : ''}" data-jf="high">High</button>
        <button class="${state.junkFilter === 'review' ? 'wb-btn-primary' : ''}" data-jf="review">Review</button>
        <button id="selectAllJunk">Select Visible</button>
        <button id="clearJunkSelection">Clear Selection</button>
      `;
    } else if (page === 'dashboard') {
      controls = `<span class="wb-kicker">Dashboard</span><span class="wb-subtle">The left page narrows a profile or action card. The right page expands its meaning.</span>`;
    } else if (page === 'canonical_lists') {
      controls = `<span class="wb-kicker">Canonical Lists</span><span class="wb-subtle">Select a list on the left. Read the full coverage story on the right.</span>`;
    }
    el.contextRibbon.innerHTML = controls;

    el.contextRibbon.querySelectorAll('[data-nf]').forEach(button => {
      button.addEventListener('click', () => { state.normalizeFilter = button.dataset.nf; renderWorkbench(); });
    });
    el.contextRibbon.querySelectorAll('[data-qf]').forEach(button => {
      button.addEventListener('click', () => { state.qualityFilter = button.dataset.qf; renderWorkbench(); });
    });
    el.contextRibbon.querySelectorAll('[data-jf]').forEach(button => {
      button.addEventListener('click', () => { state.junkFilter = button.dataset.jf; renderWorkbench(); });
    });
    el.contextRibbon.querySelectorAll('[data-fix-tab]').forEach(button => {
      button.addEventListener('click', () => {
        state.fixDefaultsTab = button.dataset.fixTab;
        state.fixDefaultsFilter = 'all';
        state.selectedReplacementPaths.clear();
        renderWorkbench();
      });
    });
    el.contextRibbon.querySelectorAll('[data-fix-filter]').forEach(button => {
      button.addEventListener('click', () => { state.fixDefaultsFilter = button.dataset.fixFilter; renderWorkbench(); });
    });
    document.getElementById('selectAllVisibleResults')?.addEventListener('click', () => {
      normalizeRows(currentNormalizePayload()).forEach(result => {
        if (result.actionable) state.selectedNormalizeResultIds.add(result.result_id);
      });
      renderWorkbench();
    });
    document.getElementById('clearNormalizeSelection')?.addEventListener('click', () => {
      state.selectedNormalizeResultIds.clear();
      renderWorkbench();
    });
    document.getElementById('selectAllQuality')?.addEventListener('click', () => {
      filteredQualityItems(pagePayload('quality')).forEach(item => {
        if (item.path) state.selectedReplacementPaths.add(item.path);
      });
      renderWorkbench();
    });
    document.getElementById('clearReplacementSelection')?.addEventListener('click', () => {
      state.selectedReplacementPaths.clear();
      renderWorkbench();
    });
    document.getElementById('selectAllDefaults')?.addEventListener('click', () => {
      const items = state.fixDefaultsTab === 'audio' ? filteredAudioItems(pagePayload('fix_defaults')) : filteredSubtitleItems(pagePayload('fix_defaults'));
      items.forEach(item => {
        if (item.path) state.selectedReplacementPaths.add(item.path);
      });
      renderWorkbench();
    });
    document.getElementById('clearDefaultsSelection')?.addEventListener('click', () => {
      state.selectedReplacementPaths.clear();
      renderWorkbench();
    });
    document.getElementById('selectAllJunk')?.addEventListener('click', () => {
      filteredMovieJunk(pagePayload('junk')).forEach(item => {
        if (item.path) state.selectedJunkPaths.add(item.path);
      });
      renderWorkbench();
    });
    document.getElementById('clearJunkSelection')?.addEventListener('click', () => {
      state.selectedJunkPaths.clear();
      renderWorkbench();
    });
  }

  function renderSliver() {
    const page = PAGE_CONFIG[state.page];
    const payload = pagePayload();
    const source = currentSource();
    const stats = [];
    if (state.page === 'dashboard' && payload?.histogram) {
      stats.push(['Movies', String(payload.histogram.movie_count || 0)]);
      stats.push(['Storage', formatBytes(payload.histogram.total_size_bytes)]);
      stats.push(['Replacement', String((payload.replacement_queue?.items || []).filter(item => item.status === 'deleted').length)]);
    } else if (state.page === 'normalize') {
      const normalize = currentNormalizePayload();
      stats.push(['Results', String((normalize?.movie_results || []).length)]);
      stats.push(['Selected', String(state.selectedNormalizeResultIds.size)]);
      stats.push(['Warnings', String((normalize?.warnings || []).length)]);
    } else if (state.page === 'quality') {
      const items = filteredQualityItems(payload);
      stats.push(['Candidates', String(items.length)]);
      stats.push(['Selected', String(state.selectedReplacementPaths.size)]);
      stats.push(['Queued', String((payload?.replacement_queue?.items || []).filter(item => item.status === 'pending').length)]);
    } else if (state.page === 'fix_defaults') {
      const items = state.fixDefaultsTab === 'audio' ? filteredAudioItems(payload) : filteredSubtitleItems(payload);
      stats.push(['Visible', String(items.length)]);
      stats.push(['Selected', String(state.selectedReplacementPaths.size)]);
      stats.push(['Mode', state.fixDefaultsTab === 'audio' ? 'Audio' : 'Subtitle']);
    } else if (state.page === 'junk') {
      const items = filteredMovieJunk(payload);
      stats.push(['Candidates', String(items.length)]);
      stats.push(['Selected', String(state.selectedJunkPaths.size)]);
      stats.push(['Deleted', String(sessionJunkHistory().length)]);
    } else if (state.page === 'canonical_lists') {
      stats.push(['Lists', String((payload?.list_summaries || []).length)]);
      stats.push(['Badges', String((payload?.badges || []).filter(badge => badge.unlocked).length)]);
      stats.push(['Owned', String(payload?.library_summary?.owned_movies || 0)]);
    }
    el.sliverContent.innerHTML = `
      <div class="wb-note">
        <div class="wb-kicker">Origin</div>
        <div class="wb-mono">${escapeHtml(source || 'No source selected')}</div>
      </div>
      <div class="wb-note">
        <div class="wb-kicker">Current Flow</div>
        <div>${escapeHtml(page.label)}</div>
        <div class="wb-subtle">This sliver remains upstream of the main review spread.</div>
      </div>
      <div class="wb-list">
        ${stats.map(([label, value]) => `
          <div class="wb-list-item">
            <div class="wb-kicker">${escapeHtml(label)}</div>
            <div class="wb-count">${escapeHtml(value)}</div>
          </div>
        `).join('')}
      </div>
    `;

    const treeLines = buildFileTreeLines();
    el.fileTreeToggle.textContent = state.fileTreeExpanded ? 'Collapse File Tree' : 'Reveal File Tree';
    el.fileTreePanel.className = `wb-tree-panel ${state.fileTreeExpanded ? '' : 'wb-tree-panel-hidden'}`;
    el.fileTreePanel.innerHTML = treeLines.length
      ? treeLines.map(line => `<div class="wb-tree-line wb-indent-${Math.min(line.depth, 5)}">${escapeHtml(line.label)}</div>`).join('')
      : '<div class="wb-subtle">No current source structure is available yet.</div>';
  }

  function buildFileTreeLines() {
    const payload = pagePayload();
    const paths = [];
    if (state.page === 'normalize') {
      const normalize = currentNormalizePayload();
      (normalize?.movie_results || []).forEach(result => paths.push(result.proposed_value || result.current_value || ''));
    } else if (state.page === 'junk') {
      (payload?.junk || []).forEach(item => paths.push(item.relative_path || item.path || ''));
    } else if (payload?.movies) {
      const source = payload.source_root || currentSource();
      const prefix = source ? `${source.replace(/\/$/, '')}/` : '';
      payload.movies.forEach(item => {
        const path = String(item.path || '');
        paths.push(prefix && path.startsWith(prefix) ? path.slice(prefix.length) : path);
      });
    } else if (state.page === 'canonical_lists') {
      ((payload?.list_summaries || []).slice(0, 12)).forEach(item => paths.push(item.label || ''));
    }
    const tree = {};
    paths.filter(Boolean).forEach(path => {
      const parts = String(path).split('/').filter(Boolean);
      let node = tree;
      parts.forEach((part, index) => {
        if (index === parts.length - 1) {
          if (!node._files) node._files = [];
          node._files.push(part);
        } else {
          node[part] = node[part] || {};
          node = node[part];
        }
      });
    });
    const lines = [];
    flattenTree(tree, lines, 0);
    return lines.slice(0, 240);
  }

  function flattenTree(node, lines, depth) {
    Object.keys(node).filter(key => key !== '_files').sort((a, b) => a.localeCompare(b)).forEach(key => {
      lines.push({ label: `${key}/`, depth });
      flattenTree(node[key], lines, depth + 1);
    });
    (node._files || []).sort((a, b) => a.localeCompare(b)).forEach(file => {
      lines.push({ label: file, depth });
    });
  }

  function renderPrimarySurface() {
    const page = PAGE_CONFIG[state.page];
    el.primaryTitle.textContent = page.primaryTitle;
    el.primaryNote.textContent = page.primaryNote;
    if (state.page === 'dashboard') {
      renderDashboardPrimary();
      return;
    }
    if (state.page === 'normalize') {
      renderNormalizePrimary();
      return;
    }
    if (state.page === 'quality') {
      renderQualityPrimary();
      return;
    }
    if (state.page === 'fix_defaults') {
      renderDefaultsPrimary();
      return;
    }
    if (state.page === 'junk') {
      renderJunkPrimary();
      return;
    }
    if (state.page === 'canonical_lists') {
      renderCanonicalPrimary();
    }
  }

  function renderDashboardPrimary() {
    const payload = pagePayload('dashboard');
    if (!payload) {
      el.primaryContent.innerHTML = '<div class="wb-empty">Run the dashboard scan to build the workbench spread.</div>';
      return;
    }
    const histogram = payload.histogram || {};
    const profileCounts = histogram.quality_profile_counts || {};
    const queueDeleted = (payload.replacement_queue?.items || []).filter(item => item.status === 'deleted').length;
    const actionCards = [];
    if (queueDeleted) {
      actionCards.push({
        key: 'deleted_awaiting_replacement',
        type: 'action',
        label: 'Deleted Awaiting Replacement',
        count: queueDeleted,
        note: 'Audit pressure waiting for replacement completion.',
      });
    }
    (payload.quality_profile_definitions || []).forEach(definition => {
      actionCards.push({
        key: definition.label,
        type: definition.profile_type || 'quality',
        label: definition.display_name || humanProfileLabel(definition.label),
        count: profileCounts[definition.label] || 0,
        note: definition.summary || definition.description || '',
      });
    });
    if (payload.replacement_candidate_definition) {
      actionCards.push({
        key: 'replacement_candidate',
        type: 'action',
        label: payload.replacement_candidate_definition.display_name || 'Replacement Candidate',
        count: profileCounts.replacement_candidate || 0,
        note: payload.replacement_candidate_definition.summary || '',
      });
    }
    el.primaryContent.innerHTML = `
      <div class="wb-spread-stats">
        <div class="wb-card"><div class="wb-kicker">Movies</div><div class="wb-count">${escapeHtml(String(histogram.movie_count || 0))}</div></div>
        <div class="wb-card"><div class="wb-kicker">Total Size</div><div class="wb-count">${escapeHtml(formatBytes(histogram.total_size_bytes))}</div></div>
        <div class="wb-card"><div class="wb-kicker">Runtime</div><div class="wb-count">${escapeHtml(String(histogram.total_runtime_minutes || 0))}m</div></div>
      </div>
      <div class="wb-card-grid">
        ${actionCards.map(card => `
          <div class="wb-card">
            <div class="wb-kicker">${escapeHtml(card.type === 'action' ? 'Action Based' : 'Quality Profile')}</div>
            <h3>${escapeHtml(card.label)}</h3>
            <div class="wb-count">${escapeHtml(String(card.count))}</div>
            <div class="wb-subtle">${escapeHtml(card.note || 'No extra definition text.')}</div>
            <button data-dashboard-card="${escapeHtml(card.key)}" data-dashboard-type="${escapeHtml(card.type)}">Read</button>
          </div>
        `).join('')}
      </div>
    `;
    el.primaryContent.querySelectorAll('[data-dashboard-card]').forEach(button => {
      button.addEventListener('click', () => {
        state.selectedDashboardKey = button.dataset.dashboardCard || '';
        state.selectedDashboardType = button.dataset.dashboardType || '';
        renderWorkbench();
      });
    });
  }

  function renderNormalizePrimary() {
    const payload = currentNormalizePayload();
    if (!payload) {
      el.primaryContent.innerHTML = '<div class="wb-empty">Run normalize to build rename proposals.</div>';
      return;
    }
    const rows = normalizeRows(payload);
    const warningCounts = counter((payload.warnings || []).map(warning => warning.code));
    el.primaryContent.innerHTML = `
      <div class="wb-note">
        <div class="wb-kicker">Warnings</div>
        <div>${Object.entries(warningCounts).map(([code, count]) => `<span class="wb-chip review">${escapeHtml(code)}${count > 1 ? ` ×${count}` : ''}</span>`).join('') || '<span class="wb-subtle">No warnings.</span>'}</div>
      </div>
      <div class="wb-table-wrap">
        <table>
          <thead><tr><th></th><th>Confidence</th><th>Current</th><th>Proposed</th></tr></thead>
          <tbody>
            ${rows.map(result => `
              <tr>
                <td><input type="checkbox" data-normalize-row="${escapeHtml(result.result_id)}" ${state.selectedNormalizeResultIds.has(result.result_id) ? 'checked' : ''} ${result.actionable ? '' : 'disabled'}></td>
                <td><span class="wb-chip ${escapeHtml(result.confidence)}">${escapeHtml(result.confidence)}</span></td>
                <td class="wb-mono">${escapeHtml(result.current_value || '')}</td>
                <td class="wb-mono">${escapeHtml(result.proposed_value || '')}</td>
              </tr>
            `).join('') || '<tr><td colspan="4" class="wb-subtle">No results for this filter.</td></tr>'}
          </tbody>
        </table>
      </div>
    `;
    el.primaryContent.querySelectorAll('[data-normalize-row]').forEach(input => {
      input.addEventListener('change', () => {
        const id = input.dataset.normalizeRow;
        if (input.checked) state.selectedNormalizeResultIds.add(id);
        else state.selectedNormalizeResultIds.delete(id);
        renderWorkbench();
      });
    });
  }

  function renderQualityPrimary() {
    const payload = pagePayload('quality');
    if (!payload) {
      el.primaryContent.innerHTML = '<div class="wb-empty">Run Delete Weak Encodes to build the inspection surface.</div>';
      return;
    }
    const items = filteredQualityItems(payload);
    el.primaryContent.innerHTML = buildSelectionTable(items, item => state.selectedReplacementPaths.has(item.path || ''), item => ({
      id: item.path || '',
      cells: [
        `<span class="wb-chip ${escapeHtml(item?.profile?.weak_candidate ? 'high' : 'review')}">${escapeHtml(humanProfileLabel(item?.profile?.label || ''))}</span>`,
        escapeHtml(item?.facts?.resolution_bucket || '—'),
        escapeHtml(item?.facts?.audio_summary || '—'),
        `<span class="wb-mono">${escapeHtml(item.path || '')}</span>`,
      ],
    }), ['Profile', 'Resolution', 'Audio', 'Path'], 'data-quality-path');
    bindSelectionInputs('data-quality-path', state.selectedReplacementPaths);
  }

  function renderDefaultsPrimary() {
    const payload = pagePayload('fix_defaults');
    if (!payload) {
      el.primaryContent.innerHTML = '<div class="wb-empty">Run Repair Defaults to build the repair workbench.</div>';
      return;
    }
    if (state.fixDefaultsTab === 'audio') {
      const items = filteredAudioItems(payload);
      el.primaryContent.innerHTML = buildSelectionTable(items, item => state.selectedReplacementPaths.has(item.path || ''), item => ({
        id: item.path || '',
        cells: [
          `<span class="wb-chip ${escapeHtml(movieAudioPackagingIssueCode(item) === 'default_non_english_audio_with_weak_english' ? 'high' : 'review')}">${escapeHtml(movieAudioPackagingIssueCode(item).replaceAll('_', ' ') || 'audio issue')}</span>`,
          escapeHtml(describeAudioStream(movieDefaultAudioStream(item))),
          escapeHtml(describeAudioStream(bestEnglishAudioStream(item))),
          `<span class="wb-mono">${escapeHtml(item.path || '')}</span>`,
        ],
      }), ['Issue', 'Current Default', 'Best English', 'Path'], 'data-defaults-path');
    } else {
      const items = filteredSubtitleItems(payload);
      el.primaryContent.innerHTML = buildSelectionTable(items, item => state.selectedReplacementPaths.has(item.path || ''), item => ({
        id: item.path || '',
        cells: [
          escapeHtml(humanSubtitleReadinessIssueLabel(movieSubtitleReadinessIssueCode(item))),
          escapeHtml(describeSubtitleStream(movieDefaultSubtitleStream(item))),
          escapeHtml(describeSubtitleStream(movieSubtitleReadinessRepairTarget(item))),
          `<span class="wb-mono">${escapeHtml(item.path || '')}</span>`,
        ],
      }), ['Issue', 'Current Default', 'Repair Target', 'Path'], 'data-defaults-path');
    }
    bindSelectionInputs('data-defaults-path', state.selectedReplacementPaths);
  }

  function renderJunkPrimary() {
    const payload = pagePayload('junk');
    if (!payload) {
      el.primaryContent.innerHTML = '<div class="wb-empty">Run Delete Junk to inspect candidates.</div>';
      return;
    }
    const items = filteredMovieJunk(payload);
    el.primaryContent.innerHTML = buildSelectionTable(items, item => state.selectedJunkPaths.has(item.path || ''), item => ({
      id: item.path || '',
      cells: [
        `<span class="wb-chip ${escapeHtml(item.confidence || 'review')}">${escapeHtml(item.confidence || 'review')}</span>`,
        escapeHtml(item.file_name || ''),
        escapeHtml(item.file_size_label || '—'),
        `<span class="wb-mono">${escapeHtml(item.relative_path || item.path || '')}</span>`,
      ],
    }), ['Confidence', 'File', 'Size', 'Path'], 'data-junk-path');
    bindSelectionInputs('data-junk-path', state.selectedJunkPaths);
  }

  function renderCanonicalPrimary() {
    const payload = pagePayload('canonical_lists');
    if (!payload) {
      el.primaryContent.innerHTML = '<div class="wb-empty">Run Canonical Lists to populate the left page.</div>';
      return;
    }
    const lists = payload.list_summaries || [];
    el.primaryContent.innerHTML = `
      <div class="wb-card-grid">
        ${lists.map(item => `
          <div class="wb-card">
            <div class="wb-kicker">${escapeHtml(item.provider_label || 'Canonical list')}</div>
            <h3>${escapeHtml(item.label || 'List')}</h3>
            <div class="wb-count">${escapeHtml(`${item.covered_count || 0}/${item.total_count || 0}`)}</div>
            <div class="wb-subtle">${escapeHtml(String(item.missing_count || 0))} missing</div>
            <button data-canonical-id="${escapeHtml(item.id || '')}">Read</button>
          </div>
        `).join('')}
      </div>
    `;
    el.primaryContent.querySelectorAll('[data-canonical-id]').forEach(button => {
      button.addEventListener('click', () => {
        state.selectedCanonicalId = button.dataset.canonicalId || '';
        renderWorkbench();
      });
    });
  }

  function buildSelectionTable(items, checkedFn, rowFn, headers, attrName) {
    return `
      <div class="wb-table-wrap">
        <table>
          <thead><tr><th></th>${headers.map(label => `<th>${escapeHtml(label)}</th>`).join('')}</tr></thead>
          <tbody>
            ${items.map(item => {
              const row = rowFn(item);
              return `
                <tr>
                  <td><input type="checkbox" ${attrName}="${escapeHtml(row.id)}" ${checkedFn(item) ? 'checked' : ''}></td>
                  ${row.cells.map(cell => `<td>${cell}</td>`).join('')}
                </tr>
              `;
            }).join('') || `<tr><td colspan="${headers.length + 1}" class="wb-subtle">No visible items.</td></tr>`}
          </tbody>
        </table>
      </div>
    `;
  }

  function bindSelectionInputs(attrName, setRef) {
    el.primaryContent.querySelectorAll(`[${attrName}]`).forEach(input => {
      input.addEventListener('change', () => {
        const id = input.getAttribute(attrName) || '';
        if (input.checked) setRef.add(id);
        else setRef.delete(id);
        renderWorkbench();
      });
    });
  }

  function renderSecondarySurface() {
    const page = PAGE_CONFIG[state.page];
    el.secondaryTitle.textContent = page.secondaryTitle;
    if (state.auditExpanded) {
      el.secondaryModes.innerHTML = '';
      el.secondaryActionBar.innerHTML = '';
      el.secondaryContent.innerHTML = `<div class="wb-preview-block wb-surface-audit">${buildAuditExpandedContent()}</div>`;
      return;
    }

    if (page.mutationFlow) {
      el.secondaryModes.innerHTML = `
        <button class="wb-mode-btn ${state.secondaryMode === 'selected' ? 'active' : ''}" data-mode="selected">Preview Selected Changes</button>
        <button class="wb-mode-btn ${state.secondaryMode === 'diff' ? 'active' : ''}" data-mode="diff">Diff View</button>
        <button class="wb-mode-btn ${state.secondaryMode === 'full' ? 'active' : ''}" data-mode="full">Full Preview</button>
      `;
      el.secondaryModes.querySelectorAll('[data-mode]').forEach(button => {
        button.addEventListener('click', () => {
          state.secondaryMode = button.dataset.mode;
          renderSecondarySurface();
          renderAuditRail();
        });
      });
    } else {
      el.secondaryModes.innerHTML = '';
    }

    renderSecondaryActionBar();

    if (state.page === 'dashboard') {
      el.secondaryContent.innerHTML = buildDashboardSecondary();
      return;
    }
    if (state.page === 'normalize') {
      el.secondaryContent.innerHTML = buildNormalizeSecondary();
      return;
    }
    if (state.page === 'quality') {
      el.secondaryContent.innerHTML = buildQualitySecondary();
      return;
    }
    if (state.page === 'fix_defaults') {
      el.secondaryContent.innerHTML = buildDefaultsSecondary();
      return;
    }
    if (state.page === 'junk') {
      el.secondaryContent.innerHTML = buildJunkSecondary();
      return;
    }
    if (state.page === 'canonical_lists') {
      el.secondaryContent.innerHTML = buildCanonicalSecondary();
    }
  }

  function renderSecondaryActionBar() {
    let html = '';
    if (state.page === 'normalize') {
      const count = state.selectedNormalizeResultIds.size;
      html = `
        <div class="wb-inline-actions">
          <button id="applySelectedChanges" class="wb-btn wb-btn-primary" ${count ? '' : 'disabled'}>Apply ${count} Change${count === 1 ? '' : 's'}</button>
          <span class="wb-subtle">${count} selected</span>
        </div>
      `;
    } else if (state.page === 'quality') {
      const count = state.selectedReplacementPaths.size;
      html = `
        <div class="wb-inline-actions">
          <button id="deleteWeakEncodes" class="wb-btn wb-btn-danger" ${count ? '' : 'disabled'}>Delete ${count} File${count === 1 ? '' : 's'}</button>
          <span class="wb-subtle">Deletion is committed from the consequence surface, not the inspection surface.</span>
        </div>
      `;
    } else if (state.page === 'fix_defaults' && state.fixDefaultsTab === 'audio') {
      const count = state.selectedReplacementPaths.size;
      html = `
        <div class="wb-inline-actions">
          <button id="fixAudioDefaults" class="wb-btn wb-btn-safe" ${(count && !state.movieAudioFixBusy) ? '' : 'disabled'}>Set English Default</button>
          <button id="fixAudioDefaultsDrop" class="wb-btn wb-btn-warn" ${(count && !state.movieAudioFixBusy) ? '' : 'disabled'}>Set English Default + Drop Foreign</button>
          <button id="deleteAudioFallbacks" class="wb-btn wb-btn-danger" ${(count && !state.movieAudioFixBusy) ? '' : 'disabled'}>Delete ${count} File${count === 1 ? '' : 's'}</button>
        </div>
      `;
    } else if (state.page === 'fix_defaults') {
      const count = state.selectedReplacementPaths.size;
      html = `
        <div class="wb-inline-actions">
          <button id="fixSubtitleDefaults" class="wb-btn wb-btn-primary" ${(count && !state.movieSubtitleFixBusy) ? '' : 'disabled'}>Repair ${count} Title${count === 1 ? '' : 's'}</button>
          <span class="wb-subtle">Subtitle repair is non-destructive but still consequence-bearing.</span>
        </div>
      `;
    } else if (state.page === 'junk') {
      const count = state.selectedJunkPaths.size;
      html = `
        <div class="wb-inline-actions">
          <button id="deleteSelectedJunk" class="wb-btn wb-btn-danger" ${count ? '' : 'disabled'}>Delete ${count} File${count === 1 ? '' : 's'}</button>
          <span class="wb-subtle">Diff mode will render these as removals from the library shape.</span>
        </div>
      `;
    }
    el.secondaryActionBar.innerHTML = html;
    document.getElementById('applySelectedChanges')?.addEventListener('click', applySelectedMovieChanges);
    document.getElementById('deleteWeakEncodes')?.addEventListener('click', deleteSelectedWeakEncodes);
    document.getElementById('fixAudioDefaults')?.addEventListener('click', () => fixSelectedAudioDefaults(false));
    document.getElementById('fixAudioDefaultsDrop')?.addEventListener('click', () => fixSelectedAudioDefaults(true));
    document.getElementById('deleteAudioFallbacks')?.addEventListener('click', deleteSelectedWeakEncodes);
    document.getElementById('fixSubtitleDefaults')?.addEventListener('click', fixSelectedSubtitleDefaults);
    document.getElementById('deleteSelectedJunk')?.addEventListener('click', deleteSelectedJunk);
  }

  function buildDashboardSecondary() {
    const payload = pagePayload('dashboard');
    if (!payload) return '<div class="wb-empty">Run the dashboard scan to populate the right page.</div>';
    const histogram = payload.histogram || {};
    const summary = `
      <div class="wb-spread-stats">
        <div class="wb-card"><div class="wb-kicker">Video Mean</div><div class="wb-count">${escapeHtml(histogram.video_bitrate_kbps?.mean ? `${(histogram.video_bitrate_kbps.mean / 1000).toFixed(1)} Mbps` : '—')}</div></div>
        <div class="wb-card"><div class="wb-kicker">Audio Mean</div><div class="wb-count">${escapeHtml(histogram.audio_bitrate_kbps?.mean ? `${Math.round(histogram.audio_bitrate_kbps.mean)} kbps` : '—')}</div></div>
        <div class="wb-card"><div class="wb-kicker">Profiles</div><div class="wb-count">${escapeHtml(String(Object.keys(histogram.quality_profile_counts || {}).length))}</div></div>
      </div>
    `;
    if (!state.selectedDashboardKey) {
      return `${summary}<div class="wb-note">Select a dashboard card on the left to expand a profile or action lane here.</div>`;
    }
    const items = (payload.movies || []).filter(item => {
      if (state.selectedDashboardKey === 'deleted_awaiting_replacement') return false;
      if (state.selectedDashboardKey === 'replacement_candidate') return item?.profile?.label === 'replacement_candidate';
      if (state.selectedDashboardType === 'action') return item?.profile?.label === state.selectedDashboardKey;
      return item?.profile?.quality_label === state.selectedDashboardKey;
    });
    return `
      ${summary}
      <div class="wb-note">
        <div class="wb-kicker">Selected Card</div>
        <h3>${escapeHtml(humanProfileLabel(state.selectedDashboardKey))}</h3>
        <div class="wb-subtle">${escapeHtml(String(items.length))} titles in this group.</div>
      </div>
      <div class="wb-table-wrap">
        <table>
          <thead><tr><th>Title</th><th>Resolution</th><th>Audio</th><th>Path</th></tr></thead>
          <tbody>
            ${items.slice(0, 250).map(item => `
              <tr>
                <td>${escapeHtml(titleFromPath(item.path || ''))}</td>
                <td>${escapeHtml(item?.facts?.resolution_bucket || '—')}</td>
                <td>${escapeHtml(item?.facts?.audio_summary || '—')}</td>
                <td class="wb-mono">${escapeHtml(item.path || '')}</td>
              </tr>
            `).join('') || '<tr><td colspan="4" class="wb-subtle">No titles in this group.</td></tr>'}
          </tbody>
        </table>
      </div>
    `;
  }

  function buildNormalizeSecondary() {
    const payload = currentNormalizePayload();
    if (!payload) return '<div class="wb-empty">Run normalize to populate the consequence surface.</div>';
    const selected = selectedNormalizeResults(payload);
    if (state.secondaryMode === 'selected') return buildSelectedTreePreview(selected);
    if (state.secondaryMode === 'diff') return buildDiffPreview(selected.map(result => ({ current: result.current_value, proposed: result.proposed_value, confidence: result.confidence })), 'No selected rename results to diff.');
    return buildSelectedTreePreview((payload.movie_results || []).filter(result => result.actionable));
  }

  function buildQualitySecondary() {
    const payload = pagePayload('quality');
    if (!payload) return '<div class="wb-empty">Run the weak-encode scan to show consequence previews.</div>';
    const items = (payload.movies || []).filter(item => state.selectedReplacementPaths.has(item.path || ''));
    if (state.secondaryMode === 'selected') {
      return buildSelectionOutcomeList(items, item => ({
        title: titleFromPath(item.path || ''),
        body: `Replacement candidate · ${item?.facts?.resolution_bucket || 'resolution unknown'} · ${item?.facts?.audio_summary || 'audio unknown'}`,
      }), 'Select files on the left to preview the deletion consequence.');
    }
    if (state.secondaryMode === 'diff') {
      return buildDiffPreview(items.map(item => ({ current: item.path, proposed: '[deleted]', confidence: 'review' })), 'Select files on the left to view the deletion diff.');
    }
    return buildSelectionOutcomeList(filteredQualityItems(payload), item => ({
      title: titleFromPath(item.path || ''),
      body: `${state.selectedReplacementPaths.has(item.path || '') ? 'selected for deletion' : 'visible candidate'} · ${item?.facts?.resolution_bucket || 'resolution unknown'}`,
    }), 'No visible weak-encode candidates.');
  }

  function buildDefaultsSecondary() {
    const payload = pagePayload('fix_defaults');
    if (!payload) return '<div class="wb-empty">Run Repair Defaults to show consequence previews.</div>';
    const items = (payload.movies || []).filter(item => state.selectedReplacementPaths.has(item.path || ''));
    if (state.fixDefaultsTab === 'audio') {
      if (state.secondaryMode === 'selected') {
        return buildSelectionOutcomeList(items, item => ({
          title: titleFromPath(item.path || ''),
          body: `${describeAudioStream(movieDefaultAudioStream(item))} -> ${describeAudioStream(bestEnglishAudioStream(item))}`,
        }), 'Select audio-default issues to preview the remux consequence.');
      }
      if (state.secondaryMode === 'diff') {
        return buildDiffPreview(items.map(item => ({
          current: describeAudioStream(movieDefaultAudioStream(item)),
          proposed: describeAudioStream(bestEnglishAudioStream(item)),
          confidence: movieAudioPackagingIssueCode(item) === 'default_non_english_audio_with_weak_english' ? 'high' : 'review',
        })), 'Select audio-default issues to view the consequence diff.');
      }
      return buildSelectionOutcomeList(filteredAudioItems(payload), item => ({
        title: titleFromPath(item.path || ''),
        body: `${movieAudioPackagingIssueCode(item).replaceAll('_', ' ')} · ${state.selectedReplacementPaths.has(item.path || '') ? 'selected' : 'visible'}`,
      }), 'No visible audio-default issues.');
    }
    if (state.secondaryMode === 'selected') {
      return buildSelectionOutcomeList(items, item => ({
        title: titleFromPath(item.path || ''),
        body: `${describeSubtitleStream(movieDefaultSubtitleStream(item))} -> ${describeSubtitleStream(movieSubtitleReadinessRepairTarget(item))}`,
      }), 'Select subtitle-default issues to preview the consequence.');
    }
    if (state.secondaryMode === 'diff') {
      return buildDiffPreview(items.map(item => ({
        current: describeSubtitleStream(movieDefaultSubtitleStream(item)),
        proposed: describeSubtitleStream(movieSubtitleReadinessRepairTarget(item)) || 'clear defaults',
        confidence: 'review',
      })), 'Select subtitle-default issues to view the consequence diff.');
    }
    return buildSelectionOutcomeList(filteredSubtitleItems(payload), item => ({
      title: titleFromPath(item.path || ''),
      body: `${humanSubtitleReadinessIssueLabel(movieSubtitleReadinessIssueCode(item))} · ${state.selectedReplacementPaths.has(item.path || '') ? 'selected' : 'visible'}`,
    }), 'No visible subtitle issues.');
  }

  function buildJunkSecondary() {
    const payload = pagePayload('junk');
    if (!payload) return '<div class="wb-empty">Run Delete Junk to populate the consequence surface.</div>';
    const items = (payload.junk || []).filter(item => state.selectedJunkPaths.has(item.path || ''));
    if (state.secondaryMode === 'selected') {
      return buildSelectionOutcomeList(items, item => ({
        title: item.file_name || titleFromPath(item.path || ''),
        body: `${item.file_size_label || 'size unknown'} · ${(item.reasons || []).map(reason => reason.code).join(', ') || 'junk candidate'}`,
      }), 'Select junk candidates on the left to preview the deletion set.');
    }
    if (state.secondaryMode === 'diff') {
      return buildDiffPreview(items.map(item => ({ current: item.relative_path || item.path, proposed: '[deleted]', confidence: item.confidence || 'review' })), 'Select junk candidates to view a deletion diff.');
    }
    return buildSelectionOutcomeList(filteredMovieJunk(payload), item => ({
      title: item.file_name || titleFromPath(item.path || ''),
      body: `${state.selectedJunkPaths.has(item.path || '') ? 'selected for deletion' : 'visible candidate'} · ${item.confidence || 'review'}`,
    }), 'No visible junk candidates.');
  }

  function buildCanonicalSecondary() {
    const payload = pagePayload('canonical_lists');
    if (!payload) return '<div class="wb-empty">Run Canonical Lists to populate the right page.</div>';
    if (!state.selectedCanonicalId) {
      return `
        <div class="wb-note">
          <div class="wb-kicker">Canonical Reading</div>
          <h3>Badge and list context</h3>
          <div class="wb-subtle">${escapeHtml(String((payload.badges || []).filter(badge => badge.unlocked).length))} badges unlocked.</div>
        </div>
        <div class="wb-card-grid">
          ${(payload.badges || []).map(badge => `
            <div class="wb-card">
              <div class="wb-kicker">${badge.unlocked ? 'Unlocked' : 'Locked'}</div>
              <h3>${escapeHtml(badge.label || 'Badge')}</h3>
              <div class="wb-subtle">${escapeHtml(String((badge.coverage_percent || 0).toFixed(1)))}% / threshold ${(badge.threshold_percent || 0).toFixed(1)}%</div>
            </div>
          `).join('')}
        </div>
      `;
    }
    const list = (payload.list_summaries || []).find(item => item.id === state.selectedCanonicalId);
    const entries = list?.all_entries || [];
    return `
      <div class="wb-note">
        <div class="wb-kicker">Selected List</div>
        <h3>${escapeHtml(list?.label || 'List')}</h3>
        <div class="wb-subtle">${escapeHtml(String(list?.covered_count || 0))} owned · ${escapeHtml(String(list?.missing_count || 0))} missing.</div>
      </div>
      <div class="wb-table-wrap">
        <table>
          <thead><tr><th>#</th><th>Title</th><th>Year</th><th>Status</th></tr></thead>
          <tbody>
            ${entries.map((entry, index) => `
              <tr>
                <td>${index + 1}</td>
                <td>${escapeHtml(entry.title || '')}</td>
                <td>${escapeHtml(String(entry.year || '—'))}</td>
                <td>${entry.owned ? '<span class="wb-chip safe">owned</span>' : '<span class="wb-chip review">missing</span>'}</td>
              </tr>
            `).join('') || '<tr><td colspan="4" class="wb-subtle">No list entries available.</td></tr>'}
          </tbody>
        </table>
      </div>
    `;
  }

  function buildSelectedTreePreview(results) {
    if (!results.length) return '<div class="wb-empty">Select rows on the left to preview the downstream shape.</div>';
    const tree = {};
    results.forEach(result => {
      const path = String(result.proposed_value || result.current_value || '');
      const slash = path.lastIndexOf('/');
      const dir = slash >= 0 ? path.slice(0, slash) : '';
      const file = slash >= 0 ? path.slice(slash + 1) : path;
      let node = tree;
      dir.split('/').filter(Boolean).forEach(part => {
        node[part] = node[part] || {};
        node = node[part];
      });
      if (!node._files) node._files = [];
      node._files.push(file);
    });
    const lines = [];
    flattenTree(tree, lines, 0);
    return `
      <div class="wb-preview-block">
        <div class="wb-kicker">Preview Selected Changes</div>
        <div class="wb-subtle">Live render of selected downstream shape.</div>
      </div>
      <div class="wb-preview-block wb-mono">
        ${lines.map(line => `<div class="wb-tree-line wb-indent-${Math.min(line.depth, 5)}">${escapeHtml(line.label)}</div>`).join('')}
      </div>
    `;
  }

  function buildDiffPreview(items, emptyText) {
    if (!items.length) return `<div class="wb-empty">${escapeHtml(emptyText)}</div>`;
    return `
      <div class="wb-list">
        ${items.map(item => `
          <div class="wb-preview-block">
            <div><span class="wb-chip ${escapeHtml(item.confidence || 'review')}">${escapeHtml(item.confidence || 'review')}</span></div>
            <div class="wb-mono">- ${escapeHtml(item.current || '')}</div>
            <div class="wb-mono">+ ${escapeHtml(item.proposed || '')}</div>
          </div>
        `).join('')}
      </div>
    `;
  }

  function buildSelectionOutcomeList(items, rowBuilder, emptyText) {
    if (!items.length) return `<div class="wb-empty">${escapeHtml(emptyText)}</div>`;
    return `
      <div class="wb-list">
        ${items.map(item => {
          const row = rowBuilder(item);
          return `
            <div class="wb-preview-block">
              <h3>${escapeHtml(row.title)}</h3>
              <div class="wb-subtle">${escapeHtml(row.body)}</div>
            </div>
          `;
        }).join('')}
      </div>
    `;
  }

  function renderAuditRail() {
    const pieces = auditRailPieces();
    el.auditRailContent.innerHTML = pieces.length ? pieces.map(piece => `
      <div class="wb-rail-pip">
        <div class="wb-audit-count">${escapeHtml(String(piece.count))}</div>
        <div class="wb-audit-minor">${escapeHtml(piece.label)}</div>
      </div>
    `).join('') : '<div class="wb-audit-minor">No audit state.</div>';
    el.auditToggle.textContent = state.auditExpanded ? 'Return' : 'Expand';
  }

  function auditRailPieces() {
    const pieces = [];
    if (state.auditEvents.length) pieces.push({ count: state.auditEvents.length, label: 'session events' });
    const queue = pagePayload()?.replacement_queue || state.results.replacementQueue;
    if (queue?.items?.length) {
      const deleted = queue.items.filter(item => item.status === 'deleted').length;
      const completed = queue.items.filter(item => item.status === 'completed').length;
      if (deleted) pieces.push({ count: deleted, label: 'awaiting replacement' });
      if (completed) pieces.push({ count: completed, label: 'replaced' });
    }
    const subtitleActive = (state.subtitleHistory?.items || []).filter(item => !item.dismissed_at).length;
    if (subtitleActive) pieces.push({ count: subtitleActive, label: 'subtitle history' });
    const junkHistory = sessionJunkHistory().length;
    if (junkHistory) pieces.push({ count: junkHistory, label: 'junk deletions' });
    return pieces;
  }

  function buildAuditExpandedContent() {
    const queue = pagePayload()?.replacement_queue || state.results.replacementQueue;
    const queueItems = queue?.items || [];
    const subtitleItems = (state.subtitleHistory?.items || []).filter(item => !item.dismissed_at);
    const junkItems = sessionJunkHistory();
    const sections = [];
    if (state.auditEvents.length) {
      sections.push(`
        <div class="wb-note">
          <div class="wb-kicker">Session Ledger</div>
          ${state.auditEvents.map(event => `
            <div class="wb-audit-event">
              <strong>${escapeHtml(event.title)}</strong>
              <div class="wb-subtle">${escapeHtml(event.detail)}</div>
              <div class="wb-subtle">${escapeHtml(event.flow)} · ${escapeHtml(new Date(event.at).toLocaleString())}</div>
            </div>
          `).join('')}
        </div>
      `);
    }
    if (queueItems.length) {
      sections.push(`
        <div class="wb-note">
          <div class="wb-kicker">Replacement Queue Ledger</div>
          <div class="wb-table-wrap">
            <table>
              <thead><tr><th>Title</th><th>Status</th><th>Issue</th></tr></thead>
              <tbody>
                ${queueItems.map(item => `
                  <tr>
                    <td>${escapeHtml(item.title ? `${item.title}${item.year ? ` (${item.year})` : ''}` : titleFromPath(item.original_path || ''))}</td>
                    <td><span class="wb-chip ${escapeHtml(item.status === 'completed' ? 'safe' : item.status === 'deleted' ? 'review' : 'meta')}">${escapeHtml(item.status || 'pending')}</span></td>
                    <td>${escapeHtml(item.issue_family || 'weak_encode')}</td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        </div>
      `);
    }
    if (subtitleItems.length) {
      sections.push(`
        <div class="wb-note">
          <div class="wb-kicker">Subtitle History</div>
          <div class="wb-table-wrap">
            <table>
              <thead><tr><th>Title</th><th>Issue</th><th>Type</th></tr></thead>
              <tbody>
                ${subtitleItems.map(item => `
                  <tr>
                    <td>${escapeHtml(item.title ? `${item.title}${item.year ? ` (${item.year})` : ''}` : titleFromPath(item.path || ''))}</td>
                    <td>${escapeHtml(humanSubtitleReadinessIssueLabel(item.issue_code || ''))}</td>
                    <td><span class="wb-chip ${escapeHtml(item.entry_type === 'fixed' ? 'safe' : 'review')}">${escapeHtml(item.entry_type === 'fixed' ? 'fixed' : 'review only')}</span></td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        </div>
      `);
    }
    if (junkItems.length) {
      sections.push(`
        <div class="wb-note">
          <div class="wb-kicker">Deleted Junk This Session</div>
          <div class="wb-table-wrap">
            <table>
              <thead><tr><th>File</th><th>Size</th><th>Deleted</th></tr></thead>
              <tbody>
                ${junkItems.map(item => `
                  <tr>
                    <td>${escapeHtml(item.file_name || titleFromPath(item.path || ''))}</td>
                    <td>${escapeHtml(item.file_size_label || '—')}</td>
                    <td>${escapeHtml(new Date(item.deleted_at).toLocaleTimeString())}</td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        </div>
      `);
    }
    return sections.join('') || '<div class="wb-empty">No audit material is recorded yet.</div>';
  }

  function sessionJunkHistory() {
    return state.auditEvents
      .filter(event => event.flow === 'junk_delete')
      .flatMap(event => event.items || []);
  }

  function bestEnglishAudioStream(item) {
    const streams = (item?.facts?.audio_streams || []).filter(stream => audioStreamLanguage(stream) === 'english');
    if (!streams.length) return null;
    return [...streams].sort((a, b) => {
      const channels = (b?.channels || 0) - (a?.channels || 0);
      if (channels) return channels;
      return (b?.bitrate_kbps || 0) - (a?.bitrate_kbps || 0);
    })[0];
  }

  function titleFromPath(path) {
    const stem = String(path || '').split('/').pop().replace(/\.[^.]+$/, '');
    const match = stem.match(/^(.+?)\s*\((\d{4})\)/);
    return match ? `${match[1]} (${match[2]})` : stem;
  }

  async function runCurrentPage() {
    const page = PAGE_CONFIG[state.page];
    const source = currentSource();
    if (!source) {
      setStatus('Choose a source directory first.', 'error');
      return;
    }
    if (state.activeRunController) {
      state.activeRunController.abort();
      return;
    }
    state.activeRunController = new AbortController();
    updateRunButton();
    setStatus(`Running ${page.label}…`, 'running');
    startStatusTimer();
    try {
      const warning = await fetchScanWarning(source);
      state.scanWarning = warning?.message || '';
      const body = { source };
      const payload = await fetchJson(page.endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: state.activeRunController.signal,
      });
      if (state.page === 'dashboard' || state.page === 'quality' || state.page === 'fix_defaults') {
        state.results.profile = payload;
        state.results.replacementQueue = payload.replacement_queue || state.results.replacementQueue;
        if (state.page === 'fix_defaults' && state.fixDefaultsTab === 'subtitle') await syncSubtitleReviewOnlyHistory(payload);
      } else if (state.page === 'normalize') {
        state.results.normalize = payload;
      } else if (state.page === 'junk') {
        state.results.junk = payload;
      } else if (state.page === 'canonical_lists') {
        state.results.canonical = payload;
      }
      setStatus(`${page.label} ready.`, 'idle');
      renderWorkbench();
    } catch (error) {
      if (error.name === 'AbortError') setStatus('Scan stopped.', 'idle');
      else setStatus(error.message, 'error');
    } finally {
      state.activeRunController = null;
      updateRunButton();
      stopStatusTimer();
    }
  }

  async function fetchScanWarning(source) {
    try {
      return await fetchJson('/api/source/scan-warning', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source }),
      });
    } catch (_error) {
      return null;
    }
  }

  async function applySelectedMovieChanges() {
    const payload = currentNormalizePayload();
    const source = currentSource();
    const changes = (payload?.proposed_changes || []).filter(change => {
      return selectedNormalizeResults(payload).some(result => (result.change_ids || []).includes(change.item_id));
    });
    if (!source || !payload || !changes.length) return;
    setStatus(`Applying ${changes.length} changes…`, 'running');
    try {
      const result = await fetchJson('/api/movies/apply', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source, changes }),
      });
      state.results.normalizeApply = result;
      state.results.normalize = result.remaining_plan || null;
      const applied = result.applied?.length || 0;
      const failed = result.failed?.length || 0;
      addAuditEvent('normalize_apply', `Applied ${applied} change${applied === 1 ? '' : 's'}`, `${failed} failed; ${result.remaining_safe_count || 0} safe and ${result.remaining_review_count || 0} review remain.`);
      state.selectedNormalizeResultIds.clear();
      setStatus(`Applied ${applied} changes.`, failed ? 'error' : 'idle');
      renderWorkbench();
    } catch (error) {
      setStatus(error.message, 'error');
    }
  }

  async function deleteSelectedWeakEncodes() {
    const source = currentSource();
    const payload = pagePayload('quality');
    if (!source || !payload) return;
    const items = (payload.movies || []).filter(item => state.selectedReplacementPaths.has(item.path || ''));
    if (!items.length) return;
    if (!window.confirm(`Permanently delete ${items.length} file${items.length === 1 ? '' : 's'}? This cannot be undone.`)) return;
    setStatus(`Deleting ${items.length} file${items.length === 1 ? '' : 's'}…`, 'running');
    try {
      const add = await fetchJson('/api/movies/replacement-queue/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source, mode: 'file', issue_family: state.page === 'fix_defaults' && state.fixDefaultsTab === 'audio' ? 'audio_packaging' : 'weak_encode', items }),
      });
      const itemIds = (add.added || []).map(item => item.item_id).filter(Boolean);
      const result = await fetchJson('/api/movies/replacement-queue/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source, item_ids: itemIds }),
      });
      state.results.replacementQueue = result;
      if (state.results.profile) state.results.profile.replacement_queue = result;
      state.selectedReplacementPaths.clear();
      addAuditEvent('replacement_delete', `Deleted ${result.deleted.length} file${result.deleted.length === 1 ? '' : 's'}`, `${result.skipped?.length || 0} skipped; replacement queue updated.`);
      setStatus(`Deleted ${result.deleted.length} file${result.deleted.length === 1 ? '' : 's'}.`, 'idle');
      renderWorkbench();
    } catch (error) {
      setStatus(error.message, 'error');
    }
  }

  async function fixSelectedAudioDefaults(dropForeignAudio) {
    const source = currentSource();
    const payload = pagePayload('fix_defaults');
    const paths = Array.from(state.selectedReplacementPaths);
    if (!source || !payload || !paths.length || state.movieAudioFixBusy) return;
    state.movieAudioFixBusy = true;
    renderWorkbench();
    setStatus(`Repairing ${paths.length} audio default${paths.length === 1 ? '' : 's'}…`, 'running');
    try {
      const result = await fetchJson('/api/movies/audio-packaging/fix', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source, paths, drop_foreign_audio: dropForeignAudio }),
      });
      if (state.results.profile) state.results.profile.replacement_queue = result.replacement_queue || state.results.profile.replacement_queue;
      state.results.replacementQueue = result.replacement_queue || state.results.replacementQueue;
      state.selectedReplacementPaths.clear();
      addAuditEvent('audio_fix', `Repaired ${result.fixed?.length || 0} audio default${(result.fixed?.length || 0) === 1 ? '' : 's'}`, dropForeignAudio ? 'English default set; tagged foreign audio removed where possible.' : 'English default set.');
      setStatus(`Fixed ${result.fixed?.length || 0} file${(result.fixed?.length || 0) === 1 ? '' : 's'}.`, 'idle');
      renderWorkbench();
    } catch (error) {
      setStatus(error.message, 'error');
    } finally {
      state.movieAudioFixBusy = false;
      renderWorkbench();
    }
  }

  async function fixSelectedSubtitleDefaults() {
    const source = currentSource();
    const payload = pagePayload('fix_defaults');
    const items = filteredSubtitleItems(payload).filter(item => state.selectedReplacementPaths.has(item.path || ''));
    const paths = items.map(item => item.path).filter(Boolean);
    if (!source || !payload || !paths.length || state.movieSubtitleFixBusy) return;
    const issueCodes = {};
    items.forEach(item => { issueCodes[item.path] = movieSubtitleReadinessIssueCode(item); });
    state.movieSubtitleFixBusy = true;
    renderWorkbench();
    setStatus(`Repairing ${paths.length} subtitle default${paths.length === 1 ? '' : 's'}…`, 'running');
    try {
      const result = await fetchJson('/api/movies/subtitle-readiness/fix', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source, paths, issue_codes: issueCodes }),
      });
      if (result.subtitle_history) state.subtitleHistory = result.subtitle_history;
      state.selectedReplacementPaths.clear();
      addAuditEvent('subtitle_fix', `Repaired ${result.fixed?.length || 0} subtitle default${(result.fixed?.length || 0) === 1 ? '' : 's'}`, `${result.skipped?.length || 0} skipped.`);
      setStatus(`Fixed ${result.fixed?.length || 0} file${(result.fixed?.length || 0) === 1 ? '' : 's'}.`, 'idle');
      renderWorkbench();
    } catch (error) {
      setStatus(error.message, 'error');
    } finally {
      state.movieSubtitleFixBusy = false;
      renderWorkbench();
    }
  }

  async function deleteSelectedJunk() {
    const source = currentSource();
    const payload = pagePayload('junk');
    const paths = Array.from(state.selectedJunkPaths);
    if (!source || !payload || !paths.length) return;
    if (!window.confirm(`Delete ${paths.length} junk file${paths.length === 1 ? '' : 's'}? This cannot be undone.`)) return;
    setStatus(`Deleting ${paths.length} junk file${paths.length === 1 ? '' : 's'}…`, 'running');
    try {
      const result = await fetchJson('/api/movies/junk/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source, paths }),
      });
      const deletedSet = new Set(result.deleted || []);
      const deletedItems = (payload.junk || []).filter(item => deletedSet.has(item.path || '')).map(item => ({ ...item, deleted_at: new Date().toISOString() }));
      state.results.junk = {
        ...payload,
        junk: (payload.junk || []).filter(item => !deletedSet.has(item.path || '')),
      };
      state.selectedJunkPaths.clear();
      addAuditEvent('junk_delete', `Deleted ${result.deleted.length} junk file${result.deleted.length === 1 ? '' : 's'}`, `${result.skipped?.length || 0} skipped.`);
      state.auditEvents[0].items = deletedItems;
      setStatus(`Deleted ${result.deleted.length} junk file${result.deleted.length === 1 ? '' : 's'}.`, 'idle');
      renderWorkbench();
    } catch (error) {
      setStatus(error.message, 'error');
    }
  }

  async function syncSubtitleReviewOnlyHistory(payload) {
    const source = currentSource();
    if (!source || !payload) return;
    const items = (payload.movies || [])
      .filter(item => movieSubtitleReadinessIssueCode(item) && !movieSubtitleReadinessIsRepairable(item))
      .map(item => ({ path: item.path || '', issue_code: movieSubtitleReadinessIssueCode(item) }))
      .filter(item => item.path);
    try {
      state.subtitleHistory = await fetchJson('/api/movies/subtitle-readiness/history/sync', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source, items }),
      });
    } catch (_error) {
      state.subtitleHistory = null;
    }
  }

  function renderWorkbench() {
    renderRibbon();
    renderSliver();
    renderPrimarySurface();
    renderSecondarySurface();
    renderAuditRail();
  }

  function bindGlobalEvents() {
    el.sourcePath.value = state.source;
    el.sourcePath.addEventListener('change', () => {
      state.source = currentSource();
      renderWorkbench();
      startActivityPolling();
    });
    el.runButton.addEventListener('click', runCurrentPage);
    el.fileTreeToggle.addEventListener('click', () => {
      state.fileTreeExpanded = !state.fileTreeExpanded;
      renderSliver();
    });
    el.auditToggle.addEventListener('click', () => {
      state.auditExpanded = !state.auditExpanded;
      renderSecondarySurface();
      renderAuditRail();
    });
  }

  renderPageNav();
  bindGlobalEvents();
  updateRunButton();
  renderWorkbench();
  startActivityPolling();
})();
