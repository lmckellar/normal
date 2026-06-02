(function () {
  const WORKFLOW_LABELS = {
    normalize: 'Movie Normalize',
    'weak-encodes': 'Weak Encodes',
    'repair-defaults': 'Repair Defaults',
    junk: 'Delete Junk & Spam',
  };

  const WORKFLOW_DESCRIPTIONS = {
    normalize: 'Normalize diagnostics with row reasoning and direct confirm/apply.',
    'weak-encodes': 'Weak encode triage with delete preview and explicit destructive confirm.',
    'repair-defaults': 'Repair audio and subtitle defaults with the same compact scan and preview shell.',
    junk: 'Destructive junk triage with explicit confirm and local delete preview.',
  };

  const LAYOUT_MODES = {
    default: '2-page-lopsided',
    book: '3-page-book',
    ledger: '4-page-ledger',
  };

  const NORMALIZE_HEADERS = [
    { key: 'select', label: '', columnClass: 'lab-col-select', priority: 'essential', width: 'var(--lab-table-select-column-width)' },
    { key: 'current_value', label: 'File Name', columnClass: 'lab-col-anchor', cellClass: 'lab-cell-anchor lab-cell-mono', priority: 'essential', width: 'auto' },
    { key: 'projected_path', label: 'Projected Path', columnClass: 'lab-col-path', cellClass: 'lab-cell-path lab-cell-mono', priority: 'desktop', width: '36%' },
    { key: 'confidence', label: 'Confidence', columnClass: 'lab-col-status', cellClass: 'lab-cell-status', priority: 'essential', width: '11ch' },
    { key: 'reason_bucket', label: 'Reason', columnClass: 'lab-col-status', cellClass: 'lab-cell-status', priority: 'medium', width: '11ch' },
  ];

  const WEAK_HEADERS = [
    { key: 'select', label: '', columnClass: 'lab-col-select', priority: 'essential', width: 'var(--lab-table-select-column-width)' },
    { key: 'current_path', label: 'File Name', columnClass: 'lab-col-anchor', cellClass: 'lab-cell-anchor lab-cell-mono', priority: 'essential', width: 'auto' },
    { key: 'issue', label: 'Issue', columnClass: 'lab-col-issue', cellClass: 'lab-cell-decision', priority: 'essential', width: '22%' },
    { key: 'resolution', label: 'Resolution', columnClass: 'lab-col-resolution', cellClass: 'lab-cell-supporting', priority: 'medium', width: '11%' },
    { key: 'video_bitrate', label: 'Video', columnClass: 'lab-col-signal', cellClass: 'lab-cell-signal lab-cell-mono', priority: 'essential', width: '11ch' },
    { key: 'audio_bitrate', label: 'Audio', columnClass: 'lab-col-signal', cellClass: 'lab-cell-signal lab-cell-mono', priority: 'desktop', width: '11ch' },
    { key: 'channels', label: 'Ch', columnClass: 'lab-col-signal', cellClass: 'lab-cell-signal lab-cell-mono', priority: 'medium', width: '7ch' },
    { key: 'audio_summary', label: 'Audio Summary', columnClass: 'lab-col-audio-summary', cellClass: 'lab-cell-supporting', priority: 'desktop', width: '18%' },
    { key: 'file_size', label: 'Size', columnClass: 'lab-col-signal', cellClass: 'lab-cell-signal lab-cell-mono', priority: 'medium', width: '11ch' },
  ];

  const JUNK_HEADERS = [
    { key: 'select', label: '', columnClass: 'lab-col-select', priority: 'essential', width: 'var(--lab-table-select-column-width)' },
    { key: 'current_path', label: 'File Name', columnClass: 'lab-col-anchor', cellClass: 'lab-cell-anchor lab-cell-mono', priority: 'essential', width: 'auto' },
    { key: 'issue', label: 'Issue', columnClass: 'lab-col-issue', cellClass: 'lab-cell-decision', priority: 'essential', width: '22%' },
    { key: 'resolution', label: 'Resolution', columnClass: 'lab-col-resolution', cellClass: 'lab-cell-supporting', priority: 'medium', width: '11%' },
    { key: 'video_bitrate', label: 'Video', columnClass: 'lab-col-signal', cellClass: 'lab-cell-signal lab-cell-mono', priority: 'essential', width: '11ch' },
    { key: 'audio_bitrate', label: 'Audio', columnClass: 'lab-col-signal', cellClass: 'lab-cell-signal lab-cell-mono', priority: 'desktop', width: '11ch' },
    { key: 'confidence', label: 'Confidence', columnClass: 'lab-col-signal', cellClass: 'lab-cell-signal', priority: 'medium', width: '11ch' },
    { key: 'audio_summary', label: 'Audio Summary', columnClass: 'lab-col-audio-summary', cellClass: 'lab-cell-supporting', priority: 'desktop', width: '18%' },
    { key: 'file_size', label: 'Size', columnClass: 'lab-col-signal', cellClass: 'lab-cell-signal lab-cell-mono', priority: 'medium', width: '11ch' },
  ];

  const REPAIR_AUDIO_HEADERS = [
    { key: 'select', label: '', columnClass: 'lab-col-select', priority: 'essential', width: 'var(--lab-table-select-column-width)' },
    { key: 'current_path', label: 'File Name', columnClass: 'lab-col-anchor', cellClass: 'lab-cell-anchor lab-cell-mono', priority: 'essential', width: 'auto' },
    { key: 'issue', label: 'Issue', columnClass: 'lab-col-issue', cellClass: 'lab-cell-decision', priority: 'essential', width: '24%' },
    { key: 'current_default', label: 'Current Default', columnClass: 'lab-col-resolution', cellClass: 'lab-cell-supporting', priority: 'medium', width: '14%' },
    { key: 'repair_target', label: 'Best English', columnClass: 'lab-col-resolution', cellClass: 'lab-cell-supporting', priority: 'desktop', width: '14%' },
    { key: 'resolution', label: 'Resolution', columnClass: 'lab-col-signal', cellClass: 'lab-cell-signal', priority: 'medium', width: '11ch' },
    { key: 'file_size', label: 'Size', columnClass: 'lab-col-signal', cellClass: 'lab-cell-signal lab-cell-mono', priority: 'medium', width: '11ch' },
  ];

  const REPAIR_SUBTITLE_HEADERS = [
    { key: 'select', label: '', columnClass: 'lab-col-select', priority: 'essential', width: 'var(--lab-table-select-column-width)' },
    { key: 'current_path', label: 'File Name', columnClass: 'lab-col-anchor', cellClass: 'lab-cell-anchor lab-cell-mono', priority: 'essential', width: 'auto' },
    { key: 'issue', label: 'Issue', columnClass: 'lab-col-issue', cellClass: 'lab-cell-decision', priority: 'essential', width: '24%' },
    { key: 'current_default', label: 'Current Default', columnClass: 'lab-col-resolution', cellClass: 'lab-cell-supporting', priority: 'medium', width: '14%' },
    { key: 'repair_target', label: 'Repair Target', columnClass: 'lab-col-resolution', cellClass: 'lab-cell-supporting', priority: 'desktop', width: '14%' },
    { key: 'resolution', label: 'Resolution', columnClass: 'lab-col-signal', cellClass: 'lab-cell-signal', priority: 'medium', width: '11ch' },
    { key: 'file_size', label: 'Size', columnClass: 'lab-col-signal', cellClass: 'lab-cell-signal lab-cell-mono', priority: 'medium', width: '11ch' },
  ];

  const state = {
    workflow: workflowFromUrl(),
    layoutMode: LAYOUT_MODES.default,
    normalizePayload: null,
    weakPayload: null,
    repairPayload: null,
    junkPayload: null,
    rows: [],
    filteredRows: [],
    selected: new Set(),
    activeRowId: '',
    sort: { key: 'current_value', dir: 'asc' },
    runInFlight: false,
    previewMode: 'selected',
    applyInFlight: false,
    weakFloor: 'standard_definition',
    weakPreview: null,
    weakPreviewKey: '',
    weakPreviewLoading: false,
    repairDefaultsTab: 'audio',
    repairAction: 'set_english_default',
    repairActionNotice: '',
    audioFixBusy: false,
    subtitleFixBusy: false,
    audioPopoverRowId: '',
    junkDeleteSkipped: [],
    junkFilenameResizeObserver: null,
    junkFilenameResizeFrame: 0,
  };

  const el = {
    shell: document.querySelector('.lab-shell'),
    pages: Array.from(document.querySelectorAll('.lab-page')),
    workflowButton: document.getElementById('workflowButton'),
    workflowTitle: document.getElementById('workflowTitle'),
    workflowDescription: document.getElementById('workflowDescription'),
    workflowMenu: document.getElementById('workflowMenu'),
    workflowNormalize: document.getElementById('workflowNormalize'),
    workflowWeakEncodes: document.getElementById('workflowWeakEncodes'),
    workflowRepairDefaults: document.getElementById('workflowRepairDefaults'),
    workflowJunk: document.getElementById('workflowJunk'),
    sourcePath: document.getElementById('sourcePath'),
    runButton: document.getElementById('runButton'),
    searchInput: document.getElementById('searchInput'),
    bucketFilter: document.getElementById('bucketFilter'),
    caseFilter: document.getElementById('caseFilter'),
    reasonFilter: document.getElementById('reasonFilter'),
    warningFilter: document.getElementById('warningFilter'),
    workflowStatusFilter: document.getElementById('workflowStatusFilter'),
    weakFloorLabel: document.getElementById('weakFloorLabel'),
    weakFloorSelect: document.getElementById('weakFloorSelect'),
    repairDefaultsTabLabel: document.getElementById('repairDefaultsTabLabel'),
    repairDefaultsTabSelect: document.getElementById('repairDefaultsTabSelect'),
    selectAllButton: document.getElementById('selectAllButton'),
    deselectAllButton: document.getElementById('deselectAllButton'),
    tableColGroup: document.getElementById('tableColGroup'),
    tableHeaderRow: document.getElementById('tableHeaderRow'),
    rowsBody: document.getElementById('rowsBody'),
    previewControls: document.getElementById('previewControls'),
    previewScopeSelect: document.getElementById('previewScopeSelect'),
    repairActionControls: document.getElementById('repairActionControls'),
    repairActionSelect: document.getElementById('repairActionSelect'),
    repairActionButton: document.getElementById('repairActionButton'),
    confirmButton: document.getElementById('confirmButton'),
    previewPane: document.getElementById('previewPane'),
    audioTrackPopover: document.getElementById('audioTrackPopover'),
  };

  el.sourcePath.value = window.DEFAULT_SOURCE || '';

  function workflowFromUrl() {
    const params = new URLSearchParams(window.location.search);
    const workflow = params.get('workflow');
    if (workflow === 'weak-encodes' || workflow === 'junk' || workflow === 'repair-defaults') return workflow;
    return 'normalize';
  }

  function syncWorkflowUrl() {
    const url = new URL(window.location.href);
    url.searchParams.set('workflow', state.workflow);
    window.history.replaceState({}, '', url.toString());
  }

  function activePayload() {
    if (state.workflow === 'weak-encodes') return state.weakPayload;
    if (state.workflow === 'repair-defaults') return state.repairPayload;
    if (state.workflow === 'junk') return state.junkPayload;
    return state.normalizePayload;
  }

  function isWeakMode() {
    return state.workflow === 'weak-encodes';
  }

  function isJunkMode() {
    return state.workflow === 'junk';
  }

  function isRepairDefaultsMode() {
    return state.workflow === 'repair-defaults';
  }

  function usesSimpleSelectionShell() {
    return isWeakMode() || isRepairDefaultsMode() || isJunkMode();
  }

  function usesDeletePreviewShell() {
    return isWeakMode() || isJunkMode() || (isRepairDefaultsMode() && state.repairDefaultsTab === 'audio');
  }

  function defaultRepairAction() {
    return state.repairDefaultsTab === 'subtitle' ? 'repair_subtitle_defaults' : 'set_english_default';
  }

  function repairActionOptions() {
    if (state.repairDefaultsTab === 'subtitle') {
      return [{ value: 'repair_subtitle_defaults', label: 'Repair Subtitle Defaults' }];
    }
    return [
      { value: 'set_english_default', label: 'Set English Default' },
      { value: 'drop_foreign_passenger_audio', label: 'Delete Foreign Passenger Audio' },
      { value: 'set_english_default_drop_foreign', label: 'Do Both At Once' },
    ];
  }

  const QUALITY_STANCE_RANKS = {
    standard_definition: 0,
    compact_grade: 1,
    library_grade: 2,
    collector_grade: 3,
    reference: 4,
  };

  const WEAK_QUALITY_CODES = new Set([
    'video_below_minimum',
    'video_signal_missing',
    'audio_channels_below_minimum',
    'audio_bitrate_below_minimum',
    'audio_codec_below_minimum',
    'audio_signal_missing',
  ]);

  const JUNK_REASON_LABELS = {
    promo_document_name: 'promo document marker',
    promo_document_content: 'promo document marker',
    junk_file_token: 'filename junk marker',
    junk_ancestor_token: 'ancestor junk marker',
    small_video_file: 'very small video',
  };

  function weakFloorDefinitionOptions() {
    const options = state.weakPayload?.replacement_candidate_definition?.fields?.[0]?.options;
    const fallback = [
      { value: 'standard_definition', label: 'Standard Definition' },
      { value: 'compact_grade', label: 'Compact Grade' },
      { value: 'library_grade', label: 'Library Grade' },
    ];
    if (!Array.isArray(options)) return fallback;
    const filtered = options
      .filter(option => option?.value === 'standard_definition' || option?.value === 'compact_grade' || option?.value === 'library_grade')
      .map(option => ({ value: option.value, label: option.label || humanProfileLabel(option.value) }));
    return filtered.length ? filtered : fallback;
  }

  function escapeHtml(value) {
    return String(value || '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  }

  function formatFileSize(bytes) {
    const raw = Number(bytes || 0);
    if (!raw) return '—';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let value = raw;
    let unit = 0;
    while (value >= 1024 && unit < units.length - 1) {
      value /= 1024;
      unit += 1;
    }
    return `${value >= 100 || unit === 0 ? Math.round(value) : value.toFixed(1)} ${units[unit]}`;
  }

  function formatBitrate(kbps) {
    const raw = Number(kbps || 0);
    return raw ? `${Math.round(raw).toLocaleString()} kbps` : '—';
  }

  function audioChannelLayout(channels) {
    const raw = Number(channels || 0);
    if (!raw) return '—';
    if (raw === 1) return '1.0';
    if (raw === 2) return '2.0';
    if (raw === 6) return '5.1';
    if (raw === 8) return '7.1';
    return `${raw}ch`;
  }

  function displayAudioLanguage(language) {
    const code = String(language || '').trim().toLowerCase();
    if (!code) return 'Unknown';
    const known = {
      eng: 'English',
      ita: 'Italian',
      jpn: 'Japanese',
      fra: 'French',
      fre: 'French',
      spa: 'Spanish',
      ger: 'German',
      deu: 'German',
    };
    return known[code] || (code.length <= 3 ? code.toUpperCase() : code.charAt(0).toUpperCase() + code.slice(1));
  }

  function audioTracksForRow(row) {
    return Array.isArray(row?.item?.facts?.audio_streams) ? row.item.facts.audio_streams : [];
  }

  function fileNameFromPath(path) {
    const parts = String(path || '').split('/').filter(Boolean);
    return parts.length ? parts[parts.length - 1] : String(path || '');
  }

  function humanProfileLabel(label) {
    if (label === 'standard_definition') return 'Standard Definition';
    if (label === 'compact_grade') return 'Compact Grade';
    if (label === 'library_grade') return 'Library Grade';
    if (label === 'collector_grade') return 'Collector Grade';
    if (label === 'reference') return 'Reference';
    if (label === 'meets_minimum') return 'Meets Minimum';
    if (label === 'needs_review') return 'Needs Review';
    if (label === 'replacement_candidate') return 'Replacement Candidate';
    return String(label || '').split('_').filter(Boolean).map(word => word.charAt(0).toUpperCase() + word.slice(1)).join(' ');
  }

  function qualityStanceRank(label) {
    return QUALITY_STANCE_RANKS[String(label || '')] ?? -1;
  }

  function firstMovieProfileIssueResult(item) {
    const domainResults = item?.profile?.domain_results || [];
    return domainResults.find(result => result?.status === 'fail')
      || domainResults.find(result => result?.status === 'review_low_confidence')
      || null;
  }

  function movieProfileIssueThreshold(summary) {
    const match = String(summary || '').match(/(\d[\d,]*)/);
    return match ? match[1] : '';
  }

  function humanMovieProfileIssueLabel(code, summary = '') {
    if (code === 'video_below_minimum') return 'Below Min. Video Bitrate';
    if (code === 'video_signal_missing') return 'Video Signal Missing';
    if (code === 'audio_channels_below_minimum') {
      const threshold = movieProfileIssueThreshold(summary);
      return threshold ? `Main Audio Below ${threshold} Channels` : 'Main Audio Below Minimum Channels';
    }
    if (code === 'audio_bitrate_below_minimum') return 'Main Audio Below Min. Bitrate';
    if (code === 'audio_codec_below_minimum') return 'Main Audio Codec Below Minimum';
    if (code === 'audio_signal_missing') return 'Audio Signal Missing';
    if (code === 'audio_default_unknown') return 'Default Audio Unknown';
    if (code === 'audio_default_non_english_no_english_alt') return 'Non-English Default Audio';
    if (code === 'audio_default_non_english') return 'Wrong Default Audio Language';
    if (code === 'multiple_default_subtitles') return 'Multiple Default Subtitles';
    if (code === 'english_forced_not_default') return 'Forced English Not Default';
    if (code === 'wrong_default_forced_subtitle') return 'Wrong Forced Subtitle Default';
    if (code === 'missing_default_english_subtitle') return 'Missing Default English Subtitle';
    if (code === 'wrong_default_subtitle_language') return 'Wrong Default Subtitle Language';
    if (code === 'unnecessary_default_subtitle') return 'Unnecessary Default Subtitle';
    if (code === 'path_not_normalized') return 'Non-Standard Path';
    if (code === 'promo_sidecar_present') return 'Promo Sidecar Present';
    if (code === 'subtitle_policy_unknown') return 'Subtitle Policy Unknown';
    return code ? code.split('_').filter(Boolean).map(word => word.charAt(0).toUpperCase() + word.slice(1)).join(' ') : '';
  }

  function movieProfileInlineSummary(item) {
    const issue = firstMovieProfileIssueResult(item);
    if (issue) return humanMovieProfileIssueLabel(issue.code || '', issue.summary || '');
    if (item?.profile?.legacy_bitrate_label) return `Legacy ${item.profile.legacy_bitrate_label.replaceAll('_', ' ')}`;
    return '';
  }

  function movieHasPackagingOwnedIssue(item) {
    const diagnostics = item?.profile?.diagnostics || [];
    return diagnostics.some(diag => diag?.code === 'default_non_english_audio');
  }

  function movieHasWeakQualityIssue(item) {
    const domainResults = item?.profile?.domain_results || [];
    return domainResults.some(result => {
      const code = String(result?.code || '');
      const status = String(result?.status || '');
      return WEAK_QUALITY_CODES.has(code) && (status === 'fail' || status === 'review_low_confidence');
    });
  }

  function movieMeetsWeakFloor(item) {
    const qualityLabel = item?.profile?.quality_label || '';
    return qualityStanceRank(qualityLabel) <= qualityStanceRank(state.weakFloor);
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

  function movieBestEnglishAudioStream(item) {
    const streams = (item?.facts?.audio_streams || []).filter(stream => audioStreamLanguage(stream) === 'english');
    if (!streams.length) return null;
    return [...streams].sort((a, b) => {
      const ach = a?.channels || 0;
      const bch = b?.channels || 0;
      if (bch !== ach) return bch - ach;
      const abr = a?.bitrate_kbps || 0;
      const bbr = b?.bitrate_kbps || 0;
      return bbr - abr;
    })[0];
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
    return parts.join(' ');
  }

  function describeAudioStream(stream) {
    if (!stream) return '—';
    const language = audioStreamLanguage(stream);
    return [
      language ? language.charAt(0).toUpperCase() + language.slice(1) : 'Unknown',
      describeAudioFormat(stream),
      stream.bitrate_kbps ? `${Math.round(stream.bitrate_kbps).toLocaleString()} kbps` : null,
    ].filter(Boolean).join(' · ');
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

  function itemDefaultAudioLanguage(item) {
    return audioStreamLanguage(movieDefaultAudioStream(item)) || '';
  }

  function movieSubtitleReadinessRepairTarget(item) {
    const forced = chooseBestEnglishSubtitleStream(item, { forcedOnly: true });
    if (forced) return forced;
    if (!['', 'english'].includes(itemDefaultAudioLanguage(item))) return chooseBestEnglishSubtitleStream(item);
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
    return [language ? language.charAt(0).toUpperCase() + language.slice(1) : 'Unknown', stream?.is_forced ? 'forced' : null, stream?.title || null]
      .filter(Boolean)
      .join(' · ');
  }

  function repairDefaultsSelectionLocked() {
    return (state.repairDefaultsTab === 'audio' && state.audioFixBusy)
      || (state.repairDefaultsTab === 'subtitle' && state.subtitleFixBusy);
  }

  function renderWorkflowHeader() {
    el.workflowTitle.textContent = WORKFLOW_LABELS[state.workflow];
    el.workflowDescription.textContent = WORKFLOW_DESCRIPTIONS[state.workflow];
    el.workflowNormalize.classList.toggle('is-active', state.workflow === 'normalize');
    el.workflowWeakEncodes.classList.toggle('is-active', state.workflow === 'weak-encodes');
    el.workflowRepairDefaults.classList.toggle('is-active', state.workflow === 'repair-defaults');
    el.workflowJunk.classList.toggle('is-active', state.workflow === 'junk');
  }

  function renderShellLayout() {
    if (el.shell) el.shell.dataset.layoutMode = state.layoutMode;
    el.pages.forEach(page => {
      const role = page.dataset.pageRole || '';
      const hidden = false;
      page.dataset.panelState = hidden ? 'collapsed' : 'expanded';
      if (!page.dataset.collapseMode) {
        page.dataset.collapseMode = role === 'preview' ? 'anchored-slot' : 'reflow';
      }
    });
  }

  function renderRunButton() {
    const normalize = state.workflow === 'normalize';
    const repairDefaults = state.workflow === 'repair-defaults';
    const junk = state.workflow === 'junk';
    el.runButton.textContent = state.runInFlight ? 'Running' : (normalize ? 'Run Normalize' : (repairDefaults ? 'Run Repair Defaults' : (junk ? 'Run Delete Junk & Spam Files' : 'Run Weak Encodes')));
    el.runButton.disabled = state.runInFlight;
    el.runButton.classList.toggle('is-running', state.runInFlight);
  }

  function renderFilterVisibility() {
    const weak = isWeakMode();
    const repairDefaults = isRepairDefaultsMode();
    const junk = isJunkMode();
    el.bucketFilter.hidden = weak || repairDefaults || junk;
    el.caseFilter.hidden = weak || repairDefaults || junk;
    el.reasonFilter.hidden = weak || repairDefaults || junk;
    el.warningFilter.hidden = weak || repairDefaults || junk;
    el.workflowStatusFilter.hidden = !(weak || repairDefaults || junk);
    el.weakFloorLabel.hidden = !weak;
    el.weakFloorSelect.hidden = !weak;
    el.repairDefaultsTabLabel.hidden = !repairDefaults;
    el.repairDefaultsTabSelect.hidden = !repairDefaults;
    el.repairDefaultsTabSelect.value = state.repairDefaultsTab;
    renderWorkflowStatusFilter();
    renderWeakFloorControl();
    renderWorkflowActionControls();
  }

  function renderWorkflowStatusFilter() {
    if (isWeakMode()) {
      el.workflowStatusFilter.innerHTML = `
        <option value="all">all</option>
        <option value="delete-candidates">delete candidates</option>
        <option value="review">review</option>
        <option value="queued">queued</option>
      `;
      if (!['all', 'delete-candidates', 'review', 'queued'].includes(el.workflowStatusFilter.value)) {
        el.workflowStatusFilter.value = 'all';
      }
      return;
    }
    if (isJunkMode()) {
      el.workflowStatusFilter.innerHTML = `
        <option value="all">all</option>
        <option value="high">high</option>
        <option value="review">review</option>
      `;
      if (!['all', 'high', 'review'].includes(el.workflowStatusFilter.value)) {
        el.workflowStatusFilter.value = 'all';
      }
      return;
    }
    if (isRepairDefaultsMode()) {
      el.workflowStatusFilter.innerHTML = state.repairDefaultsTab === 'audio'
        ? `
          <option value="all">all</option>
          <option value="weak_english">weak English</option>
          <option value="wrong_default">wrong default</option>
          <option value="queued">queued</option>
        `
        : `
          <option value="all">all</option>
          <option value="forced_english">forced English</option>
          <option value="non_english_audio">non-English audio</option>
          <option value="clear_default">clear default</option>
        `;
      const valid = state.repairDefaultsTab === 'audio'
        ? ['all', 'weak_english', 'wrong_default', 'queued']
        : ['all', 'forced_english', 'non_english_audio', 'clear_default'];
      if (!valid.includes(el.workflowStatusFilter.value)) el.workflowStatusFilter.value = 'all';
    }
  }

  function renderWorkflowActionControls() {
    const repairMode = isRepairDefaultsMode();
    el.repairActionControls.hidden = !repairMode;
    if (!repairMode) {
      el.repairActionSelect.innerHTML = '';
      el.repairActionButton.disabled = true;
      return;
    }
    const selectedCount = selectedRepairPaths().length;
    const audio = state.repairDefaultsTab === 'audio';
    const locked = repairDefaultsSelectionLocked();
    const options = repairActionOptions();
    if (!options.some(option => option.value === state.repairAction)) {
      state.repairAction = defaultRepairAction();
    }
    el.repairActionSelect.innerHTML = options.map(option => (
      `<option value="${escapeHtml(option.value)}">${escapeHtml(option.label)}</option>`
    )).join('');
    el.repairActionSelect.value = state.repairAction;
    el.repairActionButton.classList.add('lab-action-button');
    el.repairActionButton.classList.remove('is-primary', 'is-caution');
    const busy = audio ? state.audioFixBusy : state.subtitleFixBusy;
    el.repairActionButton.classList.add(audio && state.repairAction !== 'set_english_default' ? 'is-caution' : 'is-primary');
    el.repairActionButton.textContent = busy ? (audio ? 'Running Repair Remux' : 'Running Subtitle Remux') : 'Run Repair';
    el.repairActionSelect.disabled = locked || busy;
    el.repairActionButton.disabled = !selectedCount || locked || busy;
  }

  function renderWeakFloorControl() {
    const options = weakFloorDefinitionOptions();
    el.weakFloorSelect.innerHTML = options.map(option => (
      `<option value="${escapeHtml(option.value)}">${escapeHtml(option.label)}</option>`
    )).join('');
    if (!options.some(option => option.value === state.weakFloor)) {
      state.weakFloor = options[0]?.value || 'standard_definition';
    }
    el.weakFloorSelect.value = state.weakFloor;
  }

  function currentHeaders() {
    if (isWeakMode()) return WEAK_HEADERS;
    if (isRepairDefaultsMode()) return state.repairDefaultsTab === 'audio' ? REPAIR_AUDIO_HEADERS : REPAIR_SUBTITLE_HEADERS;
    if (isJunkMode()) return JUNK_HEADERS;
    return NORMALIZE_HEADERS;
  }

  function renderTableHeader() {
    const headers = currentHeaders();
    el.tableColGroup.innerHTML = headers.map(header => {
      const classAttr = header.columnClass ? ` class="${header.columnClass}"` : '';
      const styleAttr = header.width ? ` style="width:${escapeHtml(header.width)}"` : '';
      return `<col${classAttr}${styleAttr}>`;
    }).join('');
    el.tableHeaderRow.innerHTML = headers.map(header => {
      const classAttr = header.columnClass ? ` class="${header.columnClass}"` : '';
      const priorityAttr = header.priority ? ` data-priority="${header.priority}"` : '';
      if (header.key === 'select') return `<th${classAttr}${priorityAttr}></th>`;
      return `<th${classAttr}${priorityAttr}><button class="sort" data-sort="${escapeHtml(header.key)}">${escapeHtml(header.label)}</button></th>`;
    }).join('');
    el.tableHeaderRow.querySelectorAll('.sort').forEach(button => {
      button.addEventListener('click', () => {
        const key = button.dataset.sort;
        if (!key) return;
        state.sort = { key, dir: state.sort.key === key && state.sort.dir === 'asc' ? 'desc' : 'asc' };
        renderRows();
        renderSidePanel();
      });
    });
  }

  function buildReasonBucket(row) {
    const codes = row.reason_codes || [];
    if (codes.some(code => code.includes('collision'))) return 'collision';
    if (codes.some(code => code.includes('artifact'))) return 'artifact';
    if (codes.some(code => code.includes('package'))) return 'package';
    if (codes.some(code => code.includes('subtitle_merge'))) return 'subtitle';
    return codes[0] || (row.confidence === 'unchanged' ? 'unchanged' : 'normalized');
  }

  function linkedChangesForRow(row) {
    const changes = state.normalizePayload?.proposed_changes || [];
    const ids = new Set(row.change_ids || []);
    return changes.filter(change => ids.has(change.item_id));
  }

  function normalizeRows() {
    return (state.normalizePayload?.movie_results || []).map(row => ({
      ...row,
      reason_bucket: buildReasonBucket(row),
      linked_changes: (row.linked_changes || []).length ? row.linked_changes : linkedChangesForRow(row),
    }));
  }

  function isStrictWeakMovie(item) {
    return !!item?.profile?.weak_candidate && !movieHasPackagingOwnedIssue(item);
  }

  function isWeakReviewMovie(item) {
    if (isStrictWeakMovie(item)) return false;
    if (movieHasPackagingOwnedIssue(item)) return false;
    if (item?.profile?.label !== 'needs_review') return false;
    if (!movieHasWeakQualityIssue(item)) return false;
    return movieMeetsWeakFloor(item);
  }

  function weakWorkflowItems() {
    return (state.weakPayload?.movies || []).filter(item => isStrictWeakMovie(item) || isWeakReviewMovie(item));
  }

  function repairAudioItems() {
    return (state.repairPayload?.movies || []).filter(item => !!movieAudioPackagingIssueCode(item));
  }

  function repairSubtitleItems() {
    return (state.repairPayload?.movies || []).filter(item => movieSubtitleReadinessIsRepairable(item));
  }

  function weakRowForItem(item) {
    return {
      row_id: item.path || '',
      path: item.path || '',
      item,
      selectable: isStrictWeakMovie(item),
      current_path: item.path || '',
      issue: movieProfileInlineSummary(item) || humanProfileLabel(item?.profile?.label || ''),
      resolution: item?.facts?.resolution_bucket || '',
      video_bitrate: item?.facts?.video_bitrate_kbps || 0,
      audio_bitrate: item?.facts?.audio_bitrate_kbps || 0,
      channels: item?.facts?.audio_channels || 0,
      audio_summary: item?.facts?.audio_summary || '',
      file_size: item?.facts?.file_size_bytes || 0,
      workflow_status: isWeakReviewMovie(item) ? 'review' : 'delete-candidates',
    };
  }

  function repairAudioRowForItem(item) {
    const issueCode = movieAudioPackagingIssueCode(item);
    return {
      row_id: item.path || '',
      path: item.path || '',
      item,
      selectable: Boolean(item.path) && Boolean(issueCode) && !repairDefaultsSelectionLocked(),
      current_path: item.path || '',
      issue: issueCode === 'default_non_english_audio_with_weak_english' ? 'wrong language · weak English' : 'wrong default language',
      current_default: describeAudioStream(movieDefaultAudioStream(item)),
      repair_target: describeAudioStream(movieBestEnglishAudioStream(item)),
      resolution: item?.facts?.resolution_bucket || '',
      file_size: item?.facts?.file_size_bytes || 0,
      workflow_status: issueCode === 'default_non_english_audio_with_weak_english' ? 'weak_english' : 'wrong_default',
    };
  }

  function repairSubtitleRowForItem(item) {
    return {
      row_id: item.path || '',
      path: item.path || '',
      item,
      selectable: Boolean(item.path) && !repairDefaultsSelectionLocked(),
      current_path: item.path || '',
      issue: humanSubtitleReadinessIssueLabel(movieSubtitleReadinessIssueCode(item)),
      current_default: describeSubtitleStream(movieDefaultSubtitleStream(item)),
      repair_target: describeSubtitleStream(movieSubtitleReadinessRepairTarget(item)) || 'clear defaults',
      resolution: item?.facts?.resolution_bucket || '',
      file_size: item?.facts?.file_size_bytes || 0,
      workflow_status: movieSubtitleReadinessIssueCode(item),
    };
  }

  function junkIssueSummary(item) {
    const labels = [];
    (item?.reasons || []).forEach(reason => {
      const label = JUNK_REASON_LABELS[reason?.code] || '';
      if (label && !labels.includes(label)) labels.push(label);
    });
    return labels.join(', ');
  }

  function junkRowForItem(item) {
    return {
      row_id: item.path || '',
      path: item.path || '',
      item,
      selectable: Boolean(item.path),
      current_path: item.relative_path || item.path || '',
      issue: junkIssueSummary(item) || 'junk candidate',
      reason_codes: (item.reasons || []).map(reason => reason.code || '').filter(Boolean),
      resolution: item?.facts?.resolution_bucket || '',
      video_bitrate: item?.facts?.video_bitrate_kbps || 0,
      audio_bitrate: item?.facts?.audio_bitrate_kbps || 0,
      confidence: item?.confidence || 'review',
      audio_summary: item?.facts?.audio_summary || '',
      file_size: item?.file_size_bytes || 0,
    };
  }

  function activeRows() {
    if (isWeakMode()) return weakWorkflowItems().map(weakRowForItem);
    if (isRepairDefaultsMode()) {
      return state.repairDefaultsTab === 'audio'
        ? repairAudioItems().map(repairAudioRowForItem)
        : repairSubtitleItems().map(repairSubtitleRowForItem);
    }
    if (isJunkMode()) return (state.junkPayload?.junk || []).map(junkRowForItem);
    return normalizeRows();
  }

  function applyFilters() {
    const query = el.searchInput.value.trim().toLowerCase();
    let rows = activeRows();
    if (isWeakMode()) {
      const status = el.workflowStatusFilter.value;
      rows = rows.filter(row => {
        if (status === 'delete-candidates' && row.workflow_status !== 'delete-candidates') return false;
        if (status === 'review' && row.workflow_status !== 'review') return false;
        if (status === 'queued' && row.workflow_status !== 'queued') return false;
        if (query) {
          const haystack = `${row.current_path} ${row.issue} ${row.audio_summary}`.toLowerCase();
          if (!haystack.includes(query)) return false;
        }
        return true;
      });
    } else if (isRepairDefaultsMode()) {
      const status = el.workflowStatusFilter.value;
      rows = rows.filter(row => {
        if (state.repairDefaultsTab === 'audio') {
          if (status === 'weak_english' && row.workflow_status !== 'weak_english') return false;
          if (status === 'wrong_default' && row.workflow_status !== 'wrong_default') return false;
          if (status === 'queued' && row.workflow_status !== 'queued') return false;
        } else {
          if (status === 'forced_english' && !['english_forced_not_default', 'wrong_default_forced_subtitle'].includes(row.workflow_status)) return false;
          if (status === 'non_english_audio' && row.workflow_status !== 'wrong_default_subtitle_language') return false;
          if (status === 'clear_default' && !['unnecessary_default_subtitle', 'multiple_default_subtitles'].includes(row.workflow_status)) return false;
        }
        if (query) {
          const haystack = `${row.current_path} ${row.issue} ${row.current_default} ${row.repair_target}`.toLowerCase();
          if (!haystack.includes(query)) return false;
        }
        return true;
      });
    } else if (isJunkMode()) {
      const status = el.workflowStatusFilter.value;
      rows = rows.filter(row => {
        if (status === 'high' && row.confidence !== 'high') return false;
        if (status === 'review' && row.confidence !== 'review') return false;
        if (query) {
          const haystack = `${row.current_path} ${row.issue} ${(row.reason_codes || []).join(' ')}`.toLowerCase();
          if (!haystack.includes(query)) return false;
        }
        return true;
      });
    } else {
      const bucket = el.bucketFilter.value;
      const caseFilter = el.caseFilter.value;
      const reasonFilter = el.reasonFilter.value;
      const warningFilter = el.warningFilter.value;
      rows = rows.filter(row => {
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
    }
    rows.sort((a, b) => compareRows(a, b, state.sort.key, state.sort.dir));
    state.rows = activeRows();
    state.filteredRows = rows;
  }

  function compareRows(a, b, key, dir) {
    const mult = dir === 'asc' ? 1 : -1;
    if (usesSimpleSelectionShell()) {
      const read = row => {
        if (key === 'video_bitrate' || key === 'audio_bitrate' || key === 'channels' || key === 'file_size') return Number(row[key] || 0);
        return String(row[key] || '').toLowerCase();
      };
      const av = read(a);
      const bv = read(b);
      return av < bv ? -1 * mult : av > bv ? 1 * mult : 0;
    }
    const av = String(a[key] || '').toLowerCase();
    const bv = String(b[key] || '').toLowerCase();
    return av.localeCompare(bv) * mult;
  }

  function renderFilters() {
    if (isWeakMode() || isRepairDefaultsMode() || isJunkMode()) return;
    const rows = normalizeRows();
    const reasonCodes = [...new Set(rows.flatMap(row => row.reason_codes || []))].sort();
    const warningCodes = [...new Set(rows.flatMap(row => row.warning_codes || []))].sort();
    el.reasonFilter.innerHTML = `<option value="">reason code</option>${reasonCodes.map(code => `<option value="${escapeHtml(code)}">${escapeHtml(code)}</option>`).join('')}`;
    el.warningFilter.innerHTML = `<option value="">warning code</option>${warningCodes.map(code => `<option value="${escapeHtml(code)}">${escapeHtml(code)}</option>`).join('')}`;
  }

  function selectedWeakPaths() {
    return state.filteredRows.filter(row => state.selected.has(row.row_id) && row.selectable).map(row => row.path);
  }

  function selectedWeakItems() {
    return state.filteredRows.filter(row => state.selected.has(row.row_id) && row.selectable).map(row => row.item);
  }

  function selectedRepairPaths() {
    return state.filteredRows.filter(row => state.selected.has(row.row_id) && row.selectable).map(row => row.path);
  }

  function selectedRepairItems() {
    return state.filteredRows.filter(row => state.selected.has(row.row_id) && row.selectable).map(row => row.item);
  }

  function selectedJunkPaths() {
    return state.filteredRows.filter(row => state.selected.has(row.row_id) && row.selectable).map(row => row.path);
  }

  function selectedJunkItems() {
    return state.filteredRows.filter(row => state.selected.has(row.row_id) && row.selectable).map(row => row.item);
  }

  function renderSelectionButtons() {
    const selectableRows = usesSimpleSelectionShell() ? state.filteredRows.filter(row => row.selectable) : state.filteredRows;
    const filteredCount = selectableRows.length;
    const selectedVisibleCount = selectableRows.filter(row => state.selected.has(usesSimpleSelectionShell() ? row.row_id : row.result_id)).length;
    el.selectAllButton.disabled = !filteredCount;
    el.deselectAllButton.disabled = !selectedVisibleCount;
    el.selectAllButton.textContent = filteredCount ? `Select all (${filteredCount})` : 'Select all';
    el.deselectAllButton.textContent = selectedVisibleCount ? `Deselect all (${selectedVisibleCount})` : 'Deselect all';
  }

  function selectedProposedChanges() {
    const changesById = new Map((state.normalizePayload?.proposed_changes || []).map(change => [change.item_id, change]));
    const selectedChanges = [];
    const seen = new Set();
    const selectedRows = state.rows.filter(row => state.selected.has(row.result_id));
    state.rows.forEach(row => {
      if (!state.selected.has(row.result_id)) return;
      (row.change_ids || []).forEach(changeId => {
        if (seen.has(changeId)) return;
        const change = changesById.get(changeId);
        if (!change) return;
        seen.add(changeId);
        selectedChanges.push(change);
      });
    });
    (state.normalizePayload?.proposed_changes || []).forEach(change => {
      if (seen.has(change.item_id)) return;
      if (change.change_type !== 'folder_delete' || change.confidence !== 'safe' || !change.current_value) return;
      const folderPrefix = `${change.current_value}/`;
      const relatedRows = state.rows.filter(row => row.actionable && String(row.current_value || '').startsWith(folderPrefix));
      if (!relatedRows.length) return;
      const selectedRelatedCount = relatedRows.filter(row => state.selected.has(row.result_id)).length;
      if (selectedRelatedCount !== relatedRows.length) return;
      if (!selectedRows.some(row => String(row.current_value || '').startsWith(folderPrefix))) return;
      seen.add(change.item_id);
      selectedChanges.push(change);
    });
    return selectedChanges;
  }

  function selectedRows() {
    return state.filteredRows.filter(row => state.selected.has(row.result_id));
  }

  function summarizeNormalizeRows(rows) {
    const operationCounts = {
      total: 0,
      file_move: 0,
      file_rename: 0,
      folder_rename: 0,
      folder_delete: 0,
      folder_merge: 0,
      file_delete: 0,
    };
    const seen = new Set();
    rows.forEach(row => {
      (row.linked_changes || []).forEach(change => {
        if (!change?.item_id || seen.has(change.item_id)) return;
        seen.add(change.item_id);
        operationCounts.total += 1;
        if (Object.hasOwn(operationCounts, change.change_type)) {
          operationCounts[change.change_type] += 1;
        }
      });
    });
    const visibleMutationCount = rows.filter(row => row.projected_path !== row.current_value).length;
    return { operationCounts, visibleMutationCount };
  }

  function renderNormalizeSummaryChips(operationCounts, visibleMutationCount) {
    return [
      `<span class="chip">${operationCounts.total} planned operation${operationCounts.total === 1 ? '' : 's'}</span>`,
      `<span class="chip">${visibleMutationCount} visible path mutation${visibleMutationCount === 1 ? '' : 's'}</span>`,
      operationCounts.file_move ? `<span class="chip">${operationCounts.file_move} file move${operationCounts.file_move === 1 ? '' : 's'}</span>` : '',
      operationCounts.file_rename ? `<span class="chip">${operationCounts.file_rename} file rename${operationCounts.file_rename === 1 ? '' : 's'}</span>` : '',
      operationCounts.folder_rename ? `<span class="chip">${operationCounts.folder_rename} folder rename${operationCounts.folder_rename === 1 ? '' : 's'}</span>` : '',
      operationCounts.folder_delete ? `<span class="chip">${operationCounts.folder_delete} folder delete${operationCounts.folder_delete === 1 ? '' : 's'}</span>` : '',
      operationCounts.folder_merge ? `<span class="chip">${operationCounts.folder_merge} folder merge${operationCounts.folder_merge === 1 ? '' : 's'}</span>` : '',
      operationCounts.file_delete ? `<span class="chip">${operationCounts.file_delete} file delete${operationCounts.file_delete === 1 ? '' : 's'}</span>` : '',
    ].filter(Boolean).join('');
  }

  function renderConfirmButton() {
    if (isWeakMode()) {
      const count = selectedWeakPaths().length;
      el.confirmButton.disabled = count === 0 || state.applyInFlight;
      el.confirmButton.classList.add('is-danger');
      el.confirmButton.textContent = state.applyInFlight ? `Deleting Selected Files (${count})` : `Delete Selected Files (${count})`;
      return;
    }
    if (isRepairDefaultsMode()) {
      if (state.repairDefaultsTab === 'audio') {
        const count = selectedRepairPaths().length;
        el.confirmButton.disabled = count === 0 || state.applyInFlight || repairDefaultsSelectionLocked();
        el.confirmButton.classList.add('is-danger');
        el.confirmButton.textContent = state.applyInFlight ? `Deleting Selected Files (${count})` : `Delete Selected Files (${count})`;
        return;
      }
      el.confirmButton.disabled = true;
      el.confirmButton.classList.remove('is-danger');
      el.confirmButton.textContent = repairDefaultsSelectionLocked()
        ? 'Repair Running'
        : 'This page is non-destructive';
      return;
    }
    if (isJunkMode()) {
      const count = selectedJunkPaths().length;
      el.confirmButton.disabled = count === 0 || state.applyInFlight;
       el.confirmButton.classList.add('is-danger');
      el.confirmButton.textContent = state.applyInFlight ? `Deleting Selected Files (${count})` : `Delete Selected Files (${count})`;
      return;
    }
    el.confirmButton.classList.remove('is-danger');
    const operationCount = selectedProposedChanges().length;
    el.confirmButton.disabled = operationCount === 0 || state.applyInFlight;
    el.confirmButton.textContent = state.applyInFlight
      ? `Confirming (${operationCount} Operations)`
      : `Confirm (${operationCount} Operations)`;
  }

  function renderPanelVisibility() {
    if (!usesDeletePreviewShell()) closeAudioPopover();
    renderShellLayout();
    el.previewPane.hidden = false;
    el.previewControls.hidden = false;
    el.previewScopeSelect.value = state.previewMode;
    renderConfirmButton();
    renderWorkflowActionControls();
  }

  function renderRows() {
    applyFilters();
    renderSelectionButtons();
    if (!state.filteredRows.length) {
      closeAudioPopover();
      const colspan = String(currentHeaders().length);
      el.rowsBody.innerHTML = `<tr><td colspan="${colspan}">No rows for the active filters.</td></tr>`;
      renderConfirmButton();
      renderWorkflowActionControls();
      return;
    }
    el.rowsBody.innerHTML = isWeakMode()
      ? state.filteredRows.map(renderWeakRow).join('')
      : (isRepairDefaultsMode()
        ? state.filteredRows.map(renderRepairRow).join('')
        : (isJunkMode()
          ? state.filteredRows.map(renderJunkRow).join('')
          : state.filteredRows.map(renderNormalizeRow).join('')));
    attachRowHandlers();
    renderJunkFilenameCells();
    renderAudioPopover();
    renderConfirmButton();
    renderWorkflowActionControls();
  }

  function renderNormalizeRow(row) {
    return `
      <tr class="${state.activeRowId === row.result_id ? 'active' : ''}" data-row-id="${escapeHtml(row.result_id)}">
        <td class="lab-cell-select" data-priority="essential"><input type="checkbox" data-row-check="${escapeHtml(row.result_id)}" ${state.selected.has(row.result_id) ? 'checked' : ''}></td>
        <td class="lab-cell-anchor lab-cell-mono" data-priority="essential" title="${escapeHtml(row.current_value)}"><span class="lab-cell-text">${escapeHtml(fileNameFromPath(row.current_value))}</span></td>
        <td class="lab-cell-path lab-cell-mono" data-priority="desktop" title="${escapeHtml(row.projected_path)}"><span class="lab-cell-text">${escapeHtml(row.projected_path)}</span></td>
        <td class="lab-cell-status" data-priority="essential"><span class="lab-cell-pill ${normalizeConfidenceClass(row.confidence)}">${escapeHtml(row.confidence)}</span></td>
        <td class="lab-cell-status" data-priority="medium"><span class="lab-cell-pill">${escapeHtml(row.reason_bucket)}</span></td>
      </tr>
    `;
  }

  function renderWeakRow(row) {
    const checked = state.selected.has(row.row_id) ? 'checked' : '';
    const hasAudioTracks = audioTracksForRow(row).length > 0;
    const audioBitrateMarkup = hasAudioTracks
      ? `<button class="lab-audio-popover-trigger" type="button" data-audio-popover="${escapeHtml(row.row_id)}" aria-expanded="${state.audioPopoverRowId === row.row_id ? 'true' : 'false'}">${escapeHtml(formatBitrate(row.audio_bitrate))}</button>`
      : `<span class="lab-cell-text">${escapeHtml(formatBitrate(row.audio_bitrate))}</span>`;
    return `
      <tr class="${state.activeRowId === row.row_id ? 'active' : ''}" data-row-id="${escapeHtml(row.row_id)}">
        <td class="lab-cell-select" data-priority="essential">${row.selectable ? `<input type="checkbox" data-row-check="${escapeHtml(row.row_id)}" ${checked}>` : ''}</td>
        <td class="lab-cell-anchor lab-cell-mono" data-priority="essential" title="${escapeHtml(row.current_path)}"><span class="lab-cell-text">${escapeHtml(fileNameFromPath(row.current_path))}</span></td>
        <td class="lab-cell-decision" data-priority="essential" title="${escapeHtml(row.issue)}"><span class="lab-cell-text">${escapeHtml(row.issue)}</span></td>
        <td class="lab-cell-supporting" data-priority="medium" title="${escapeHtml(row.resolution || '—')}"><span class="lab-cell-text">${escapeHtml(row.resolution || '—')}</span></td>
        <td class="lab-cell-signal lab-cell-mono" data-priority="essential" title="${escapeHtml(formatBitrate(row.video_bitrate))}"><span class="lab-cell-text">${escapeHtml(formatBitrate(row.video_bitrate))}</span></td>
        <td class="lab-cell-signal lab-cell-mono" data-priority="desktop" title="${escapeHtml(formatBitrate(row.audio_bitrate))}">${audioBitrateMarkup}</td>
        <td class="lab-cell-signal lab-cell-mono" data-priority="medium" title="${row.channels ? escapeHtml(String(row.channels)) : '—'}"><span class="lab-cell-text">${row.channels ? escapeHtml(String(row.channels)) : '—'}</span></td>
        <td class="lab-cell-supporting" data-priority="desktop" title="${escapeHtml(row.audio_summary || '—')}"><span class="lab-cell-text">${escapeHtml(row.audio_summary || '—')}</span></td>
        <td class="lab-cell-signal lab-cell-mono" data-priority="medium" title="${escapeHtml(formatFileSize(row.file_size))}"><span class="lab-cell-text">${escapeHtml(formatFileSize(row.file_size))}</span></td>
      </tr>
    `;
  }

  function junkConfidenceClass(confidence) {
    return confidence === 'high' ? 'is-safe' : 'is-review';
  }

  function renderJunkRow(row) {
    const checked = state.selected.has(row.row_id) ? 'checked' : '';
    const hasAudioTracks = audioTracksForRow(row).length > 0;
    const audioBitrateMarkup = hasAudioTracks
      ? `<button class="lab-audio-popover-trigger" type="button" data-audio-popover="${escapeHtml(row.row_id)}" aria-expanded="${state.audioPopoverRowId === row.row_id ? 'true' : 'false'}">${escapeHtml(formatBitrate(row.audio_bitrate))}</button>`
      : `<span class="lab-cell-text">${escapeHtml(formatBitrate(row.audio_bitrate))}</span>`;
    return `
      <tr class="${state.activeRowId === row.row_id ? 'active' : ''}" data-row-id="${escapeHtml(row.row_id)}">
        <td class="lab-cell-select" data-priority="essential">${row.selectable ? `<input type="checkbox" data-row-check="${escapeHtml(row.row_id)}" ${checked}>` : ''}</td>
        <td class="lab-cell-anchor lab-cell-mono" data-priority="essential" title="${escapeHtml(row.current_path)}" data-junk-filename-cell>
          <span class="lab-cell-text" data-junk-filename-full="${escapeHtml(fileNameFromPath(row.current_path))}">${escapeHtml(fileNameFromPath(row.current_path))}</span>
        </td>
        <td class="lab-cell-decision" data-priority="essential" title="${escapeHtml(row.issue)}"><span class="lab-cell-text">${escapeHtml(row.issue)}</span></td>
        <td class="lab-cell-supporting" data-priority="medium" title="${escapeHtml(row.resolution || '—')}"><span class="lab-cell-text">${escapeHtml(row.resolution || '—')}</span></td>
        <td class="lab-cell-signal lab-cell-mono" data-priority="essential" title="${escapeHtml(formatBitrate(row.video_bitrate))}"><span class="lab-cell-text">${escapeHtml(formatBitrate(row.video_bitrate))}</span></td>
        <td class="lab-cell-signal lab-cell-mono" data-priority="desktop" title="${escapeHtml(formatBitrate(row.audio_bitrate))}">${audioBitrateMarkup}</td>
        <td class="lab-cell-signal" data-priority="medium" title="${escapeHtml(row.confidence)}"><span class="lab-cell-pill ${junkConfidenceClass(row.confidence)}">${escapeHtml(row.confidence)}</span></td>
        <td class="lab-cell-supporting" data-priority="desktop" title="${escapeHtml(row.audio_summary || '—')}"><span class="lab-cell-text">${escapeHtml(row.audio_summary || '—')}</span></td>
        <td class="lab-cell-signal lab-cell-mono" data-priority="medium" title="${escapeHtml(formatFileSize(row.file_size))}"><span class="lab-cell-text">${escapeHtml(formatFileSize(row.file_size))}</span></td>
      </tr>
    `;
  }

  function repairStatusClass(row) {
    if (state.repairDefaultsTab === 'audio') {
      return row.workflow_status === 'queued' ? 'is-unchanged' : (row.workflow_status === 'weak_english' ? 'is-review' : 'is-actionable');
    }
    return 'is-actionable';
  }

  function renderRepairRow(row) {
    const checked = state.selected.has(row.row_id) ? 'checked' : '';
    const disabled = repairDefaultsSelectionLocked() ? 'disabled' : '';
    return `
      <tr class="${state.activeRowId === row.row_id ? 'active' : ''}" data-row-id="${escapeHtml(row.row_id)}">
        <td class="lab-cell-select" data-priority="essential">${row.selectable ? `<input type="checkbox" data-row-check="${escapeHtml(row.row_id)}" ${checked} ${disabled}>` : ''}</td>
        <td class="lab-cell-anchor lab-cell-mono" data-priority="essential" title="${escapeHtml(row.current_path)}"><span class="lab-cell-text">${escapeHtml(fileNameFromPath(row.current_path))}</span></td>
        <td class="lab-cell-decision" data-priority="essential" title="${escapeHtml(row.issue)}"><span class="lab-cell-text">${escapeHtml(row.issue)}</span></td>
        <td class="lab-cell-supporting" data-priority="medium" title="${escapeHtml(row.current_default || '—')}"><span class="lab-cell-text">${escapeHtml(row.current_default || '—')}</span></td>
        <td class="lab-cell-supporting" data-priority="desktop" title="${escapeHtml(row.repair_target || '—')}"><span class="lab-cell-text">${escapeHtml(row.repair_target || '—')}</span></td>
        <td class="lab-cell-signal" data-priority="medium" title="${escapeHtml(row.resolution || '—')}"><span class="lab-cell-pill ${repairStatusClass(row)}">${escapeHtml(row.resolution || '—')}</span></td>
        <td class="lab-cell-signal lab-cell-mono" data-priority="medium" title="${escapeHtml(formatFileSize(row.file_size))}"><span class="lab-cell-text">${escapeHtml(formatFileSize(row.file_size))}</span></td>
      </tr>
    `;
  }

  function junkFilenameMeasureCanvas() {
    if (!junkFilenameMeasureCanvas.canvas) {
      junkFilenameMeasureCanvas.canvas = document.createElement('canvas');
      junkFilenameMeasureCanvas.context = junkFilenameMeasureCanvas.canvas.getContext('2d');
    }
    return junkFilenameMeasureCanvas.context;
  }

  function middleTruncateJunkFileName(value, maxWidth, font) {
    const text = String(value || '');
    if (!text || !maxWidth || maxWidth <= 0) return text;
    const context = junkFilenameMeasureCanvas();
    if (!context) return text;
    context.font = font;
    if (context.measureText(text).width <= maxWidth) return text;
    const omission = '[...]';
    const extensionIndex = text.lastIndexOf('.');
    const suffixFloor = Math.min(text.length - 1, Math.max(extensionIndex >= 0 ? text.length - extensionIndex + 6 : 10, 8));
    const prefixFloor = Math.min(8, Math.max(4, text.length - suffixFloor - 1));
    let prefix = Math.min(24, Math.max(prefixFloor, text.length - suffixFloor - 1));
    let suffix = Math.min(Math.max(suffixFloor, 8), text.length - prefixFloor - 1);
    let compact = `${text.slice(0, prefix)}${omission}${text.slice(-suffix)}`;
    while (context.measureText(compact).width > maxWidth && (prefix > prefixFloor || suffix > suffixFloor)) {
      if (prefix > prefixFloor && (prefix >= suffix || suffix <= suffixFloor)) prefix -= 1;
      else if (suffix > suffixFloor) suffix -= 1;
      compact = `${text.slice(0, prefix)}${omission}${text.slice(-suffix)}`;
    }
    while (context.measureText(compact).width > maxWidth && prefix > 4) {
      prefix -= 1;
      compact = `${text.slice(0, prefix)}${omission}${text.slice(-suffix)}`;
    }
    return compact;
  }

  function applyJunkFilenameCompaction(cell) {
    const label = cell?.querySelector('[data-junk-filename-full]');
    if (!(label instanceof HTMLElement)) return;
    const full = label.dataset.junkFilenameFull || label.textContent || '';
    label.title = full;
    if (!isJunkMode()) {
      label.textContent = full;
      return;
    }
    const style = window.getComputedStyle(label);
    const compact = middleTruncateJunkFileName(full, label.clientWidth || cell.clientWidth || 0, style.font);
    label.textContent = compact || full;
  }

  function renderJunkFilenameCells() {
    if (!isJunkMode()) return;
    el.rowsBody.querySelectorAll('[data-junk-filename-cell]').forEach(cell => applyJunkFilenameCompaction(cell));
    ensureJunkFilenameResizeObserver();
  }

  function ensureJunkFilenameResizeObserver() {
    if (!isJunkMode() || state.junkFilenameResizeObserver) return;
    state.junkFilenameResizeObserver = new ResizeObserver(() => {
      if (state.junkFilenameResizeFrame) window.cancelAnimationFrame(state.junkFilenameResizeFrame);
      state.junkFilenameResizeFrame = window.requestAnimationFrame(() => {
        state.junkFilenameResizeFrame = 0;
        renderJunkFilenameCells();
      });
    });
    state.junkFilenameResizeObserver.observe(el.rowsBody);
  }

  function normalizeConfidenceClass(confidence) {
    if (confidence === 'safe') return 'is-safe';
    if (confidence === 'review') return 'is-review';
    if (confidence === 'unchanged') return 'is-unchanged';
    return 'is-actionable';
  }

  function clearDeletePreviewState() {
    state.weakPreview = null;
    state.weakPreviewKey = '';
    state.junkDeleteSkipped = [];
  }

  function refreshSelectionState() {
    renderSelectionButtons();
    renderConfirmButton();
    renderWorkflowActionControls();
    renderSidePanel();
  }

  function attachRowHandlers() {
    el.rowsBody.querySelectorAll('tr[data-row-id]').forEach(rowEl => {
      rowEl.addEventListener('click', event => {
        if (event.target instanceof HTMLInputElement) return;
        state.activeRowId = rowEl.dataset.rowId || '';
        renderSidePanel();
      });
    });
    el.rowsBody.querySelectorAll('input[data-row-check]').forEach(input => {
      input.addEventListener('change', () => {
        if (isRepairDefaultsMode() && repairDefaultsSelectionLocked()) {
          input.checked = state.selected.has(input.dataset.rowCheck || '');
          return;
        }
        const id = input.dataset.rowCheck || '';
        if (input.checked) state.selected.add(id);
        else state.selected.delete(id);
        state.activeRowId = id;
        clearDeletePreviewState();
        refreshSelectionState();
      });
    });
    el.rowsBody.querySelectorAll('button[data-audio-popover]').forEach(button => {
      button.addEventListener('click', event => {
        event.stopPropagation();
        const rowId = button.dataset.audioPopover || '';
        if (!rowId) return;
        state.audioPopoverRowId = state.audioPopoverRowId === rowId ? '' : rowId;
        renderAudioPopover();
      });
    });
  }

  function renderAudioPopover() {
    const popover = el.audioTrackPopover;
    if (!popover) return;
    const row = rowById(state.audioPopoverRowId);
    const anchor = state.audioPopoverRowId
      ? el.rowsBody.querySelector(`button[data-audio-popover="${CSS.escape(state.audioPopoverRowId)}"]`)
      : null;
    const tracks = audioTracksForRow(row);
    if (!usesDeletePreviewShell() || !row || !anchor || !tracks.length) {
      closeAudioPopover();
      return;
    }
    popover.innerHTML = `
      <div class="lab-audio-popover-title">Audio Tracks</div>
      <ul class="lab-audio-popover-list">
        ${tracks.map(track => `
          <li class="lab-audio-popover-row">
            <span class="lab-audio-popover-lang">${escapeHtml(displayAudioLanguage(track.language))}</span>
            <span class="lab-audio-popover-facts">${escapeHtml(`${formatBitrate(track.bitrate_kbps)} · ${audioChannelLayout(track.channels)}`)}</span>
            ${track.is_default ? '<span class="lab-audio-popover-default">default</span>' : ''}
          </li>
        `).join('')}
      </ul>
    `;
    popover.hidden = false;
    positionAudioPopover(anchor, popover);
    el.rowsBody.querySelectorAll('button[data-audio-popover]').forEach(button => {
      button.setAttribute('aria-expanded', button.dataset.audioPopover === state.audioPopoverRowId ? 'true' : 'false');
    });
  }

  function positionAudioPopover(anchor, popover) {
    const anchorRect = anchor.getBoundingClientRect();
    const popoverRect = popover.getBoundingClientRect();
    const margin = 12;
    let left = anchorRect.right;
    let top = anchorRect.top - popoverRect.height;
    left = Math.min(left, window.innerWidth - popoverRect.width - margin);
    left = Math.max(margin, left);
    if (top < margin) top = Math.min(anchorRect.bottom + 14, window.innerHeight - popoverRect.height - margin);
    popover.style.left = `${left}px`;
    popover.style.top = `${Math.max(margin, top)}px`;
  }

  function closeAudioPopover() {
    state.audioPopoverRowId = '';
    if (!el.audioTrackPopover) return;
    el.audioTrackPopover.hidden = true;
    el.audioTrackPopover.innerHTML = '';
    el.rowsBody.querySelectorAll('button[data-audio-popover]').forEach(button => {
      button.setAttribute('aria-expanded', 'false');
    });
  }

  function rowById(rowId) {
    const key = usesSimpleSelectionShell() ? 'row_id' : 'result_id';
    return state.rows.find(item => item[key] === rowId) || state.filteredRows.find(item => item[key] === rowId) || null;
  }

  function flattenPreviewTree(node, lines, depth) {
    Object.keys(node).filter(key => !key.startsWith('_')).sort((a, b) => a.localeCompare(b)).forEach(key => {
      const entry = node[key];
      lines.push({
        label: `${key}/`,
        depth,
        mutated: Boolean(entry._mutated),
        selected: Boolean(entry._selected),
        deleted: Boolean(entry._deleted),
        cleanup: Boolean(entry._cleanup),
      });
      flattenPreviewTree(entry, lines, depth + 1);
    });
    (node._files || []).sort((a, b) => a.name.localeCompare(b.name)).forEach(file => {
      lines.push({
        label: file.name,
        depth,
        mutated: Boolean(file.mutated),
        selected: Boolean(file.selected),
        deleted: Boolean(file.deleted),
        cleanup: Boolean(file.cleanup),
      });
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
    return renderPreviewTreeMarkup(tree);
  }

  function addPathToTree(tree, path, flags) {
    const parts = String(path || '').split('/').filter(Boolean);
    if (!parts.length) return;
    let node = tree;
    parts.forEach((part, index) => {
      const isFile = index === parts.length - 1;
      if (isFile) {
        if (!node._files) node._files = [];
        node._files.push({ name: part, ...flags });
        return;
      }
      node[part] = node[part] || {};
      if (flags.deleted) node[part]._deleted = true;
      if (flags.cleanup) node[part]._cleanup = true;
      if (flags.selected) node[part]._selected = true;
      node = node[part];
    });
  }

  function renderPreviewTreeMarkup(tree) {
    const lines = [];
    flattenPreviewTree(tree, lines, 0);
    return `
      <div class="lab-tree">
        ${lines.map(line => `
          <div class="lab-tree-line lab-indent-${Math.min(line.depth, 5)} ${line.mutated ? 'is-mutated' : ''} ${line.selected ? 'is-selected' : ''} ${line.deleted ? 'is-deleted' : ''} ${line.cleanup ? 'is-cleanup' : ''}">
            ${escapeHtml(line.label)}
          </div>
        `).join('')}
      </div>
    `;
  }

  function renderSelectedPreview() {
    const rows = selectedRows();
    if (!state.normalizePayload) {
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
    const { operationCounts, visibleMutationCount } = summarizeNormalizeRows(rows);
    el.previewPane.innerHTML = `
      <div class="lab-preview-summary">
        <strong>${visibleMutationCount}</strong> mutated media file${visibleMutationCount === 1 ? '' : 's'}.
        ${renderNormalizeSummaryChips(operationCounts, visibleMutationCount)}
      </div>
      ${buildPreviewTree(rows)}
    `;
  }

  function renderLibraryPreview() {
    if (!state.normalizePayload) {
      el.previewPane.textContent = 'Run normalize to inspect projected output.';
      return;
    }
    const rows = state.filteredRows;
    if (!rows.length) {
      el.previewPane.textContent = 'No rows match the current filters.';
      return;
    }
    const { operationCounts, visibleMutationCount } = summarizeNormalizeRows(rows);
    el.previewPane.innerHTML = `
      <div class="lab-preview-summary">
        <strong>${visibleMutationCount}</strong> mutated media file${visibleMutationCount === 1 ? '' : 's'}.
        ${renderNormalizeSummaryChips(operationCounts, visibleMutationCount)}
      </div>
      ${buildPreviewTree(rows)}
    `;
  }

  function weakSelectedPreviewTree(preview) {
    const tree = {};
    (preview.deleted || []).forEach(path => addPathToTree(tree, relativeToSource(path), { deleted: true, selected: true }));
    (preview.cleaned_sidecars || []).forEach(path => addPathToTree(tree, relativeToSource(path), { cleanup: true, selected: true }));
    (preview.removed_folders || []).forEach(path => addPathToTree(tree, relativeToSource(path), { cleanup: true, selected: true }));
    return renderPreviewTreeMarkup(tree);
  }

  function weakLibraryPreviewTree(preview) {
    const tree = {};
    const deleted = new Set((preview.deleted || []).map(path => relativeToSource(path)));
    const movies = weakWorkflowItems();
    movies.forEach(item => {
      const relPath = relativeToSource(item.path || '');
      if (!relPath || deleted.has(relPath)) return;
      addPathToTree(tree, relPath, {});
    });
    (preview.deleted || []).forEach(path => addPathToTree(tree, relativeToSource(path), { deleted: true, selected: true }));
    (preview.cleaned_sidecars || []).forEach(path => addPathToTree(tree, relativeToSource(path), { cleanup: true, selected: true }));
    (preview.removed_folders || []).forEach(path => addPathToTree(tree, relativeToSource(path), { cleanup: true, selected: true }));
    return renderPreviewTreeMarkup(tree);
  }

  function relativeToSource(path) {
    const source = String(el.sourcePath.value || '').replace(/\/+$/, '');
    const raw = String(path || '');
    if (!source || !raw.startsWith(source + '/')) return raw;
    return raw.slice(source.length + 1);
  }

  async function ensureWeakPreview() {
    const source = el.sourcePath.value.trim();
    const paths = selectedWeakPaths();
    const key = `${source}\n${paths.join('\n')}`;
    if (!source) return { deleted: [], cleaned_sidecars: [], removed_folders: [], skipped: [] };
    if (!paths.length) return { deleted: [], cleaned_sidecars: [], removed_folders: [], skipped: [] };
    if (state.weakPreview && state.weakPreviewKey === key) return state.weakPreview;
    state.weakPreviewLoading = true;
    renderPreviewPane();
    const response = await fetch('/api/movies/delete-preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source, paths }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'delete preview failed');
    state.weakPreview = payload;
    state.weakPreviewKey = key;
    state.weakPreviewLoading = false;
    return payload;
  }

  function renderWeakPreviewPane() {
    const selectedCount = selectedWeakPaths().length;
    if (!state.weakPayload) {
      el.previewPane.textContent = 'Run weak encodes to inspect delete preview.';
      return;
    }
    if (!selectedCount) {
      el.previewPane.innerHTML = `
        <div class="lab-preview-empty">
          <strong>No rows selected.</strong>
          <div>Select strict weak rows to preview deleted media files, cleaned sidecars, and removed folders.</div>
        </div>
      `;
      return;
    }
    if (state.weakPreviewLoading) {
      el.previewPane.innerHTML = '<div class="lab-preview-empty"><strong>Loading delete preview.</strong></div>';
      return;
    }
    const preview = state.weakPreview || { deleted: [], cleaned_sidecars: [], removed_folders: [], skipped: [] };
    const tree = state.previewMode === 'library' ? weakLibraryPreviewTree(preview) : weakSelectedPreviewTree(preview);
    el.previewPane.innerHTML = `
      <div class="lab-preview-summary">
        <strong>${preview.deleted.length}</strong> deleted media file${preview.deleted.length === 1 ? '' : 's'}.
        <span class="chip delete">${preview.cleaned_sidecars.length} cleaned sidecar${preview.cleaned_sidecars.length === 1 ? '' : 's'}</span>
        <span class="chip">${preview.removed_folders.length} removed folder${preview.removed_folders.length === 1 ? '' : 's'}</span>
      </div>
      ${tree}
      ${preview.skipped.length ? `<div class="lab-preview-summary">Skipped: ${escapeHtml(preview.skipped.map(item => `${item.path || ''} ${item.reason || ''}`.trim()).join(' | '))}</div>` : ''}
    `;
  }

  function junkSelectedPreviewTree(rows) {
    const tree = {};
    rows.forEach(row => addPathToTree(tree, row.item?.relative_path || row.current_path || '', { deleted: true, selected: true }));
    return renderPreviewTreeMarkup(tree);
  }

  function junkLibraryPreviewTree(rows) {
    const tree = {};
    rows.forEach(row => addPathToTree(tree, row.item?.relative_path || row.current_path || '', { deleted: true }));
    return renderPreviewTreeMarkup(tree);
  }

  function renderJunkPreviewPane() {
    const selected = selectedJunkItems();
    if (!state.junkPayload) {
      el.previewPane.textContent = 'Run Delete Junk & Spam Files to inspect delete preview.';
      return;
    }
    if (state.previewMode === 'selected' && !selected.length) {
      el.previewPane.innerHTML = `
        <div class="lab-preview-empty">
          <strong>No rows selected.</strong>
          <div>Select junk candidates to preview files marked as deleted.</div>
        </div>
      `;
      return;
    }
    const previewRows = state.previewMode === 'library'
      ? state.filteredRows
      : state.filteredRows.filter(row => state.selected.has(row.row_id));
    const tree = state.previewMode === 'library' ? junkLibraryPreviewTree(previewRows) : junkSelectedPreviewTree(previewRows);
    const label = state.previewMode === 'library' ? 'currently filtered junk candidate' : 'selected junk file';
    el.previewPane.innerHTML = `
      <div class="lab-preview-summary">
        <strong>${previewRows.length}</strong> ${label}${previewRows.length === 1 ? '' : 's'} marked as deleted.
        ${state.junkDeleteSkipped.length ? `<span class="chip">${state.junkDeleteSkipped.length} skipped on last delete</span>` : ''}
      </div>
      ${tree}
      ${state.junkDeleteSkipped.length ? `<div class="lab-preview-summary">Skipped: ${escapeHtml(state.junkDeleteSkipped.map(item => `${relativeToSource(item.path || '')} ${item.reason || ''}`.trim()).join(' | '))}</div>` : ''}
    `;
  }

  function buildRepairPreviewList(rows, formatBody) {
    if (!rows.length) return '<div class="lab-preview-empty"><strong>No visible items.</strong></div>';
    return `
      <div class="lab-preview-list">
        ${rows.map(row => `
          <div class="lab-preview-item">
            <div class="lab-preview-item-title">${escapeHtml(fileNameFromPath(row.current_path || row.path || ''))}</div>
            <div class="lab-preview-item-body">${escapeHtml(formatBody(row))}</div>
          </div>
        `).join('')}
      </div>
    `;
  }

  function renderRepairPreviewPane() {
    if (!state.repairPayload) {
      el.previewPane.textContent = 'Run Repair Defaults to inspect repair consequences.';
      return;
    }
    const previewRows = state.previewMode === 'library'
      ? state.filteredRows
      : state.filteredRows.filter(row => state.selected.has(row.row_id));
    if (!previewRows.length) {
      el.previewPane.innerHTML = `
        <div class="lab-preview-empty">
          <strong>No rows selected.</strong>
          <div>${state.repairDefaultsTab === 'audio'
            ? 'Select audio-packaging issues to preview remux and delete consequences.'
            : 'Select subtitle-default issues to preview non-destructive repair consequences.'}</div>
        </div>
      `;
      return;
    }
    const summary = state.repairDefaultsTab === 'audio'
      ? `${previewRows.length} ${state.previewMode === 'library' ? 'visible audio-packaging title' : 'selected audio-packaging title'}${previewRows.length === 1 ? '' : 's'} ready for repair or delete.`
      : `${previewRows.length} ${state.previewMode === 'library' ? 'visible subtitle issue' : 'selected subtitle issue'}${previewRows.length === 1 ? '' : 's'} staged for non-destructive repair.`;
    const body = state.repairDefaultsTab === 'audio'
      ? buildRepairPreviewList(previewRows, row => `${row.current_default} -> ${row.repair_target}${row.workflow_status === 'queued' ? ' · queued for replacement' : ''}`)
      : buildRepairPreviewList(previewRows, row => `${row.current_default} -> ${row.repair_target}`);
    el.previewPane.innerHTML = `
      <div class="lab-preview-summary">
        <strong>${summary}</strong>
        ${state.repairActionNotice ? `<span class="chip">${escapeHtml(state.repairActionNotice)}</span>` : ''}
      </div>
      ${body}
    `;
  }

  function renderPreviewPane() {
    if (isWeakMode()) {
      renderWeakPreviewPane();
      return;
    }
    if (isRepairDefaultsMode()) {
      renderRepairPreviewPane();
      return;
    }
    if (isJunkMode()) {
      renderJunkPreviewPane();
      return;
    }
    if (state.previewMode === 'library') renderLibraryPreview();
    else renderSelectedPreview();
  }

  function renderSidePanel() {
    renderPanelVisibility();
    renderPreviewPane();
  }

  async function runNormalize() {
    const response = await fetch('/api/movies/normalize', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source: el.sourcePath.value }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'normalize failed');
    state.normalizePayload = payload;
    state.selected = new Set();
    state.activeRowId = '';
    state.previewMode = 'selected';
    renderFilters();
    renderRows();
    renderSidePanel();
  }

  async function runWeakEncodes() {
    const response = await fetch('/api/movies/profile', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source: el.sourcePath.value, weak_floor: state.weakFloor }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'weak encodes failed');
    state.weakPayload = payload;
    state.weakFloor = payload?.replacement_candidate_definition?.fields?.[0]?.value || state.weakFloor;
    state.selected = new Set();
    state.activeRowId = '';
    state.previewMode = 'selected';
    clearDeletePreviewState();
    renderWeakFloorControl();
    renderRows();
    renderSidePanel();
  }

  async function runRepairDefaults() {
    const response = await fetch('/api/movies/profile', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source: el.sourcePath.value }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'repair defaults failed');
    state.repairPayload = payload;
    state.selected = new Set();
    state.activeRowId = '';
    state.previewMode = 'selected';
    state.repairActionNotice = '';
    clearDeletePreviewState();
    renderRows();
    renderSidePanel();
  }

  async function runJunk() {
    const response = await fetch('/api/movies/junk', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source: el.sourcePath.value }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'junk scan failed');
    state.junkPayload = payload;
    state.selected = new Set();
    state.activeRowId = '';
    state.previewMode = 'selected';
    clearDeletePreviewState();
    renderRows();
    renderSidePanel();
  }

  async function runActiveWorkflow() {
    state.runInFlight = true;
    renderRunButton();
    try {
      if (isWeakMode()) await runWeakEncodes();
      else if (isRepairDefaultsMode()) await runRepairDefaults();
      else if (isJunkMode()) await runJunk();
      else await runNormalize();
    } finally {
      state.runInFlight = false;
      renderRunButton();
    }
  }

  function removeWeakDeletedItems(payload, deletedPaths) {
    if (!payload) return payload;
    const deleted = new Set(deletedPaths);
    return {
      ...payload,
      movies: (payload.movies || []).filter(item => !deleted.has(item.path || '')),
    };
  }

  function removeJunkDeletedItems(payload, deletedPaths) {
    if (!payload) return payload;
    const deleted = new Set(deletedPaths);
    return {
      ...payload,
      junk: (payload.junk || []).filter(item => !deleted.has(item.path || '')),
    };
  }

  function mergeUpdatedProfileItems(payload, updatedItems, options = {}) {
    if (!payload) return payload;
    const byPath = new Map((updatedItems || []).map(item => [item.path || '', item]));
    const dropResolved = !!options.dropResolved;
    return {
      ...payload,
      movies: (payload.movies || []).map(item => byPath.get(item.path || '') || item).filter(item => {
        if (!dropResolved || !byPath.has(item.path || '')) return true;
        if (state.repairDefaultsTab === 'audio') return !!movieAudioPackagingIssueCode(item);
        return movieSubtitleReadinessIsRepairable(item);
      }),
    };
  }

  async function deleteSelectedRepairAudio() {
    const items = selectedRepairItems();
    if (!items.length) return;
    state.applyInFlight = true;
    renderConfirmButton();
    try {
      const source = el.sourcePath.value.trim();
      const paths = items.map(item => item.path).filter(Boolean);
      const delResponse = await fetch('/api/movies/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source, paths }),
      });
      const delPayload = await delResponse.json();
      if (!delResponse.ok) throw new Error(delPayload.error || 'delete failed');
      state.repairPayload = removeWeakDeletedItems(state.repairPayload, delPayload.deleted || []);
      state.selected = new Set();
      state.activeRowId = '';
      state.previewMode = 'selected';
      state.repairActionNotice = `Deleted ${delPayload.deleted?.length || 0} file${(delPayload.deleted?.length || 0) === 1 ? '' : 's'}.`;
      clearDeletePreviewState();
      renderRows();
      renderSidePanel();
    } finally {
      state.applyInFlight = false;
      renderConfirmButton();
    }
  }

  async function fixSelectedAudioDefaults(dropForeignAudio) {
    const paths = selectedRepairPaths();
    if (!paths.length) return;
    state.audioFixBusy = true;
    const action = state.repairAction;
    state.repairActionNotice = action === 'drop_foreign_passenger_audio'
      ? `Running foreign-audio prune for ${paths.length} file${paths.length === 1 ? '' : 's'}.`
      : (dropForeignAudio
        ? `Running English-default remux and foreign-audio prune for ${paths.length} file${paths.length === 1 ? '' : 's'}.`
        : `Running English-default remux for ${paths.length} file${paths.length === 1 ? '' : 's'}.`);
    renderRows();
    renderSidePanel();
    try {
      const response = await fetch('/api/movies/audio-packaging/fix', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source: el.sourcePath.value.trim(), paths, drop_foreign_audio: dropForeignAudio }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || 'audio packaging fix failed');
      state.repairPayload = mergeUpdatedProfileItems(state.repairPayload, payload.updated_items || [], { dropResolved: true });
      state.selected = new Set();
      state.activeRowId = '';
      state.previewMode = 'selected';
      state.repairActionNotice = action === 'drop_foreign_passenger_audio'
        ? `${payload.fixed?.length || 0} foreign-audio prune${(payload.fixed?.length || 0) === 1 ? '' : 's'} completed.`
        : `${payload.fixed?.length || 0} audio default${(payload.fixed?.length || 0) === 1 ? '' : 's'} repaired.`;
      renderRows();
      renderSidePanel();
    } catch (error) {
      state.repairActionNotice = error.message;
      renderRows();
      renderSidePanel();
      throw error;
    } finally {
      state.audioFixBusy = false;
      renderRows();
      renderSidePanel();
    }
  }

  async function fixSelectedSubtitleDefaults() {
    const rows = state.filteredRows.filter(row => state.selected.has(row.row_id) && row.selectable);
    const paths = rows.map(row => row.path);
    if (!paths.length) return;
    const issueCodes = Object.fromEntries(rows.map(row => [row.path, row.workflow_status]));
    state.subtitleFixBusy = true;
    state.repairActionNotice = `Running subtitle-default remux for ${paths.length} file${paths.length === 1 ? '' : 's'}.`;
    renderRows();
    renderSidePanel();
    try {
      const response = await fetch('/api/movies/subtitle-readiness/fix', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source: el.sourcePath.value.trim(), paths, issue_codes: issueCodes }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || 'subtitle readiness fix failed');
      state.repairPayload = mergeUpdatedProfileItems(state.repairPayload, payload.updated_items || [], { dropResolved: true });
      state.selected = new Set();
      state.activeRowId = '';
      state.previewMode = 'selected';
      state.repairActionNotice = `${payload.fixed?.length || 0} subtitle default${(payload.fixed?.length || 0) === 1 ? '' : 's'} repaired.`;
      renderRows();
      renderSidePanel();
    } catch (error) {
      state.repairActionNotice = error.message;
      renderRows();
      renderSidePanel();
      throw error;
    } finally {
      state.subtitleFixBusy = false;
      renderRows();
      renderSidePanel();
    }
  }

  async function confirmSelected() {
    if (isWeakMode()) {
      const items = selectedWeakItems();
      if (!items.length) return;
      state.applyInFlight = true;
      renderConfirmButton();
      try {
        const source = el.sourcePath.value.trim();
        const paths = items.map(item => item.path).filter(Boolean);
        const delResponse = await fetch('/api/movies/delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ source, paths }),
        });
        const delPayload = await delResponse.json();
        if (!delResponse.ok) throw new Error(delPayload.error || 'delete failed');
        state.weakPayload = removeWeakDeletedItems(state.weakPayload, delPayload.deleted || []);
        state.selected = new Set();
        clearDeletePreviewState();
        state.activeRowId = '';
        state.previewMode = 'selected';
        renderRows();
        renderSidePanel();
      } finally {
        state.applyInFlight = false;
        renderConfirmButton();
      }
      return;
    }
    if (isRepairDefaultsMode()) {
      if (state.repairDefaultsTab === 'subtitle') return;
      await deleteSelectedRepairAudio();
      return;
    }
    if (isJunkMode()) {
      const items = selectedJunkItems();
      if (!items.length) return;
      state.applyInFlight = true;
      renderConfirmButton();
      try {
        const source = el.sourcePath.value.trim();
        const paths = items.map(item => item.path).filter(Boolean);
        const response = await fetch('/api/movies/junk/delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ source, paths }),
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || 'junk delete failed');
        state.junkPayload = removeJunkDeletedItems(state.junkPayload, payload.deleted || []);
        state.selected = new Set();
        state.activeRowId = '';
        state.previewMode = 'selected';
        state.junkDeleteSkipped = payload.skipped || [];
        renderRows();
        renderSidePanel();
      } finally {
        state.applyInFlight = false;
        renderConfirmButton();
      }
      return;
    }
    const changes = selectedProposedChanges();
    if (!changes.length) return;
    state.applyInFlight = true;
    renderConfirmButton();
    try {
      const response = await fetch('/api/movies/apply', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source: el.sourcePath.value, changes }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || 'confirm failed');
      state.normalizePayload = payload.remaining_plan || null;
      state.selected = new Set();
      state.activeRowId = '';
      state.previewMode = 'selected';
      renderFilters();
      renderRows();
      if (!state.normalizePayload) {
        el.previewPane.innerHTML = `
          <div class="lab-preview-empty">
            <strong>No remaining normalize changes.</strong>
            <div>Run normalize again to refresh the library view.</div>
          </div>
        `;
        renderPanelVisibility();
        return;
      }
      renderSidePanel();
    } finally {
      state.applyInFlight = false;
      renderConfirmButton();
    }
  }

  function setWorkflow(workflow) {
    state.workflow = ['weak-encodes', 'repair-defaults', 'junk'].includes(workflow) ? workflow : 'normalize';
    state.layoutMode = LAYOUT_MODES.default;
    state.selected = new Set();
    state.activeRowId = '';
    state.previewMode = 'selected';
    state.repairDefaultsTab = 'audio';
    state.repairAction = defaultRepairAction();
    state.repairActionNotice = '';
    state.sort = usesSimpleSelectionShell() ? { key: 'current_path', dir: 'asc' } : { key: 'current_value', dir: 'asc' };
    clearDeletePreviewState();
    closeAudioPopover();
    syncWorkflowUrl();
    renderWorkflowHeader();
    renderFilterVisibility();
    renderRunButton();
    renderTableHeader();
    renderFilters();
    renderRows();
    renderSidePanel();
  }

  el.workflowButton.addEventListener('click', () => {
    const open = el.workflowMenu.hidden;
    el.workflowMenu.hidden = !open;
    el.workflowButton.setAttribute('aria-expanded', open ? 'true' : 'false');
  });

  [el.workflowNormalize, el.workflowWeakEncodes, el.workflowRepairDefaults, el.workflowJunk].forEach(button => {
    button.addEventListener('click', async () => {
      el.workflowMenu.hidden = true;
      el.workflowButton.setAttribute('aria-expanded', 'false');
      setWorkflow(button.dataset.workflow || 'normalize');
    });
  });

  document.addEventListener('click', event => {
    if (!(event.target instanceof Node)) return;
    if (!el.workflowMenu.contains(event.target) && !el.workflowButton.contains(event.target)) {
      el.workflowMenu.hidden = true;
      el.workflowButton.setAttribute('aria-expanded', 'false');
    }
    if (
      el.audioTrackPopover
      && !el.audioTrackPopover.hidden
      && !el.audioTrackPopover.contains(event.target)
      && !(event.target instanceof Element && event.target.closest('button[data-audio-popover]'))
    ) {
      closeAudioPopover();
    }
  });

  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') closeAudioPopover();
  });

  window.addEventListener('resize', () => {
    if (state.audioPopoverRowId) renderAudioPopover();
  });

  window.addEventListener('scroll', () => {
    if (state.audioPopoverRowId) renderAudioPopover();
  }, true);

  [el.searchInput, el.bucketFilter, el.caseFilter, el.reasonFilter, el.warningFilter, el.workflowStatusFilter].forEach(control => {
    control.addEventListener('change', async () => {
      renderRows();
      renderSidePanel();
      if (isWeakMode() && state.previewMode === 'selected' && selectedWeakPaths().length) {
        try {
          await ensureWeakPreview();
          renderPreviewPane();
        } catch (error) {
          el.previewPane.textContent = error.message;
        }
      }
    });
    if (control === el.searchInput) {
      control.addEventListener('input', () => {
        renderRows();
        renderSidePanel();
      });
    }
  });

  el.weakFloorSelect.addEventListener('change', async () => {
    state.weakFloor = el.weakFloorSelect.value || 'standard_definition';
    state.selected = new Set();
    state.activeRowId = '';
    clearDeletePreviewState();
    if (isWeakMode() && state.weakPayload) {
      try {
        await runWeakEncodes();
      } catch (error) {
        el.previewPane.textContent = error.message;
      }
      return;
    }
    renderRows();
    renderSidePanel();
  });

  el.repairDefaultsTabSelect.addEventListener('change', () => {
    state.repairDefaultsTab = el.repairDefaultsTabSelect.value === 'subtitle' ? 'subtitle' : 'audio';
    state.repairAction = defaultRepairAction();
    state.selected = new Set();
    state.activeRowId = '';
    state.previewMode = 'selected';
    state.repairActionNotice = '';
    clearDeletePreviewState();
    renderFilterVisibility();
    renderTableHeader();
    renderRows();
    renderSidePanel();
  });

  el.selectAllButton.addEventListener('click', async () => {
    const rows = usesSimpleSelectionShell() ? state.filteredRows.filter(row => row.selectable) : state.filteredRows;
    rows.forEach(row => state.selected.add(usesSimpleSelectionShell() ? row.row_id : row.result_id));
    if (rows[0]) state.activeRowId = usesSimpleSelectionShell() ? rows[0].row_id : rows[0].result_id;
    state.previewMode = 'selected';
    clearDeletePreviewState();
    renderRows();
    refreshSelectionState();
    if (isWeakMode() && selectedWeakPaths().length) {
      try {
        await ensureWeakPreview();
        renderPreviewPane();
      } catch (error) {
        el.previewPane.textContent = error.message;
      }
    }
  });

  el.deselectAllButton.addEventListener('click', () => {
    const rows = usesSimpleSelectionShell() ? state.filteredRows.filter(row => row.selectable) : state.filteredRows;
    rows.forEach(row => state.selected.delete(usesSimpleSelectionShell() ? row.row_id : row.result_id));
    clearDeletePreviewState();
    renderRows();
    refreshSelectionState();
  });

  el.repairActionSelect.addEventListener('change', () => {
    state.repairAction = el.repairActionSelect.value || defaultRepairAction();
    renderSidePanel();
  });

  el.repairActionButton.addEventListener('click', () => {
    const action = el.repairActionSelect.value || defaultRepairAction();
    const request = action === 'repair_subtitle_defaults'
      ? fixSelectedSubtitleDefaults()
      : fixSelectedAudioDefaults(action !== 'set_english_default');
    request.catch(error => {
      el.previewPane.textContent = error.message;
    });
  });

  el.previewScopeSelect.addEventListener('change', async () => {
    state.previewMode = el.previewScopeSelect.value === 'library' ? 'library' : 'selected';
    renderSidePanel();
    if (isWeakMode() && selectedWeakPaths().length) {
      try {
        await ensureWeakPreview();
        renderPreviewPane();
      } catch (error) {
        el.previewPane.textContent = error.message;
      }
    }
  });

  renderWorkflowHeader();
  renderFilterVisibility();
  renderRunButton();
  renderTableHeader();
  renderSelectionButtons();
  renderPanelVisibility();
  renderSidePanel();
  syncWorkflowUrl();

  el.runButton.addEventListener('click', () => {
    runActiveWorkflow().catch(error => {
      el.previewPane.textContent = error.message;
    });
  });

  el.confirmButton.addEventListener('click', () => {
    confirmSelected().catch(error => {
      el.previewPane.textContent = error.message;
    });
  });
})();
