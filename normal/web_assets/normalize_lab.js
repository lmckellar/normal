(function () {
  const WORKFLOW_LABELS = {
    normalize: 'Normalize Movie Library Naming',
    'weak-encodes': 'Review Low-Quality Encodes',
    'repair-defaults': 'Fix Audio and Subtitle Defaults',
    'canonical-lists': 'Compare Against Canonical Lists',
    'format-upgrades': 'Review Format Upgrade Candidates',
    junk: 'Remove Junk Files',
  };

  const WORKFLOW_DESCRIPTIONS = {
    normalize: 'Review naming fixes and apply clean movie title and path changes across the library.',
    'weak-encodes': 'Review low-quality encodes that are better deleted or replaced.',
    'repair-defaults': 'Fix audio and subtitle defaults to improve playback behaviour and keep repair cases visible.',
    'canonical-lists': 'Compare the library against canonical lists and inspect owned copy quality at a glance.',
    'format-upgrades': 'Compare known feature releases with UHD, Dolby Vision, immersive audio, Open Matte, and Hybrid coverage across your copies.',
    junk: 'Review obvious junk files and remove them safely.',
  };

  const CANONICAL_FALLBACK_LISTS = [
    { id: 'top_100', label: 'Top 100' },
    { id: 'top_250', label: 'Top 250' },
    { id: 'top_500', label: 'Top 500' },
    { id: 'animation', label: 'Animation' },
    { id: 'sci_fi', label: 'Sci-Fi' },
    { id: 'fantasy', label: 'Fantasy' },
    { id: 'action', label: 'Action' },
    { id: 'thriller_mystery', label: 'Thriller / Mystery' },
    { id: 'drama_romance', label: 'Drama / Romance' },
    { id: 'documentary', label: 'Documentary' },
    { id: 'comedy', label: 'Comedy' },
  ];

  // Weak-encode badges. Pure presentation over the diagnosis codes already
  // emitted server-side (see weak-encode-badge-taxonomy.md) — never a detector.
  // A row can carry several (Screecher + Magoo + …). Fun Mode swaps the sober
  // tooltip for the louder register; it never changes which badges appear.
  const WEAK_BADGES = {
    known_moron_encoder:           { glyph: '💩', tierClass: 'is-not-available', label: 'Known moron' },
    suspect_encoder:               { glyph: '🎲', tierClass: 'is-review', label: 'Suspect encoder' },
    audio_bitrate_below_minimum:   { glyph: '📢', tierClass: 'is-not-available', label: 'Screecher' },
    audio_channels_below_minimum:  { glyph: '📢', tierClass: 'is-not-available', label: 'Screecher' },
    audio_signal_missing:          { glyph: '📢', tierClass: 'is-review', label: 'Screecher' },
    video_below_minimum:           { glyph: '🥽', tierClass: 'is-not-available', label: 'Magoo' },
    video_signal_missing:          { glyph: '🥽', tierClass: 'is-review', label: 'Magoo' },
    encode_lopsided_audio_starved: { glyph: '🤡', tierClass: 'is-not-available', label: 'Dipshit' },
    encode_lopsided_video_starved: { glyph: '🤡', tierClass: 'is-not-available', label: 'Dipshit' },
  };

  const WEAK_BADGE_FUN_TOOLTIPS = {
    known_moron_encoder: badge => `${badge.name} signed this one. Reigning king of WTF encodes — every drop is the wettest fart of a file. Bin this filth without a second thought.`,
    suspect_encoder: badge => `${badge.name} again. Flips a coin for its settings — might be fine, might be sludge. Open it before you trust it.`,
    audio_bitrate_below_minimum: () => `The audio is screeching for help — bitrate scraped right to the bone.`,
    audio_channels_below_minimum: () => `Some chiseller flattened the surround. You're hearing a fraction of the room.`,
    audio_signal_missing: () => `Couldn't get a clean read on the audio. Suspicious — give it a listen.`,
    video_below_minimum: () => `Mr Magoo encoded this — squinting, smeared, bitrate-starved. The picture's a fog.`,
    video_signal_missing: () => `Couldn't get a clean read on the video bitrate. Eyeball it before trusting.`,
    encode_lopsided_audio_starved: () => `Gorgeous picture welded to honking starved audio. Classic dipshit move.`,
    encode_lopsided_video_starved: () => `Pristine audio laid over a smeared transcode. Dipshit got it backwards.`,
  };

  const LAYOUT_MODES = {
    default: '2-page-lopsided',
    book: '3-page-book',
    ledger: '4-page-ledger',
  };

  const AUDIT_STREAM_RETRY_MS = 2000;
  const ACTIVITY_POLL_MS = 2000;
  const ONBOARDING_DISMISS_KEY = 'normal.onboarding.dismissed.cold';

  const TABLE_WIDTHS = {
    foundation: 'var(--lab-table-foundation-column-width)',
    projectedPath: '28%',
    status: '13ch',
    reason: '13ch',
    issue: '13%',
    triage: '8ch',
    badges: '10ch',
    resolution: '16ch',
    video: '11ch',
    audio: '11ch',
    channels: '7ch',
    audioSummary: '18%',
    fileSize: '11ch',
    defaultAudio: '15ch',
    defaultSubtitle: '13ch',
    currentDefault: '15%',
    repairTarget: '17%',
    rank: 'var(--lab-table-foundation-column-width)',
    year: 'var(--lab-table-foundation-column-width)',
    inLibrary: '12ch',
    qualityProfile: '16ch',
    category: '17ch',
    verdict: '20ch',
    compactMeasure: '14ch',
  };

  const NORMALIZE_HEADERS = [
    { key: 'select', label: '', columnClass: 'lab-col-foundation lab-col-select', priority: 'essential', width: TABLE_WIDTHS.foundation },
    { key: 'current_value', label: 'File Name', columnClass: 'lab-col-anchor', cellClass: 'lab-cell-anchor lab-cell-mono', priority: 'essential', width: 'auto' },
    { key: 'projected_path', label: 'Projected Path', columnClass: 'lab-col-path', cellClass: 'lab-cell-path lab-cell-mono', priority: 'desktop', width: TABLE_WIDTHS.projectedPath },
    { key: 'confidence', label: 'Confidence', columnClass: 'lab-col-status', cellClass: 'lab-cell-status', priority: 'essential', width: TABLE_WIDTHS.status },
    { key: 'reason_bucket', label: 'Reason', columnClass: 'lab-col-status', cellClass: 'lab-cell-status', priority: 'medium', width: TABLE_WIDTHS.reason },
  ];

  const WEAK_HEADERS = [
    { key: 'select', label: '', columnClass: 'lab-col-foundation lab-col-select', priority: 'essential', width: TABLE_WIDTHS.foundation },
    { key: 'current_path', label: 'File Name', columnClass: 'lab-col-anchor', cellClass: 'lab-cell-anchor lab-cell-mono', priority: 'essential', width: 'auto' },
    { key: 'issue', label: 'Issue', columnClass: 'lab-col-issue', cellClass: 'lab-cell-decision', priority: 'essential', width: TABLE_WIDTHS.issue },
    { key: 'triage', label: 'Triage', columnClass: 'lab-col-signal', cellClass: 'lab-cell-signal lab-cell-mono', priority: 'essential', width: TABLE_WIDTHS.triage, tooltip: 'Triage = quality deficit × replacement priority. Higher is worse: the larger the score, the more this encode underperforms its tier and the stronger the case to replace or delete it.' },
    { key: 'badges', label: 'Badges', columnClass: 'lab-col-signal', cellClass: 'lab-cell-signal', priority: 'essential', width: TABLE_WIDTHS.badges },
    { key: 'resolution', label: 'Resolution', columnClass: 'lab-col-resolution', cellClass: 'lab-cell-supporting', priority: 'medium', width: TABLE_WIDTHS.resolution },
    { key: 'video_bitrate', label: 'Video', columnClass: 'lab-col-signal', cellClass: 'lab-cell-signal lab-cell-mono', priority: 'essential', width: TABLE_WIDTHS.video },
    { key: 'audio_bitrate', label: 'Audio', columnClass: 'lab-col-signal', cellClass: 'lab-cell-signal lab-cell-mono', priority: 'desktop', width: TABLE_WIDTHS.audio },
    { key: 'channels', label: 'Ch', columnClass: 'lab-col-signal', cellClass: 'lab-cell-signal lab-cell-mono', priority: 'medium', width: TABLE_WIDTHS.channels },
    { key: 'audio_summary', label: 'Audio Summary', columnClass: 'lab-col-audio-summary', cellClass: 'lab-cell-supporting', priority: 'desktop', width: TABLE_WIDTHS.audioSummary },
    { key: 'file_size', label: 'Size', columnClass: 'lab-col-signal', cellClass: 'lab-cell-signal lab-cell-mono', priority: 'medium', width: TABLE_WIDTHS.fileSize },
  ];

  const JUNK_HEADERS = [
    { key: 'select', label: '', columnClass: 'lab-col-foundation lab-col-select', priority: 'essential', width: TABLE_WIDTHS.foundation },
    { key: 'current_path', label: 'File Name', columnClass: 'lab-col-anchor', cellClass: 'lab-cell-anchor lab-cell-mono', priority: 'essential', width: 'auto' },
    { key: 'issue', label: 'Issue', columnClass: 'lab-col-issue', cellClass: 'lab-cell-decision', priority: 'essential', width: TABLE_WIDTHS.issue },
    { key: 'resolution', label: 'Resolution', columnClass: 'lab-col-resolution', cellClass: 'lab-cell-supporting', priority: 'medium', width: TABLE_WIDTHS.resolution },
    { key: 'video_bitrate', label: 'Video', columnClass: 'lab-col-signal', cellClass: 'lab-cell-signal lab-cell-mono', priority: 'essential', width: TABLE_WIDTHS.video },
    { key: 'audio_bitrate', label: 'Audio', columnClass: 'lab-col-signal', cellClass: 'lab-cell-signal lab-cell-mono', priority: 'desktop', width: TABLE_WIDTHS.audio },
    { key: 'confidence', label: 'Confidence', columnClass: 'lab-col-signal', cellClass: 'lab-cell-signal', priority: 'medium', width: TABLE_WIDTHS.status },
    { key: 'audio_summary', label: 'Audio Summary', columnClass: 'lab-col-audio-summary', cellClass: 'lab-cell-supporting', priority: 'desktop', width: TABLE_WIDTHS.audioSummary },
    { key: 'file_size', label: 'Size', columnClass: 'lab-col-signal', cellClass: 'lab-cell-signal lab-cell-mono', priority: 'medium', width: TABLE_WIDTHS.fileSize },
  ];

  const REPAIR_HEADERS = [
    { key: 'select', label: '', columnClass: 'lab-col-foundation lab-col-select', priority: 'essential', width: TABLE_WIDTHS.foundation },
    { key: 'current_path', label: 'File Name', columnClass: 'lab-col-anchor', cellClass: 'lab-cell-anchor lab-cell-mono', priority: 'essential', width: 'auto' },
    { key: 'audio_bitrate', label: 'Default Audio', columnClass: 'lab-col-signal', cellClass: 'lab-cell-signal lab-cell-mono', priority: 'medium', width: TABLE_WIDTHS.defaultAudio },
    { key: 'default_subtitle', label: 'Default Subtitle', columnClass: 'lab-col-resolution', cellClass: 'lab-cell-supporting', priority: 'desktop', width: TABLE_WIDTHS.defaultSubtitle },
    { key: 'issue', label: 'Issue', columnClass: 'lab-col-issue', cellClass: 'lab-cell-decision', priority: 'essential', width: TABLE_WIDTHS.issue },
    { key: 'current_default', label: 'Current Default', columnClass: 'lab-col-resolution', cellClass: 'lab-cell-supporting', priority: 'medium', width: TABLE_WIDTHS.currentDefault },
    { key: 'repair_target', label: 'Repair Target', columnClass: 'lab-col-resolution', cellClass: 'lab-cell-supporting', priority: 'desktop', width: TABLE_WIDTHS.repairTarget },
    { key: 'resolution', label: 'Resolution', columnClass: 'lab-col-signal', cellClass: 'lab-cell-signal lab-cell-mono', priority: 'medium', width: TABLE_WIDTHS.resolution },
    { key: 'file_size', label: 'Size', columnClass: 'lab-col-signal', cellClass: 'lab-cell-signal lab-cell-mono', priority: 'medium', width: TABLE_WIDTHS.fileSize },
  ];

  const CANONICAL_HEADERS = [
    { key: 'rank', label: 'Rank', columnClass: 'lab-col-foundation lab-col-signal', cellClass: 'lab-cell-foundation lab-cell-signal lab-cell-mono', priority: 'essential', width: TABLE_WIDTHS.rank },
    { key: 'title', label: 'Title', columnClass: 'lab-col-anchor', cellClass: 'lab-cell-anchor', priority: 'essential', width: 'auto' },
    { key: 'year', label: 'Year', columnClass: 'lab-col-signal', cellClass: 'lab-cell-signal lab-cell-mono', priority: 'medium', width: TABLE_WIDTHS.year },
    { key: 'in_library', label: 'In Library', columnClass: 'lab-col-status', cellClass: 'lab-cell-status', priority: 'essential', width: TABLE_WIDTHS.inLibrary },
    { key: 'quality_profile', label: 'Quality Profile', columnClass: 'lab-col-resolution', cellClass: 'lab-cell-supporting', priority: 'desktop', width: TABLE_WIDTHS.qualityProfile },
    { key: 'current_path', label: 'File Name', columnClass: 'lab-col-anchor', cellClass: 'lab-cell-anchor lab-cell-mono', priority: 'desktop', width: '24%' },
  ];

  const IMMERSIVE_HEADERS = [
    { key: 'year', label: 'Year', columnClass: 'lab-col-foundation lab-col-signal', cellClass: 'lab-cell-foundation lab-cell-signal lab-cell-mono', priority: 'essential', width: TABLE_WIDTHS.year },
    { key: 'title', label: 'Title', columnClass: 'lab-col-anchor', cellClass: 'lab-cell-anchor', priority: 'essential', width: 'auto' },
    { key: 'trait', label: 'Upgrade Feature', columnClass: 'lab-col-status', cellClass: 'lab-cell-status', priority: 'essential', width: TABLE_WIDTHS.category },
    { key: 'release_status', label: 'Known Release', tooltip: 'What the evidence corpus knows about releases carrying this feature.', columnClass: 'lab-col-status', cellClass: 'lab-cell-status', priority: 'essential', width: TABLE_WIDTHS.verdict },
    { key: 'opportunity', label: 'Corpus Verdict', tooltip: 'The resulting upgrade verdict for this title and feature.', columnClass: 'lab-col-status', cellClass: 'lab-cell-status', priority: 'essential', width: TABLE_WIDTHS.verdict },
    { key: 'coverage', label: 'Your Copies', tooltip: 'How many local copies carry this feature.', columnClass: 'lab-col-audio-summary', cellClass: 'lab-cell-supporting', priority: 'essential', width: '27ch' },
  ];

  const state = {
    workflow: workflowFromUrl(),
    layoutMode: LAYOUT_MODES.default,
    normalizePayload: null,
    weakPayload: null,
    repairPayload: null,
    junkPayload: null,
    canonicalPayload: null,
    canonicalProfilePayload: null,
    canonicalProfileSource: '',
    canonicalSelectedListId: 'top_100',
    immersivePayload: null,
    immersivePayloadSource: '',
    policyPayload: null,
    rows: [],
    filteredRows: [],
    selected: new Set(),
    activeRowId: '',
    sort: { key: 'current_value', dir: 'asc' },
    runInFlight: false,
    previewMode: 'selected',
    applyInFlight: false,
    weakFloor: 'standard_definition',
    funMode: false,
    weakPreview: null,
    weakPreviewKey: '',
    weakPreviewLoading: false,
    dashboardProfilePayload: null,
    dashboardProfileSource: '',
    dashboardRequestedSource: '',
    surfaceMode: 'default',
    settingsStatus: null,
    settingsBusy: false,
    settingsRenderKey: '',
    policyBusy: false,
    policySectionLabel: '',
    policyDrafts: {},
    policyEditorRenderKey: '',
    auditPayload: null,
    auditBusy: false,
    auditRefreshInFlight: false,
    auditNeedsRefresh: false,
    auditSignature: '',
    auditOpenBreakdowns: new Set(),
    auditEventSource: null,
    auditEventSourceKey: '',
    auditEventReconnectTimer: 0,
    repairAction: 'set_english_default',
    repairActionNotice: '',
    audioFixBusy: false,
    subtitleFixBusy: false,
    trackPopoverRowId: '',
    trackPopoverKind: '',
    weakPayloadSource: '',
    repairPayloadSource: '',
    junkDeleteSkipped: [],
    junkFilenameResizeObserver: null,
    junkFilenameResizeFrame: 0,
    catalogueExportInFlight: false,
    activityPayload: null,
    activityRefreshInFlight: false,
    activityPollTimer: 0,
    repairPreviewSignature: '',
    activeRemuxPath: '',
    completedRemuxPaths: new Set(),
    onboardingVisible: false,
    lopsidedDraft: null,
    lopsidedView: 'registers',
    lopsidedBusy: false,
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
    workflowCanonicalLists: document.getElementById('workflowCanonicalLists'),
    workflowImmersive: document.getElementById('workflowImmersive'),
    workflowJunk: document.getElementById('workflowJunk'),
    sourcePath: document.getElementById('sourcePath'),
    runButton: document.getElementById('runButton'),
    filterBar: document.getElementById('filterBar'),
    searchInput: document.getElementById('searchInput'),
    bucketFilter: document.getElementById('bucketFilter'),
    workflowStatusFilter: document.getElementById('workflowStatusFilter'),
    canonicalListFilter: document.getElementById('canonicalListFilter'),
    traitFilter: document.getElementById('traitFilter'),
    traitStatusFilter: document.getElementById('traitStatusFilter'),
    selectAllButton: document.getElementById('selectAllButton'),
    deselectAllButton: document.getElementById('deselectAllButton'),
    tableColGroup: document.getElementById('tableColGroup'),
    tableHeaderRow: document.getElementById('tableHeaderRow'),
    rowsBody: document.getElementById('rowsBody'),
    scanPage: document.querySelector('.lab-page-scan'),
    previewPage: document.querySelector('.lab-page-preview'),
    scanTablePanel: document.getElementById('scanTablePanel'),
    dashboardPanel: document.getElementById('dashboardPanel'),
    policyEditorPanel: document.getElementById('policyEditorPanel'),
    auditPanel: document.getElementById('auditPanel'),
    policyToggle: document.getElementById('policyToggle'),
    dashboardToggle: document.getElementById('dashboardToggle'),
    auditToggle: document.getElementById('auditToggle'),
    placeholderToggle: document.getElementById('placeholderToggle'),
    settingsToggle: document.getElementById('settingsToggle'),
    settingsPanel: document.getElementById('settingsPanel'),
    placeholderDownloadToggle: document.getElementById('placeholderDownloadToggle'),
    previewControls: document.getElementById('previewControls'),
    repairActionControls: document.getElementById('repairActionControls'),
    repairActionSelect: document.getElementById('repairActionSelect'),
    repairActionButton: document.getElementById('repairActionButton'),
    confirmButton: document.getElementById('confirmButton'),
    previewPanelKicker: document.getElementById('previewPanelKicker'),
    previewPanelHeading: document.getElementById('previewPanelHeading'),
    previewPane: document.getElementById('previewPane'),
    inspectionPane: document.getElementById('inspectionPane'),
    trackPopover: document.getElementById('trackPopover'),
    repairLockOverlay: document.getElementById('repairLockOverlay'),
    onboardingGate: document.getElementById('onboardingGate'),
    onboardingGateBackdrop: document.getElementById('onboardingGateBackdrop'),
    onboardingGateClose: document.getElementById('onboardingGateClose'),
  };

  el.sourcePath.value = window.DEFAULT_SOURCE || '';

  function normalBoot() {
    const boot = window.NORMAL_BOOT || {};
    return typeof boot === 'object' && boot ? boot : {};
  }

  function onboardingBoot() {
    const onboarding = normalBoot().onboarding || {};
    return typeof onboarding === 'object' && onboarding ? onboarding : {};
  }

  function onboardingTemp() {
    return onboardingBoot().temp === 'warm' ? 'warm' : 'cold';
  }

  function onboardingShouldShow() {
    if (!el.onboardingGate) return false;
    if (onboardingTemp() === 'warm') {
      window.localStorage.removeItem(ONBOARDING_DISMISS_KEY);
      return false;
    }
    return window.localStorage.getItem(ONBOARDING_DISMISS_KEY) !== '1';
  }

  function hideOnboardingGate({ remember = false } = {}) {
    if (!el.onboardingGate || !state.onboardingVisible) return;
    state.onboardingVisible = false;
    el.onboardingGate.hidden = true;
    document.body.style.removeProperty('overflow');
    if (remember) window.localStorage.setItem(ONBOARDING_DISMISS_KEY, '1');
  }

  function showOnboardingGate() {
    if (!el.onboardingGate || !onboardingShouldShow()) return;
    state.onboardingVisible = true;
    el.onboardingGate.hidden = false;
    document.body.style.setProperty('overflow', 'hidden');
  }

  function workflowFromUrl() {
    const params = new URLSearchParams(window.location.search);
    const workflow = params.get('workflow');
    if (workflow === 'immersive-audio') return 'format-upgrades';
    if (workflow === 'weak-encodes' || workflow === 'junk' || workflow === 'repair-defaults' || workflow === 'canonical-lists' || workflow === 'format-upgrades') return workflow;
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
    if (state.workflow === 'canonical-lists') return state.canonicalPayload;
    if (state.workflow === 'format-upgrades') return state.immersivePayload;
    if (state.workflow === 'junk') return state.junkPayload;
    return state.normalizePayload;
  }

  function activeProfilePayload() {
    if (state.workflow === 'weak-encodes') return state.weakPayload;
    if (state.workflow === 'repair-defaults') return state.repairPayload;
    if (state.workflow === 'canonical-lists') return state.canonicalProfilePayload;
    if (state.workflow === 'format-upgrades') return state.immersivePayload;
    return null;
  }

  function currentPolicyPayload() {
    return state.policyPayload || activeProfilePayload() || null;
  }

  function normalizeSourceKey(value) {
    const text = String(value || '').trim();
    if (!text) return '';
    return text.length > 1 ? text.replace(/\/+$/, '') : text;
  }

  function updateDashboardPayload(payload, requestedSource = '') {
    const source = normalizeSourceKey(payload?.source_root);
    if (!payload || !payload.histogram || !source) return;
    state.dashboardProfilePayload = payload;
    state.dashboardProfileSource = source;
    state.dashboardRequestedSource = normalizeSourceKey(requestedSource) || source;
    state._lopsidedFactsCache = null;
  }

  async function refreshDashboardPayload(source, { weakFloor = state.weakFloor } = {}) {
    const normalizedSource = normalizeSourceKey(source);
    if (!normalizedSource) return null;
    const payload = await postJson('/api/movies/profile', { source: normalizedSource, weak_floor: weakFloor });
    updateDashboardPayload(payload, normalizedSource);
    return payload;
  }

  function activeProfilePayloadContext() {
    if (state.workflow === 'weak-encodes') {
      return { payload: state.weakPayload, requestedSource: state.weakPayloadSource };
    }
    if (state.workflow === 'repair-defaults') {
      return { payload: state.repairPayload, requestedSource: state.repairPayloadSource };
    }
    if (state.workflow === 'canonical-lists') {
      return { payload: state.canonicalProfilePayload, requestedSource: state.canonicalProfileSource };
    }
    if (state.workflow === 'format-upgrades') {
      return { payload: state.immersivePayload, requestedSource: state.immersivePayloadSource };
    }
    return { payload: null, requestedSource: '' };
  }

  function currentDashboardPayload() {
    const source = normalizeSourceKey(el.sourcePath.value);
    if (
      state.dashboardProfilePayload
      && (!source || state.dashboardProfileSource === source || state.dashboardRequestedSource === source)
    ) {
      return state.dashboardProfilePayload;
    }
    const { payload, requestedSource } = activeProfilePayloadContext();
    const payloadSource = normalizeSourceKey(payload?.source_root);
    if (payload?.histogram) {
      if (!source || payloadSource === source || normalizeSourceKey(requestedSource) === source) return payload;
      return payload;
    }
    return null;
  }

  function surfaceOpen() {
    return state.surfaceMode !== 'default';
  }

  function dashboardSurfaceOpen() {
    return state.surfaceMode === 'dashboard';
  }

  function policySurfaceOpen() {
    return state.surfaceMode === 'policy';
  }

  function auditSurfaceOpen() {
    return state.surfaceMode === 'audit';
  }

  function settingsSurfaceOpen() {
    return state.surfaceMode === 'settings';
  }

  function dismissAuditSurface() {
    if (!auditSurfaceOpen()) return false;
    state.surfaceMode = 'default';
    closeAuditEventSource();
    return true;
  }

  function dismissActiveSurface() {
    if (!surfaceOpen()) return false;
    if (auditSurfaceOpen()) closeAuditEventSource();
    state.surfaceMode = 'default';
    return true;
  }

  function currentPolicyDefinitions() {
    const payload = currentPolicyPayload();
    if (!Array.isArray(payload?.policy_definitions)) return [];
    const preferredOrder = ['default_source', 'delete_mode', 'library_defaults', 'language_subtitle_defaults'];
    const filtered = payload.policy_definitions.filter(definition => definition?.label !== 'replacement_candidate');
    return filtered.slice().sort((left, right) => {
      const leftIndex = preferredOrder.indexOf(left?.label || '');
      const rightIndex = preferredOrder.indexOf(right?.label || '');
      if (leftIndex === -1 && rightIndex === -1) return 0;
      if (leftIndex === -1) return 1;
      if (rightIndex === -1) return -1;
      return leftIndex - rightIndex;
    });
  }

  function currentWarningGateSafetyLevel() {
    return String(currentPolicyPayload()?.policy?.warning_gate_safety_level || 'safe').trim().toLowerCase() || 'safe';
  }

  function currentReplacementDefinition() {
    const payload = currentPolicyPayload();
    return payload?.replacement_candidate_definition || state.weakPayload?.replacement_candidate_definition || null;
  }

  function currentQualityProfileDefinitions() {
    const payload = currentPolicyPayload();
    return Array.isArray(payload?.quality_profile_definitions) ? payload.quality_profile_definitions : [];
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

  function isCanonicalMode() {
    return state.workflow === 'canonical-lists';
  }

  function isImmersiveMode() {
    return state.workflow === 'format-upgrades';
  }

  function usesSimpleSelectionShell() {
    return isWeakMode() || isRepairDefaultsMode() || isJunkMode();
  }

  const REPAIR_ACTION_ORDER = [
    'set_english_default',
    'repair_subtitle_defaults',
    'set_english_default_repair_subtitle_defaults',
    'set_english_default_drop_foreign',
    'set_english_default_drop_foreign_repair_subtitle_defaults',
  ];

  const REPAIR_ACTION_CONFIGS = {
    set_english_default: {
      label: 'Make Best English Audio Default',
      families: ['audio'],
      dropForeignAudio: false,
      runsSubtitle: false,
      destructiveDelete: true,
      buttonClass: 'is-primary',
      buttonText: 'Run Repair',
      busyText: 'Running Audio Remux',
      emptyText: 'Select audio-packaging issues to preview default-track repair.',
      summaryNoun: 'audio-packaging title',
      statusOptions: [
        ['all', 'all'],
        ['weak_english', 'weak English'],
        ['wrong_default', 'wrong default'],
        ['queued', 'queued'],
      ],
    },
    repair_subtitle_defaults: {
      label: 'Normalize Subtitle Defaults',
      families: ['subtitle'],
      dropForeignAudio: false,
      runsSubtitle: true,
      destructiveDelete: false,
      buttonClass: 'is-primary',
      buttonText: 'Run Repair',
      busyText: 'Running Subtitle Remux',
      emptyText: 'Select subtitle-default issues to preview non-destructive repair consequences.',
      summaryNoun: 'subtitle issue',
      statusOptions: [
        ['all', 'all'],
        ['forced_english', 'forced English'],
        ['non_english_audio', 'non-English audio'],
        ['clear_default', 'clear default'],
      ],
    },
    set_english_default_repair_subtitle_defaults: {
      label: 'Make Best English Audio Default + Normalize Subtitle Defaults',
      families: ['audio', 'subtitle'],
      dropForeignAudio: false,
      runsSubtitle: true,
      destructiveDelete: true,
      buttonClass: 'is-caution',
      buttonText: 'Run Combined Repair',
      busyText: 'Running Combined Remux',
      emptyText: 'Select repair issues to preview combined audio and subtitle repair consequences.',
      summaryNoun: 'repair title',
      statusOptions: [
        ['all', 'all'],
        ['both', 'audio + subtitle'],
        ['audio_only', 'audio only'],
        ['subtitle_only', 'subtitle only'],
      ],
    },
    set_english_default_drop_foreign: {
      label: 'Make Best English Audio Default + Remove Foreign Audio',
      families: ['audio'],
      dropForeignAudio: true,
      runsSubtitle: false,
      destructiveDelete: true,
      buttonClass: 'is-caution',
      buttonText: 'Run Combined Repair',
      busyText: 'Running Audio Prune Remux',
      emptyText: 'Select audio-packaging issues to preview default-track repair and internal audio-stream deletion.',
      summaryNoun: 'audio-packaging title',
      statusOptions: [
        ['all', 'all'],
        ['weak_english', 'weak English'],
        ['wrong_default', 'wrong default'],
        ['queued', 'queued'],
      ],
    },
    set_english_default_drop_foreign_repair_subtitle_defaults: {
      label: 'Make Best English Audio Default + Remove Foreign Audio + Normalize Subtitle Defaults',
      families: ['audio', 'subtitle'],
      dropForeignAudio: true,
      runsSubtitle: true,
      destructiveDelete: true,
      buttonClass: 'is-caution',
      buttonText: 'Run Combined Repair',
      busyText: 'Running Full Remux',
      emptyText: 'Select repair issues to preview combined audio prune and subtitle repair consequences.',
      summaryNoun: 'repair title',
      statusOptions: [
        ['all', 'all'],
        ['both', 'audio + subtitle'],
        ['audio_only', 'audio only'],
        ['subtitle_only', 'subtitle only'],
      ],
    },
  };

  const REPAIR_STATUS_FILTER_OPTIONS = [
    ['all', 'all'],
    ['both', 'audio + subtitle'],
    ['audio_only', 'audio only'],
    ['subtitle_only', 'subtitle only'],
    ['weak_english', 'weak English'],
    ['wrong_default', 'wrong default'],
    ['forced_english', 'forced English'],
    ['non_english_audio', 'non-English audio'],
    ['clear_default', 'clear default'],
    ['queued', 'queued'],
  ];

  function repairActionConfig(action = state.repairAction) {
    return REPAIR_ACTION_CONFIGS[action] || REPAIR_ACTION_CONFIGS.set_english_default;
  }

  function usesDeletePreviewShell() {
    return isWeakMode() || isJunkMode() || (isRepairDefaultsMode() && repairActionConfig().families.includes('audio'));
  }

  function defaultRepairAction() {
    return 'set_english_default';
  }

  function repairActionOptions() {
    return REPAIR_ACTION_ORDER.map(value => ({
      value,
      label: repairActionConfig(value).label,
    }));
  }

  function repairActionOptionLabel(action, selectedCount, applicableCount) {
    const label = repairActionConfig(action).label;
    if (!selectedCount) return label;
    if (!applicableCount) return `${label} (unavailable)`;
    if (applicableCount === selectedCount) return label;
    return `${label} (${applicableCount}/${selectedCount})`;
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
    const options = currentReplacementDefinition()?.fields?.[0]?.options;
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

  function syncWeakFloorState() {
    const options = weakFloorDefinitionOptions();
    if (!options.some(option => option.value === state.weakFloor)) {
      state.weakFloor = options[0]?.value || 'standard_definition';
    }
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

  function effectiveAudioStreamBitrateKbps(track, row = null) {
    const bitrate = Number(track?.bitrate_kbps || 0);
    if (bitrate > 0) return bitrate;
    if (track?.is_default) {
      const fallback = Number(row?.item?.facts?.audio_bitrate_kbps || row?.audio_bitrate || 0);
      if (fallback > 0) return fallback;
    }
    const tracks = audioTracksForRow(row);
    if (tracks.length === 1) {
      const fallback = Number(row?.item?.facts?.audio_bitrate_kbps || row?.audio_bitrate || 0);
      if (fallback > 0) return fallback;
    }
    return 0;
  }

  function describeAudioPopoverFacts(track, row = null) {
    const parts = [];
    const format = describeAudioFormat(track);
    const bitrate = formatBitrate(effectiveAudioStreamBitrateKbps(track, row));
    if (track?.title) parts.push(track.title);
    if (format && format !== '—') parts.push(format);
    if (bitrate && bitrate !== '—') parts.push(bitrate);
    return parts.length ? parts.join(' · ') : '—';
  }

  function repairDefaultAudioLabel(item, row = null) {
    const stream = movieDefaultAudioStream(item);
    if (!stream) return formatBitrate(row?.audio_bitrate);
    const language = displayAudioLanguage(stream.language);
    const bitrate = formatBitrate(effectiveAudioStreamBitrateKbps(stream, row));
    return bitrate === '—' ? language : `${language} · ${bitrate}`;
  }

  function sameTrack(a, b) {
    if (!a || !b) return false;
    const aIndex = String(a.index || '');
    const bIndex = String(b.index || '');
    if (aIndex && bIndex) return aIndex === bIndex;
    return a === b;
  }

  function isEffectiveDefaultAudioTrack(track, row) {
    return sameTrack(track, movieDefaultAudioStream(row?.item));
  }

  function popoverTrackLanguageMarkup(label, isDefault = false) {
    return `<span class="lab-audio-popover-lang${isDefault ? ' is-default' : ''}">${escapeHtml(label)}</span>`;
  }

  function actualResolutionLabel(item) {
    const width = Number(item?.facts?.width || 0);
    const height = Number(item?.facts?.height || 0);
    if (width > 0 && height > 0) return `${width} x ${height}`;
    return item?.facts?.resolution_bucket || '—';
  }

  function canonicalListsForPayload(payload = state.canonicalPayload) {
    return Array.isArray(payload?.list_summaries) ? payload.list_summaries : [];
  }

  function canonicalFallbackOptionsMarkup() {
    return CANONICAL_FALLBACK_LISTS
      .map(item => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.label)}</option>`)
      .join('');
  }

  function activeCanonicalListSummary() {
    const lists = canonicalListsForPayload();
    if (!lists.length) return null;
    return lists.find(item => item.id === state.canonicalSelectedListId) || lists[0] || null;
  }

  function canonicalProfileItemsByPath() {
    const items = Array.isArray(state.canonicalProfilePayload?.movies) ? state.canonicalProfilePayload.movies : [];
    return new Map(items.map(item => [item.path || '', item]));
  }

  function canonicalOwnedStatusLabel(row) {
    return row.owned ? 'Owned' : 'Missing';
  }

  function imdbTitleUrl(imdbId) {
    const value = String(imdbId || '').trim();
    return value ? `https://www.imdb.com/title/${value}/` : '';
  }

  function canonicalTitleMarkup(title, imdbId) {
    const label = escapeHtml(title || '—');
    const url = imdbTitleUrl(imdbId);
    if (!url) return `<span class="lab-cell-text">${label}</span>`;
    return `<a class="lab-cell-text" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${label}</a>`;
  }

  function canonicalQualityProfileLabel(item) {
    const label = item?.profile?.quality_label || '';
    return label ? qualityProfileDisplayLabel(label) : '';
  }

  function canonicalPrimaryAudioType(item) {
    const stream = movieDefaultAudioStream(item);
    if (!stream) return '—';
    const parts = [audioCodecDisplayName(stream.codec, stream.profile), audioChannelLayout(stream.channels)].filter(Boolean);
    return parts.join(' · ') || '—';
  }

  function canonicalInspectorFacts(row) {
    const item = row?.item || null;
    if (!item) return [];
    const languages = audioTracksForRow(row).map(track => displayAudioLanguage(track.language));
    const uniqueLanguages = [...new Set(languages.filter(Boolean))];
    const width = Number(item?.facts?.width || 0);
    const height = Number(item?.facts?.height || 0);
    return [
      ['Video resolution', width > 0 && height > 0 ? `${width} x ${height}` : '—'],
      ['Video bitrate', formatBitrate(item?.facts?.video_bitrate_kbps || 0)],
      ['Audio bitrate', formatBitrate(item?.facts?.audio_bitrate_kbps || 0)],
      ['Audio type', canonicalPrimaryAudioType(item)],
      ['Audio languages', uniqueLanguages.length ? uniqueLanguages.join(', ') : '—'],
    ];
  }

  function fileNameFromPath(path) {
    const parts = String(path || '').split('/').filter(Boolean);
    return parts.length ? parts[parts.length - 1] : String(path || '');
  }

  function projectedPathMarkup(path) {
    const raw = String(path || '');
    const cut = raw.lastIndexOf('/');
    if (cut < 0) return escapeHtml(raw);
    return `<span class="lab-path-dir">${escapeHtml(raw.slice(0, cut + 1))}</span><span class="lab-path-file">${escapeHtml(raw.slice(cut + 1))}</span>`;
  }

  function parseTitleYearFromPath(path) {
    const stem = fileNameFromPath(path).replace(/\.[^.]+$/, '');
    const match = stem.match(/^(.+?)\s*\((\d{4})\)/);
    if (match) return { title: match[1].trim(), year: match[2] };
    return { title: stem.trim(), year: '' };
  }

  function traitDisplayLabel(trait) {
    if (trait === 'immersive_audio') return 'Immersive Audio';
    if (trait === 'uhd') return 'UHD';
    if (trait === 'dolby_vision') return 'Dolby Vision';
    if (trait === 'open_matte') return 'Open Matte';
    if (trait === 'hybrid') return 'Hybrid';
    return humanProfileLabel(trait);
  }

  function immersiveVerdictDisplayLabel(status) {
    const labels = {
      upgrade_available: 'Confirmed Available',
      likely_available: 'Likely Available',
      no_known_release: 'No Known Release',
      contested: 'Conflicting Reports',
      unverified: 'Not Researched',
    };
    return labels[status] || humanProfileLabel(status);
  }

  function immersiveVerdictPillClass(status) {
    if (status === 'upgrade_available') return 'is-actionable';
    if (status === 'no_known_release') return 'is-not-available';
    if (status === 'contested') return 'is-review';
    return 'is-review';
  }

  function formatOpportunityDisplayLabel(opportunity) {
    const labels = {
      upgrade_found: 'Upgrade Found',
      partial_coverage: 'Partial Coverage',
      already_covered: 'Already Covered',
      quality_review: 'Quality Review',
      no_known_upgrade: 'No Known Upgrade',
      conflicting_reports: 'Conflicting Reports',
      research_needed: 'Research Needed',
    };
    return labels[opportunity] || humanProfileLabel(opportunity);
  }

  function formatOpportunityPillClass(opportunity) {
    if (opportunity === 'already_covered') return 'is-safe';
    if (opportunity === 'upgrade_found' || opportunity === 'partial_coverage') return 'is-actionable';
    if (opportunity === 'no_known_upgrade') return 'is-not-available';
    return 'is-review';
  }

  function localCopySummary(row) {
    const present = Number(row.local_present_count || 0);
    const total = Number(row.local_copy_count || 0);
    const rejected = Number(row.local_rejected_count || 0);
    if (rejected && !present) {
      const detail = row.capability === 'quality_unverified'
        ? 'claim found, quality could not be verified'
        : 'claim found, below quality floor';
      return `${detail} · ${present} of ${total}`;
    }
    if (total && present === total) return `all copies have it · ${present} of ${total}`;
    if (present) return `some copies have it · ${present} of ${total}`;
    if (total) return `no copies have it · 0 of ${total}`;
    return 'no local copies';
  }

  function immersiveRows() {
    const assessments = Array.isArray(state.immersivePayload?.trait_assessments)
      ? state.immersivePayload.trait_assessments
      : [];
    return assessments.map(assessment => ({
      ...assessment,
      row_id: `trait:${assessment.trait}:${assessment.title}:${assessment.year}`,
    }));
  }

  function qualityProfileDisplayLabel(label) {
    const normalized = String(label || '').trim();
    if (!normalized) return '';
    const definition = currentQualityProfileDefinitions().find(item => item?.label === normalized);
    return String(definition?.display_name || '').trim() || humanProfileLabel(normalized);
  }

  function replacementFloorDisplayLabel(label) {
    const normalized = String(label || '').trim();
    if (!normalized) return '';
    const options = currentReplacementDefinition()?.fields?.[0]?.options;
    if (Array.isArray(options)) {
      const option = options.find(item => item?.value === normalized);
      const display = String(option?.label || '').trim();
      if (display) return display;
    }
    return qualityProfileDisplayLabel(normalized);
  }

  function policyDefinitionDisplayLabel(label) {
    const normalized = String(label || '').trim();
    if (!normalized) return '';
    if (normalized === 'replacement_candidate') {
      const replacement = currentReplacementDefinition();
      const display = String(replacement?.display_name || '').trim();
      if (display) return display;
    }
    const definition = currentPolicyDefinitions().find(item => item?.label === normalized);
    const display = String(definition?.display_name || '').trim();
    if (display) return display;
    return qualityProfileDisplayLabel(normalized);
  }

  function humanProfileLabel(label) {
    if (label === 'standard_definition') return 'Suspect Encode';
    if (label === 'compact_grade') return 'Compact Grade';
    if (label === 'library_grade') return 'Library Grade';
    if (label === 'collector_grade') return 'Collector Grade';
    if (label === 'reference') return 'Reference';
    if (label === 'default_source') return 'Default Library Directory';
    if (label === 'library_defaults') return 'Library Defaults';
    if (label === 'language_subtitle_defaults') return 'Language & Subtitles';
    if (label === 'delete_mode') return 'Delete Posture';
    if (label === 'meets_minimum') return 'Meets Minimum';
    if (label === 'needs_review') return 'Needs Review';
    if (label === 'replacement_candidate') return 'Replacement Candidate';
    return String(label || '').split('_').filter(Boolean).map(word => word.charAt(0).toUpperCase() + word.slice(1)).join(' ');
  }

  async function postJson(url, body) {
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || `${url} failed`);
    return payload;
  }

  function auditSourceKey() {
    return normalizeSourceKey(el.sourcePath.value);
  }

  function auditPayloadSignature(payload) {
    const events = Array.isArray(payload?.events) ? payload.events : [];
    const followups = Array.isArray(payload?.active_followups) ? payload.active_followups : [];
    const latestEvent = events[events.length - 1] || null;
    return [
      payload?.ledger_revision || '',
      payload?.latest_event_id || latestEvent?.event_id || '',
      payload?.latest_recorded_at || latestEvent?.recorded_at || '',
      events.length,
      followups.length,
    ].join(':');
  }

  function clearAuditEventReconnectTimer() {
    if (!state.auditEventReconnectTimer) return;
    window.clearTimeout(state.auditEventReconnectTimer);
    state.auditEventReconnectTimer = 0;
  }

  function closeAuditEventSource() {
    clearAuditEventReconnectTimer();
    if (state.auditEventSource) state.auditEventSource.close();
    state.auditEventSource = null;
    state.auditEventSourceKey = '';
  }

  function scheduleAuditEventReconnect(delayMs = AUDIT_STREAM_RETRY_MS) {
    clearAuditEventReconnectTimer();
    if (!auditSurfaceOpen() || !auditSourceKey()) return;
    state.auditEventReconnectTimer = window.setTimeout(() => {
      state.auditEventReconnectTimer = 0;
      ensureAuditEventSource();
    }, delayMs);
  }

  function ensureAuditEventSource() {
    const source = auditSourceKey();
    if (!auditSurfaceOpen() || !source) {
      closeAuditEventSource();
      return;
    }
    if (state.auditEventSource && state.auditEventSourceKey === source) return;
    closeAuditEventSource();
    const stream = new EventSource(`/api/audit/stream?source=${encodeURIComponent(source)}`);
    state.auditEventSource = stream;
    state.auditEventSourceKey = source;
    stream.onmessage = event => {
      if (state.auditEventSource !== stream) return;
      let payload = null;
      try {
        payload = JSON.parse(event.data || '{}');
      } catch {
        return;
      }
      const changedSources = Array.isArray(payload?.source_roots) ? payload.source_roots.map(normalizeSourceKey) : [];
      if (!changedSources.includes(source) && !changedSources.includes('__system__')) return;
      if (state.auditRefreshInFlight) {
        state.auditNeedsRefresh = true;
        return;
      }
      refreshAuditPayload({ silent: true, immediate: true }).catch(error => {
        if (!state.auditPayload) el.inspectionPane.textContent = error.message;
      });
    };
    stream.onerror = () => {
      if (state.auditEventSource !== stream) return;
      closeAuditEventSource();
      scheduleAuditEventReconnect();
    };
  }

  function markAuditLedgerDirty() {
    if (!auditSourceKey()) return;
    state.auditNeedsRefresh = true;
    if (!auditSurfaceOpen() || state.auditRefreshInFlight) return;
    state.auditNeedsRefresh = false;
    refreshAuditPayload({ silent: true, immediate: true }).catch(error => {
      if (!state.auditPayload) el.inspectionPane.textContent = error.message;
    });
  }

  async function refreshAuditPayload({ silent = false, immediate = false } = {}) {
    const source = auditSourceKey();
    if (!source) {
      closeAuditEventSource();
      state.auditPayload = null;
      state.auditNeedsRefresh = false;
      state.auditRefreshInFlight = false;
      state.auditBusy = false;
      state.auditSignature = '';
      renderAuditPanel();
      renderInspectionPane();
      return null;
    }
    if (state.auditRefreshInFlight) return state.auditPayload;
    state.auditRefreshInFlight = true;
    const hadPayload = Boolean(state.auditPayload);
    if (!silent && !hadPayload) {
      state.auditBusy = true;
      renderAuditPanel();
      renderInspectionPane();
    }
    try {
      const payload = await postJson('/api/audit/read', { source, limit: 40 });
      const signature = auditPayloadSignature(payload);
      const changed = signature !== state.auditSignature;
      state.auditPayload = payload;
      state.auditSignature = signature;
      if (changed || !hadPayload || !silent || immediate) {
        renderAuditPanel();
        renderInspectionPane();
      }
      ensureAuditEventSource();
      return payload;
    } finally {
      state.auditRefreshInFlight = false;
      state.auditBusy = false;
      if (state.auditNeedsRefresh) {
        state.auditNeedsRefresh = false;
        if (auditSurfaceOpen() && auditSourceKey()) {
          refreshAuditPayload({ silent: true, immediate: true }).catch(error => {
            if (!state.auditPayload) el.inspectionPane.textContent = error.message;
          });
        }
      }
      renderAuditPanel();
      renderInspectionPane();
    }
  }

  function downloadFilenameFromDisposition(header, fallback = 'movie-catalogue.xlsx') {
    const value = String(header || '');
    const match = value.match(/filename="([^"]+)"/i);
    return match?.[1] || fallback;
  }

  function applyPolicyPayload(payload) {
    if (!payload) return;
    state.policyPayload = payload;
    const preferences = payload.operator_preferences || {};
    if (Object.prototype.hasOwnProperty.call(preferences, 'fun_mode')) {
      state.funMode = Boolean(preferences.fun_mode);
    }
    if (payload?.replacement_candidate_definition?.fields?.[0]?.value) {
      state.weakFloor = payload.replacement_candidate_definition.fields[0].value;
    }
    syncWeakFloorState();
    if (state.weakPayload) {
      state.weakPayload = { ...state.weakPayload, ...payload };
    }
    if (state.repairPayload) {
      state.repairPayload = { ...state.repairPayload, ...payload };
    }
  }

  function preferredDefaultSource() {
    return normalizeSourceKey(state.policyPayload?.operator_preferences?.default_source || '');
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

  function isFunMode() {
    return !!state.funMode;
  }

  function moronEncoderFinding(item) {
    const diagnostics = item?.profile?.diagnostics || [];
    return diagnostics.find(diag => diag?.code === 'known_moron_encoder')
      || diagnostics.find(diag => diag?.code === 'suspect_encoder')
      || null;
  }

  function moronEncoderName(summary) {
    return String(summary || '').split(' — ')[0].trim();
  }

  function collectWeakBadges(item) {
    const diagnostics = item?.profile?.diagnostics || [];
    const seen = new Set();
    const badges = [];
    for (const diag of diagnostics) {
      const def = WEAK_BADGES[diag?.code];
      if (!def || seen.has(def.glyph)) continue;
      seen.add(def.glyph);
      badges.push({
        code: diag.code,
        glyph: def.glyph,
        tierClass: def.tierClass,
        label: def.label,
        summary: diag.summary || '',
        name: moronEncoderName(diag.summary || ''),
      });
    }
    return badges;
  }

  function weakBadgeClusterMarkup(badges) {
    if (!badges || !badges.length) return '';
    return badges.map(badge => {
      const funBuilder = WEAK_BADGE_FUN_TOOLTIPS[badge.code];
      const tip = isFunMode() && funBuilder ? funBuilder(badge) : (badge.summary || badge.label);
      return `<span class="lab-moron-badge ${badge.tierClass}" title="${escapeHtml(tip)}" aria-label="${escapeHtml(badge.label)}">${badge.glyph}</span>`;
    }).join('');
  }

  function humanMovieProfileIssueLabel(code, summary = '') {
    if (code === 'known_moron_encoder') {
      const name = moronEncoderName(summary);
      return name ? `Known Moron (${name})` : 'Known Moron';
    }
    if (code === 'suspect_encoder') {
      const name = moronEncoderName(summary);
      return name ? `Suspect Encoder (${name})` : 'Suspect Encoder';
    }
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
    if (code === 'english_audio_missing_default_english_subtitle') return 'Missing English Subtitle Default';
    if (code === 'wrong_default_subtitle_language') return 'Wrong Default Subtitle Language';
    if (code === 'unnecessary_default_subtitle') return 'Unnecessary Default Subtitle';
    if (code === 'path_not_normalized') return 'Non-Standard Path';
    if (code === 'promo_sidecar_present') return 'Promo Sidecar Present';
    if (code === 'subtitle_policy_unknown') return 'Subtitle Policy Unknown';
    return code ? code.split('_').filter(Boolean).map(word => word.charAt(0).toUpperCase() + word.slice(1)).join(' ') : '';
  }

  function movieProfileInlineSummary(item) {
    const moron = moronEncoderFinding(item);
    if (moron) return humanMovieProfileIssueLabel(moron.code || '', moron.summary || '');
    const issue = firstMovieProfileIssueResult(item);
    if (issue) return humanMovieProfileIssueLabel(issue.code || '', issue.summary || '');
    if (item?.profile?.legacy_bitrate_label) return `Legacy ${item.profile.legacy_bitrate_label.replaceAll('_', ' ')}`;
    return '';
  }

  function movieHasPackagingOwnedIssue(item) {
    const diagnostics = item?.profile?.diagnostics || [];
    return diagnostics.some(diag => diag?.code === 'default_non_english_audio' || diag?.code === 'foreign_original_audio_ok');
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
    return repairPlanAudio(item)?.issue_code || '';
  }

  function movieSubtitleSetupResult(item) {
    const issueCode = movieSubtitleReadinessIssueCode(item);
    return issueCode ? { domain: 'subtitle_setup', code: issueCode } : null;
  }

  function movieSubtitleReadinessIssueCode(item) {
    return repairPlanSubtitle(item)?.issue_code || '';
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

  function repairPlan(item) {
    return item?.repair_plan || null;
  }

  function repairPlanAudio(item) {
    return repairPlan(item)?.audio || null;
  }

  function repairPlanSubtitle(item) {
    return repairPlan(item)?.subtitle || null;
  }

  function repairPlanCombined(item) {
    return repairPlan(item)?.combined || null;
  }

  function repairPlanCombinedSubtitle(item) {
    return repairPlanCombined(item)?.subtitle_after_audio || null;
  }

  function audioStreamByIndex(item, streamIndex) {
    return (item?.facts?.audio_streams || []).find(stream => String(stream?.index || '') === String(streamIndex || '')) || null;
  }

  function subtitleStreamByIndex(item, streamIndex) {
    return (item?.facts?.subtitle_streams || []).find(stream => String(stream?.index || '') === String(streamIndex || '')) || null;
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

  function chooseBestFullEnglishSubtitleStream(item) {
    const streams = (item?.facts?.subtitle_streams || []).filter(stream => isEnglishSubtitleStream(stream) && !stream?.is_forced);
    if (!streams.length) return null;
    const currentDefault = movieDefaultSubtitleStream(item);
    if (currentDefault && streams.includes(currentDefault)) return currentDefault;
    return streams[0];
  }

  function itemDefaultAudioLanguage(item) {
    return audioStreamLanguage(movieDefaultAudioStream(item)) || '';
  }

  function currentSubtitlePolicy() {
    // Legacy policy branch reference retained for test/documentation continuity:
    // subtitlePolicy.englishAudioSubtitles === 'forced_english'
    const preferences = currentPolicyPayload()?.policy?.subtitle_preferences || {};
    const englishAudioSubtitles = ['off', 'forced_english', 'english', 'primary_language'].includes(String(preferences.english_audio_subtitles || '').toLowerCase())
      ? String(preferences.english_audio_subtitles).toLowerCase()
      : 'off';
    const foreignAudioSubtitles = ['forced_english', 'english', 'off'].includes(String(preferences.foreign_audio_subtitles || '').toLowerCase())
      ? String(preferences.foreign_audio_subtitles).toLowerCase()
      : 'forced_english';
    return { englishAudioSubtitles, foreignAudioSubtitles };
  }

  function movieSubtitleReadinessRepairTarget(item) {
    const plan = repairPlanSubtitle(item);
    if (plan) return subtitleStreamByIndex(item, plan.target_stream_index);
    return null;
  }

  // Strict current-default subtitle: only a stream the container actually flags
  // default. Unlike movieDefaultSubtitleStream there is no streams[0] fallback, so
  // a file with no default subtitle reads as "no default" instead of narrating the
  // first track as a phantom default in the preview.
  function strictDefaultSubtitleStream(item) {
    return (item?.facts?.subtitle_streams || []).find(stream => stream?.is_default) || null;
  }

  // Resolve which subtitle plan the chosen action will actually act on, and whether
  // it is second-order (only surfaced because the audio default flips to English in
  // the same remux). For a combined action with a repairable audio stage we trust
  // the planner's post-audio evaluation (combined.subtitle_after_audio); otherwise
  // the first-order top-level subtitle plan governs.
  function effectiveSubtitleStage(item, action) {
    const cfg = repairActionConfig(action);
    if (!cfg.families.includes('subtitle')) return null;
    const touchesAudio = cfg.families.includes('audio');
    const audioRepairable = !!repairPlanAudio(item)?.repairable;
    if (touchesAudio && audioRepairable && repairPlanCombined(item)?.staged) {
      const sub = repairPlanCombinedSubtitle(item);
      if (sub?.repairable) {
        return { plan: sub, secondOrder: !!repairPlanCombined(item)?.second_order_subtitle };
      }
      return null;
    }
    const sub = repairPlanSubtitle(item);
    if (sub?.repairable) return { plan: sub, secondOrder: false };
    return null;
  }

  // Pure projection of the planner's decision into preview nodes. The renderer is a
  // dumb consumer of this model: every node resolves to exactly one of three states
  // — a confident change, an intentional no-op, or an explicit `unresolved` node
  // when the planner staged a change whose stream descriptor cannot be resolved.
  // Nothing is silently dropped, so unmodelled edge cases announce themselves.
  function buildRepairPreviewModel(item, action) {
    const cfg = repairActionConfig(action);
    const touchesAudio = cfg.families.includes('audio');
    const touchesSubtitle = cfg.families.includes('subtitle');
    const dropForeignAudio = !!cfg.dropForeignAudio;
    const nodes = [];

    if (touchesAudio) {
      const audioPlan = repairPlanAudio(item);
      if (audioPlan?.repairable) {
        const currentDefault = movieDefaultAudioStream(item);
        const target = movieAudioPackagingTarget(item);
        if (currentDefault) {
          nodes.push({
            path: `audio/default: ${describeAudioStream(currentDefault)}${dropForeignAudio ? ' [default cleared, stream kept if retained]' : ' [default cleared]'}`,
            flags: { mutated: true, staged: true },
          });
        }
        if (target) {
          nodes.push({ path: `audio/default: ${describeAudioStream(target)} [becomes default]`, flags: { mutated: true, landing: true } });
        } else {
          nodes.push({ path: 'audio/default: staged English default — track could not be resolved', flags: { unresolved: true } });
        }
        if (dropForeignAudio) {
          (item?.facts?.audio_streams || [])
            .filter(stream => canonicalAudioLanguageValue(stream.language) && canonicalAudioLanguageValue(stream.language) !== 'english')
            .forEach(stream => nodes.push({ path: `audio/remove: ${describeAudioStream(stream)}`, flags: { deleted: true } }));
        }
      } else {
        nodes.push({ path: 'audio/no change', flags: {} });
      }
    }

    if (touchesSubtitle) {
      const stage = effectiveSubtitleStage(item, action);
      if (stage) {
        const sub = stage.plan;
        const causal = stage.secondOrder ? ' — after audio flips to English' : '';
        const currentDefault = strictDefaultSubtitleStream(item);
        if (currentDefault) {
          nodes.push({ path: `subtitle/default: ${describeSubtitleStream(currentDefault)} [default cleared]`, flags: { mutated: true, staged: true } });
        }
        if (sub.mode === 'clear') {
          nodes.push({ path: `subtitle/default: no subtitle default${causal}`, flags: { mutated: true, landing: true } });
        } else {
          const target = subtitleStreamByIndex(item, sub.target_stream_index);
          if (target) {
            nodes.push({ path: `subtitle/default: ${describeSubtitleStream(target)} [becomes default${causal}]`, flags: { mutated: true, landing: true } });
          } else {
            nodes.push({ path: `subtitle/default: staged default for track #${sub.target_stream_index} — track could not be resolved${causal}`, flags: { unresolved: true } });
          }
        }
      } else {
        nodes.push({ path: 'subtitle/no change', flags: {} });
      }
    }

    return { nodes };
  }

  function movieSubtitleReadinessIsRepairable(item) {
    const plan = repairPlanSubtitle(item);
    return !!plan?.repairable;
  }

  function humanSubtitleReadinessIssueLabel(code) {
    const labels = {
      english_forced_not_default: 'forced English exists but is not default',
      wrong_default_forced_subtitle: 'wrong subtitle is default instead of forced English',
      missing_default_english_subtitle: 'non-English audio but no default English subtitle',
      english_audio_missing_default_english_subtitle: 'English audio should default to a full English subtitle',
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

  function describeSubtitlePolicyTarget(stream, options = {}) {
    if (!stream) return options.clearLabel || 'no subtitle default';
    return `${describeSubtitleStream(stream)} default`;
  }

  function defaultSubtitleStreamsForItem(item) {
    return (item?.facts?.subtitle_streams || []).filter(stream => stream?.is_default);
  }

  function repairDefaultSubtitleLabel(item) {
    const subtitleStreams = item?.facts?.subtitle_streams || [];
    const defaultStreams = defaultSubtitleStreamsForItem(item);
    const defaultCount = defaultStreams.length;
    if (!subtitleStreams.length || defaultCount <= 0) return 'None';
    if (defaultCount > 1) return 'Multiple';
    const stream = defaultStreams[0] || null;
    if (!stream) return 'None';
    const language = displayAudioLanguage(stream.language);
    return stream.is_forced ? `${language} Forced` : language;
  }

  function subtitleTracksForRow(row) {
    return row?.item?.facts?.subtitle_streams || [];
  }

  function movieAudioPackagingTarget(item) {
    const plan = repairPlanAudio(item);
    if (plan) return audioStreamByIndex(item, plan.target_stream_index);
    return movieBestEnglishAudioStream(item);
  }

  function movieCombinedSubtitleRepairTarget(item) {
    const plan = repairPlanCombinedSubtitle(item);
    if (plan) return subtitleStreamByIndex(item, plan.target_stream_index);
    return null;
  }

  function combinedSubtitleWillRun(item) {
    const combined = repairPlanCombined(item);
    return !!combined?.staged && !!combined?.subtitle_after_audio?.repairable;
  }

  function combinedSubtitleChangesAfterAudio(item) {
    return !!repairPlanCombined(item)?.subtitle_changes_after_audio;
  }

  function combinedSubtitleSecondOrder(item) {
    return !!repairPlanCombined(item)?.second_order_subtitle;
  }

  function repairDefaultsSelectionLocked() {
    return state.audioFixBusy || state.subtitleFixBusy;
  }

  function activityPayloadHasRemux(payload = state.activityPayload) {
    const appItems = Array.isArray(payload?.app) ? payload.app : [];
    if (appItems.some(item => item?.kind === 'remux')) return true;
    const externalItems = Array.isArray(payload?.external) ? payload.external : [];
    return externalItems.some(item => {
      const command = String(item?.command || '').trim().toLowerCase();
      const summary = String(item?.summary || '').trim().toLowerCase();
      return command === 'ffmpeg' || summary.includes('ffmpeg');
    });
  }

  function repairWorkflowBusy() {
    return state.audioFixBusy || state.subtitleFixBusy || activityPayloadHasRemux();
  }

  // Scan and activity payloads both carry resolved absolute paths (the source root
  // is resolve()'d up front and discovery skips symlinks), so card paths and the
  // remux item's current_path are the same string. Trim only for defensive equality.
  function normalizePathKey(path) {
    return String(path || '').trim().replace(/\/+$/, '');
  }

  function remuxActivityCurrentPath(payload = state.activityPayload) {
    const appItems = Array.isArray(payload?.app) ? payload.app : [];
    const remux = appItems.find(item => item?.kind === 'remux' && item?.current_path);
    return remux ? normalizePathKey(remux.current_path) : '';
  }

  // The single remux item's current_path advances file-by-file, but not
  // necessarily in card order — the backend may walk the queue however it likes.
  // So we can't infer "done" from a card's position relative to the active one;
  // instead we record each path as completed once the focus moves off it (and the
  // last one when the remux item disappears). Hold the last known target across
  // the brief gaps between files so the focus doesn't flicker mid-chain.
  function updateRemuxFocusPath() {
    if (!activityPayloadHasRemux()) {
      if (state.activeRemuxPath) state.completedRemuxPaths.add(state.activeRemuxPath);
      state.activeRemuxPath = '';
      return;
    }
    const current = remuxActivityCurrentPath();
    if (current && current !== state.activeRemuxPath) {
      if (state.activeRemuxPath) state.completedRemuxPaths.add(state.activeRemuxPath);
      state.activeRemuxPath = current;
    }
  }

  function safeRepairLockOverlayEnabled() {
    return isRepairDefaultsMode() && repairWorkflowBusy() && currentWarningGateSafetyLevel() === 'safe';
  }

  function updateRepairLockOverlay() {
    if (!el.repairLockOverlay || !el.previewPage) return;
    const enabled = safeRepairLockOverlayEnabled();
    el.repairLockOverlay.hidden = !enabled;
    if (!enabled) return;
    closeTrackPopover();
    const rect = el.previewPage.getBoundingClientRect();
    const inset = 8;
    const top = Math.max(Math.round(rect.top - inset), 0);
    const left = Math.max(Math.round(rect.left - inset), 0);
    const right = Math.min(Math.round(rect.right + inset), window.innerWidth);
    const bottom = Math.min(Math.round(rect.bottom + inset), window.innerHeight);
    el.repairLockOverlay.style.setProperty('--lock-top', `${top}px`);
    el.repairLockOverlay.style.setProperty('--lock-left', `${left}px`);
    el.repairLockOverlay.style.setProperty('--lock-right', `${right}px`);
    el.repairLockOverlay.style.setProperty('--lock-bottom', `${bottom}px`);
  }

  function actionTouchesFamily(action, family) {
    return repairActionConfig(action).families.includes(family);
  }

  function actionTouchesAudio(action = state.repairAction) {
    return actionTouchesFamily(action, 'audio');
  }

  function actionTouchesSubtitle(action = state.repairAction) {
    return actionTouchesFamily(action, 'subtitle');
  }

  function actionSupportsDelete(action = state.repairAction) {
    return repairActionConfig(action).destructiveDelete;
  }

  function rowTouchesFamily(row, family) {
    return Array.isArray(row?.issue_families) && row.issue_families.includes(family);
  }

  function rowSupportsAudioAction(row) {
    return rowTouchesFamily(row, 'audio');
  }

  function rowSupportsSubtitleAction(row) {
    return rowTouchesFamily(row, 'subtitle');
  }

  function rowSupportsCombinedRepairAction(row) {
    return rowSupportsAudioAction(row) && (rowSupportsSubtitleAction(row) || combinedSubtitleWillRun(row?.item));
  }

  function repairRowMatchesAction(row, action = state.repairAction) {
    if (actionTouchesAudio(action) && actionTouchesSubtitle(action)) {
      return rowSupportsCombinedRepairAction(row);
    }
    if (actionTouchesAudio(action)) return rowSupportsAudioAction(row);
    if (actionTouchesSubtitle(action)) return rowSupportsSubtitleAction(row);
    return false;
  }

  function issueFamilyLabel(families) {
    if (!Array.isArray(families) || !families.length) return '';
    if (families.length === 2) return 'Audio + Subtitle';
    return families[0] === 'audio' ? 'Audio' : 'Subtitle';
  }

  function repairItemMatchesAction(item, action = state.repairAction) {
    return (actionTouchesAudio(action) && !!movieAudioPackagingIssueCode(item))
      || (actionTouchesSubtitle(action) && movieSubtitleReadinessIsRepairable(item));
  }

  function renderWorkflowHeader() {
    el.workflowTitle.textContent = WORKFLOW_LABELS[state.workflow];
    el.workflowDescription.textContent = WORKFLOW_DESCRIPTIONS[state.workflow];
    el.workflowButton.dataset.active = surfaceOpen() ? 'false' : 'true';
    el.workflowNormalize.classList.toggle('is-active', state.workflow === 'normalize');
    el.workflowWeakEncodes.classList.toggle('is-active', state.workflow === 'weak-encodes');
    el.workflowRepairDefaults.classList.toggle('is-active', state.workflow === 'repair-defaults');
    el.workflowCanonicalLists.classList.toggle('is-active', state.workflow === 'canonical-lists');
    el.workflowImmersive.classList.toggle('is-active', state.workflow === 'format-upgrades');
    el.workflowJunk.classList.toggle('is-active', state.workflow === 'junk');
    el.workflowButton.disabled = repairWorkflowBusy();
    [el.workflowNormalize, el.workflowWeakEncodes, el.workflowRepairDefaults, el.workflowCanonicalLists, el.workflowImmersive, el.workflowJunk].forEach(button => {
      button.disabled = repairWorkflowBusy();
    });
  }

  function renderShellLayout() {
    if (el.shell) el.shell.dataset.layoutMode = state.layoutMode;
    if (el.shell) el.shell.dataset.policyMode = surfaceOpen() ? 'editing' : 'default';
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
    const canonical = state.workflow === 'canonical-lists';
    const immersive = state.workflow === 'format-upgrades';
    const junk = state.workflow === 'junk';
    el.runButton.textContent = state.runInFlight ? 'Running' : (normalize ? 'Run Normalize Movie Library Naming' : (repairDefaults ? 'Run Fix Audio and Subtitle Defaults' : (canonical ? 'Run Compare Against Canonical Lists' : (immersive ? 'Run Review Format Upgrade Candidates' : (junk ? 'Run Remove Junk Files' : 'Run Review Low-Quality Encodes')))));
    el.runButton.disabled = state.runInFlight || repairWorkflowBusy();
    el.runButton.classList.toggle('is-running', state.runInFlight);
  }

  function renderFilterVisibility() {
    const weak = isWeakMode();
    const repairDefaults = isRepairDefaultsMode();
    const canonical = isCanonicalMode();
    const immersive = isImmersiveMode();
    const junk = isJunkMode();
    if (el.filterBar) el.filterBar.hidden = false;
    el.bucketFilter.hidden = weak || repairDefaults || canonical || immersive || junk;
    el.workflowStatusFilter.hidden = !(weak || repairDefaults || junk);
    el.canonicalListFilter.hidden = !canonical;
    el.traitFilter.hidden = !immersive;
    el.traitStatusFilter.hidden = !immersive;
    el.selectAllButton.hidden = canonical || immersive;
    el.deselectAllButton.hidden = canonical || immersive;
    renderWorkflowStatusFilter();
    renderCanonicalListFilter();
    renderWeakFloorControl();
    renderWorkflowActionControls();
  }

  function renderCanonicalListFilter() {
    if (!el.canonicalListFilter) return;
    const inertPlaceholders = '<option value="anime" disabled>Anime</option><option value="tv_shows" disabled>TV Shows</option>';
    if (!isCanonicalMode()) {
      el.canonicalListFilter.innerHTML = `${canonicalFallbackOptionsMarkup()}${inertPlaceholders}`;
      return;
    }
    const lists = canonicalListsForPayload();
    const options = lists.length
      ? lists.map(item => `<option value="${escapeHtml(item.id || '')}">${escapeHtml(item.label || item.id || 'List')}</option>`).join('')
      : canonicalFallbackOptionsMarkup();
    el.canonicalListFilter.innerHTML = `${options}${inertPlaceholders}`;
    const active = activeCanonicalListSummary();
    state.canonicalSelectedListId = active?.id || state.canonicalSelectedListId || 'top_100';
    el.canonicalListFilter.value = state.canonicalSelectedListId;
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
      const options = REPAIR_STATUS_FILTER_OPTIONS;
      el.workflowStatusFilter.innerHTML = options.map(([value, label]) => `<option value="${escapeHtml(value)}">${escapeHtml(label)}</option>`).join('');
      const valid = options.map(([value]) => value);
      if (!valid.includes(el.workflowStatusFilter.value)) el.workflowStatusFilter.value = 'all';
    }
  }

  function renderWorkflowActionControls() {
    const repairMode = isRepairDefaultsMode();
    el.repairActionControls.hidden = !repairMode;
    el.previewControls.classList.remove('is-repair-delete-leading');
    if (!repairMode) {
      el.repairActionSelect.innerHTML = '';
      el.repairActionButton.disabled = true;
      return;
    }
    const selection = selectedRepairApplicability();
    const selectedCount = selection.selectedRows.length;
    const locked = repairDefaultsSelectionLocked();
    const config = repairActionConfig();
    const busy = locked;
    const options = repairActionOptions().map(option => ({
      ...option,
      applicableCount: selection.selectedRows.length ? selectedRepairRowsForAction(option.value).length : state.filteredRows.filter(row => repairRowMatchesAction(row, option.value)).length,
    }));
    if (!options.some(option => option.value === state.repairAction)) {
      state.repairAction = defaultRepairAction();
    }
    el.repairActionSelect.innerHTML = options.map(option => (
      `<option value="${escapeHtml(option.value)}" ${selection.selectedRows.length && !option.applicableCount ? 'disabled' : ''}>${escapeHtml(repairActionOptionLabel(option.value, selectedCount, option.applicableCount))}</option>`
    )).join('');
    el.repairActionSelect.value = state.repairAction;
    el.repairActionButton.classList.add('lab-action-button');
    el.repairActionButton.classList.remove('is-primary', 'is-caution');
    el.repairActionButton.classList.add(config.buttonClass);
    el.repairActionButton.textContent = locked ? config.busyText : config.buttonText;
    el.repairActionSelect.disabled = locked || busy;
    el.repairActionButton.disabled = !selection.applicableRows.length || locked || busy;
  }

  function renderWeakFloorControl() {
    syncWeakFloorState();
  }

  function currentWeakFloorLabel() {
    const options = weakFloorDefinitionOptions();
    return options.find(option => option.value === state.weakFloor)?.label || humanProfileLabel(state.weakFloor);
  }

  function policyDefinitionDraft(label) {
    return state.policyDrafts[label] || null;
  }

  function policyDefinitionFields(definition) {
    return (definition.fields || []).map(field => {
      const draft = policyDefinitionDraft(definition.label);
      const hasDraft = !!draft && Object.prototype.hasOwnProperty.call(draft, field.key);
      const value = hasDraft ? draft[field.key] : field.value;
      if (field.type === 'select') {
        return `
          <div class="lab-policy-field">
            <label for="policy-field-${escapeHtml(definition.label)}-${escapeHtml(field.key)}">${escapeHtml(field.label)}</label>
            <select id="policy-field-${escapeHtml(definition.label)}-${escapeHtml(field.key)}" data-policy-field="${escapeHtml(field.key)}">
              ${(field.options || []).map(option => `<option value="${escapeHtml(option.value)}" ${String(option.value) === String(value) ? 'selected' : ''}>${escapeHtml(option.label)}</option>`).join('')}
            </select>
          </div>
        `;
      }
      return `
        <div class="lab-policy-field">
          <label for="policy-field-${escapeHtml(definition.label)}-${escapeHtml(field.key)}">${escapeHtml(field.label)}</label>
          <input id="policy-field-${escapeHtml(definition.label)}-${escapeHtml(field.key)}" data-policy-field="${escapeHtml(field.key)}" type="text" value="${escapeHtml(value)}">
        </div>
      `;
    }).join('');
  }

  function railIconSvg(name) {
    if (name === 'scroll-text') {
      return '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 12h-5" /><path d="M15 8h-5" /><path d="M19 17V5a2 2 0 0 0-2-2H4" /><path d="M8 21h12a2 2 0 0 0 2-2v-1a1 1 0 0 0-1-1H11a1 1 0 0 0-1 1v1a2 2 0 1 1-4 0V5a2 2 0 1 0-4 0v2a1 1 0 0 0 1 1h3" /></svg>';
    }
    if (name === 'layout-grid') {
      return '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /></svg>';
    }
    if (name === 'list-indent-decrease') {
      return '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 5H11" /><path d="M21 12H11" /><path d="M21 19H11" /><path d="m7 8-4 4 4 4" /></svg>';
    }
    if (name === 'clipboard-paste') {
      return '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M11 14h10" /><path d="M16 4h2a2 2 0 0 1 2 2v1.344" /><path d="m17 18 4-4-4-4" /><path d="M8 4H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 1.793-1.113" /><rect x="8" y="2" width="8" height="4" rx="1" /></svg>';
    }
    if (name === 'clipboard-copy') {
      return '<svg viewBox="0 0 24 24" aria-hidden="true"><rect width="8" height="4" x="8" y="2" rx="1" ry="1" /><path d="M8 4H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" /><path d="M16 4h2a2 2 0 0 1 2 2v4" /><path d="M21 14H11" /><path d="m15 10-4 4 4 4" /></svg>';
    }
    if (name === 'ellipsis') {
      return '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="1" /><circle cx="19" cy="12" r="1" /><circle cx="5" cy="12" r="1" /></svg>';
    }
    if (name === 'trophy') {
      return '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 21h8" /><path d="M12 17v4" /><path d="M7 4h10v3a5 5 0 0 1-5 5 5 5 0 0 1-5-5V4Z" /><path d="M17 5h2a2 2 0 0 1 2 2 5 5 0 0 1-5 5" /><path d="M7 5H5a2 2 0 0 0-2 2 5 5 0 0 0 5 5" /></svg>';
    }
    if (name === 'settings') {
      return '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12.22 2h-.44a2 2 0 0 0-1.94 1.5l-.23.94a2 2 0 0 1-1.43 1.43l-.94.23A2 2 0 0 0 5.74 8v.44a2 2 0 0 1-.59 1.41l-.67.67a2 2 0 0 0 0 2.83l.67.67a2 2 0 0 1 .59 1.41V16a2 2 0 0 0 1.5 1.94l.94.23a2 2 0 0 1 1.43 1.43l.23.94a2 2 0 0 0 1.94 1.5h.44a2 2 0 0 0 1.94-1.5l.23-.94a2 2 0 0 1 1.43-1.43l.94-.23a2 2 0 0 0 1.5-1.94v-.44a2 2 0 0 1 .59-1.41l.67-.67a2 2 0 0 0 0-2.83l-.67-.67a2 2 0 0 1-.59-1.41V8a2 2 0 0 0-1.5-1.94l-.94-.23a2 2 0 0 1-1.43-1.43l-.23-.94A2 2 0 0 0 12.22 2z" /><circle cx="12" cy="12" r="3" /></svg>';
    }
    if (name === 'download') {
      return '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><path d="M7 10l5 5 5-5" /><path d="M12 15V3" /></svg>';
    }
    if (name === 'arrow-big-left') {
      return '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m11 19-7-7 7-7" /><path d="M4 12h16" /></svg>';
    }
    return '';
  }

  function renderPolicyRail() {
    const toggleLabel = policySurfaceOpen() ? 'Close Policy' : 'Open Policy';
    el.policyToggle.setAttribute('aria-label', toggleLabel);
    el.policyToggle.setAttribute('title', toggleLabel);
    el.policyToggle.setAttribute('aria-pressed', policySurfaceOpen() ? 'true' : 'false');
    el.policyToggle.dataset.active = policySurfaceOpen() ? 'true' : 'false';
    el.policyToggle.innerHTML = railIconSvg('scroll-text');
    if (el.dashboardToggle) {
      const dashboardLabel = dashboardSurfaceOpen() ? 'Close Dashboard' : 'Open Dashboard';
      el.dashboardToggle.setAttribute('aria-label', dashboardLabel);
      el.dashboardToggle.setAttribute('title', dashboardLabel);
      el.dashboardToggle.setAttribute('aria-pressed', dashboardSurfaceOpen() ? 'true' : 'false');
      el.dashboardToggle.dataset.active = dashboardSurfaceOpen() ? 'true' : 'false';
      el.dashboardToggle.innerHTML = railIconSvg('layout-grid');
    }
    const auditLabel = auditSurfaceOpen() ? 'Close Audit' : 'Open Audit';
    el.auditToggle.setAttribute('aria-label', auditLabel);
    el.auditToggle.setAttribute('title', auditLabel);
    el.auditToggle.setAttribute('aria-pressed', auditSurfaceOpen() ? 'true' : 'false');
    el.auditToggle.dataset.active = auditSurfaceOpen() ? 'true' : 'false';
    el.auditToggle.innerHTML = railIconSvg('clipboard-paste');
    if (el.placeholderToggle) {
      el.placeholderToggle.setAttribute('aria-label', 'Placeholder');
      el.placeholderToggle.setAttribute('title', 'Placeholder');
      el.placeholderToggle.setAttribute('aria-pressed', 'false');
      el.placeholderToggle.dataset.active = 'false';
      el.placeholderToggle.innerHTML = railIconSvg('trophy');
    }
    if (el.settingsToggle) {
      const settingsLabel = settingsSurfaceOpen() ? 'Close Settings' : 'Open Settings';
      el.settingsToggle.setAttribute('aria-label', settingsLabel);
      el.settingsToggle.setAttribute('title', settingsLabel);
      el.settingsToggle.setAttribute('aria-pressed', settingsSurfaceOpen() ? 'true' : 'false');
      el.settingsToggle.dataset.active = settingsSurfaceOpen() ? 'true' : 'false';
      el.settingsToggle.innerHTML = railIconSvg('settings');
    }
    if (el.placeholderDownloadToggle) {
      const sourceReady = Boolean(normalizeSourceKey(el.sourcePath.value));
      const exportBusy = state.catalogueExportInFlight;
      const exportLabel = exportBusy ? 'Exporting Catalogue' : 'Export Catalogue';
      el.placeholderDownloadToggle.setAttribute('aria-label', exportLabel);
      el.placeholderDownloadToggle.setAttribute('title', sourceReady ? exportLabel : 'Export Catalogue');
      el.placeholderDownloadToggle.setAttribute('aria-pressed', 'false');
      el.placeholderDownloadToggle.dataset.active = 'false';
      el.placeholderDownloadToggle.disabled = !sourceReady || exportBusy;
      el.placeholderDownloadToggle.innerHTML = railIconSvg('download');
    }
  }

  function formatDashboardRuntime(minutes) {
    const total = Number(minutes || 0);
    if (!total) return '—';
    const hours = Math.floor(total / 60);
    const mins = Math.round(total % 60);
    return hours ? `${hours}h ${mins}m` : `${mins}m`;
  }

  function formatDashboardVideoBitrate(kbps) {
    const total = Number(kbps || 0);
    return total ? `${(total / 1000).toFixed(1)} Mbps` : '—';
  }

  function dashboardMetricCard(label, value) {
    return `
      <section class="lab-policy-card">
        <div class="lab-dashboard-metric-value">${escapeHtml(value)}</div>
        <div class="lab-dashboard-metric-label">${escapeHtml(label)}</div>
      </section>
    `;
  }

  function dashboardBreakdownCard(group, rows) {
    return `
      <section class="lab-policy-card">
        <div class="lab-policy-meta">
          <span class="lab-kicker">${escapeHtml(group)}</span>
        </div>
        <div class="lab-dashboard-list">
          ${rows.length ? rows.map(row => `
            <div class="lab-dashboard-row">
              <span class="lab-dashboard-row-label">${escapeHtml(row.label)}</span>
              <span class="lab-dashboard-row-value">${escapeHtml(row.value)}</span>
            </div>
          `).join('') : '<div class="lab-dashboard-row"><span class="lab-dashboard-row-label">No data</span><span class="lab-dashboard-row-value">—</span></div>'}
        </div>
      </section>
    `;
  }

  function dashboardImprovementRows(metrics) {
    const filesRemoved = metrics?.files_removed || {};
    const audioRemoved = metrics?.audio_tracks_removed || {};
    const canonicalTop500 = metrics?.canonical_top_500_above_floor || {};
    const canonicalImprovement = metrics?.canonical_improvement || {};
    const canonicalValue = canonicalImprovement.percent != null
      ? `${canonicalImprovement.percent}% · ${canonicalImprovement.baseline_count || 0}/500 -> ${canonicalImprovement.latest_count || 0}/500`
      : (canonicalTop500.count != null ? `${canonicalTop500.count}/500` : '—');
    return [
      {
        label: 'Non-audio files removed',
        value: `${Number(filesRemoved.count || 0).toLocaleString()} · ${formatFileSize(filesRemoved.total_bytes || 0)}`,
      },
      {
        label: 'Audio tracks removed',
        value: `${Number(audioRemoved.count || 0).toLocaleString()} · ${formatFileSize(audioRemoved.total_bytes || 0)}`,
      },
      {
        label: 'Canonical improvement',
        value: canonicalValue,
      },
      {
        label: 'Total scans performed',
        value: Number(metrics?.total_scans_performed || 0).toLocaleString(),
      },
      {
        label: 'Current Top 500 above weak floor',
        value: canonicalTop500.count != null ? `${canonicalTop500.count}/500` : '—',
      },
    ];
  }

  function dashboardBreakdownRows(counts, total, labels, options = {}) {
    const resolveLabel = typeof options.resolveLabel === 'function'
      ? options.resolveLabel
      : entry => (typeof entry === 'string' ? humanProfileLabel(entry) : entry.label);
    const rows = labels.map(entry => {
      const key = typeof entry === 'string' ? entry : entry.key;
      const label = resolveLabel(entry);
      const count = Number(counts?.[key] || 0);
      const share = total ? `${((count / total) * 100).toFixed(1)}%` : '0.0%';
      return {
        count,
        label,
        value: `${count.toLocaleString()} · ${share}`,
      };
    });
    return options.hideZero ? rows.filter(row => row.count > 0) : rows;
  }

  function dashboardResolutionBreakdownKey(item) {
    const facts = item?.facts || {};
    const resolution = String(facts.resolution_bucket || '').trim().toLowerCase();
    const width = Number(facts.width || 0);
    const height = Number(facts.height || 0);
    const sar = String(facts.sample_aspect_ratio || '').trim();
    const dar = String(facts.display_aspect_ratio || '').trim();
    const squarePixels = !sar || sar === '1:1';
    let aspectRatio = 0;
    if (dar.includes(':')) {
      const [left, right] = dar.split(':').map(Number);
      if (left > 0 && right > 0) aspectRatio = left / right;
    }
    if (!aspectRatio && width > 0 && height > 0) {
      aspectRatio = width / height;
      if (!squarePixels && sar.includes(':')) {
        const [left, right] = sar.split(':').map(Number);
        if (left > 0 && right > 0) aspectRatio = (width * left / right) / height;
      }
    }

    if (resolution === '2160p' || resolution === '1080p' || resolution === '720p') {
      if (!squarePixels && aspectRatio >= 1.7) return `${resolution}_anamorphic`;
      if (aspectRatio >= 1.7) return `${resolution}_letterbox`;
      return `${resolution}_standard`;
    }
    return 'unknown';
  }

  function dashboardSurroundBreakdownKey(item) {
    const facts = item?.facts || {};
    const channels = Number(facts.audio_channels || 0);
    const immersive = String(facts.audio_immersive_extension || '').trim().toLowerCase();
    const summary = String(facts.audio_summary || '').trim().toLowerCase();
    if (!channels) return 'unknown';
    if (channels === 1) return 'mono_archive';
    if (channels === 2) return 'stereo_ltrt';
    if (channels === 3) return 'three_channel_stage';
    if (channels === 4) return 'quad_matrix';
    if (channels === 5) return 'five_channel_surround';
    if (channels === 6) return 'five_one_surround';
    if (channels === 7) return 'six_one_surround';
    if (immersive === 'atmos' || summary.includes('atmos')) return 'seven_one_atmos';
    if (immersive === 'dtsx' || summary.includes('dts:x')) return 'seven_one_dtsx';
    return 'seven_one_surround';
  }

  function movieBreakdownCounts(items, keyFn) {
    return (Array.isArray(items) ? items : []).reduce((counts, item) => {
      const key = keyFn(item);
      counts[key] = Number(counts[key] || 0) + 1;
      return counts;
    }, {});
  }

  function renderDashboardPanel() {
    if (!dashboardSurfaceOpen()) {
      el.dashboardPanel.innerHTML = '';
      return;
    }
    const payload = currentDashboardPayload();
    if (!payload) {
      el.dashboardPanel.innerHTML = `
        <div class="lab-policy-header">
          <div class="lab-policy-heading">
            <div class="lab-kicker">Dashboard View</div>
            <h2>Profile scan required</h2>
            <p>Dashboard currently reuses the latest profile-bearing scan for this source. Run Review Low-Quality Encodes, Fix Audio and Subtitle Defaults, or Compare Against Canonical Lists first.</p>
          </div>
        </div>
      `;
      return;
    }
    const histogram = payload.histogram || {};
    const total = Number(histogram.movie_count ?? ((payload.movies || []).length));
    const movieResolutionCounts = movieBreakdownCounts(payload.movies || [], dashboardResolutionBreakdownKey);
    const movieSurroundCounts = movieBreakdownCounts(payload.movies || [], dashboardSurroundBreakdownKey);
    const qualityRows = dashboardBreakdownRows(
      histogram.quality_profile_counts || {},
      total,
      ['standard_definition', 'compact_grade', 'library_grade', 'collector_grade', 'reference'],
      { resolveLabel: entry => qualityProfileDisplayLabel(entry) },
    );
    const improvementRows = dashboardImprovementRows(payload.library_improvement_metrics || {});
    const resolutionRows = dashboardBreakdownRows(
      Object.keys(histogram.resolution_breakdown_counts || {}).length ? histogram.resolution_breakdown_counts : movieResolutionCounts,
      total,
      [
        { key: '2160p_anamorphic', label: '4K Anamorphic' },
        { key: '2160p_letterbox', label: '4K Letterbox' },
        { key: '2160p_standard', label: '4K Standard' },
        { key: '1080p_anamorphic', label: '1080p Anamorphic' },
        { key: '1080p_letterbox', label: '1080p Letterbox' },
        { key: '1080p_standard', label: '1080p Standard' },
        { key: '720p_anamorphic', label: '720p Anamorphic' },
        { key: '720p_letterbox', label: '720p Letterbox' },
        { key: '720p_standard', label: '720p Standard' },
        { key: 'unknown', label: 'Unknown' },
      ],
      { hideZero: true },
    );
    const surroundSoundRows = dashboardBreakdownRows(
      Object.keys(histogram.surround_sound_breakdown_counts || {}).length ? histogram.surround_sound_breakdown_counts : movieSurroundCounts,
      total,
      [
        { key: 'mono_archive', label: 'Mono Archive' },
        { key: 'stereo_ltrt', label: 'Stereo / LtRt' },
        { key: 'three_channel_stage', label: '3-Channel Stage' },
        { key: 'quad_matrix', label: 'Quad / Matrixed' },
        { key: 'five_channel_surround', label: '5.0 Surround' },
        { key: 'five_one_surround', label: '5.1 Surround' },
        { key: 'six_one_surround', label: '6.1 Surround' },
        { key: 'seven_one_surround', label: '7.1 Surround' },
        { key: 'seven_one_atmos', label: '7.1 Atmos Bed' },
        { key: 'seven_one_dtsx', label: '7.1 DTS:X Bed' },
        { key: 'unknown', label: 'Unknown' },
      ],
      { hideZero: true },
    );
    el.dashboardPanel.innerHTML = `
      <div class="lab-policy-header">
        <div class="lab-policy-heading">
          <div class="lab-kicker">Dashboard View</div>
          <h2>Library visibility snapshot</h2>
          <p>At a glance quality overview of Media Library</p>
        </div>
        <div class="lab-policy-chips">
          <span class="chip">${escapeHtml(fileNameFromPath(payload.source_root || el.sourcePath.value || 'Current source'))}</span>
          <span class="chip">${escapeHtml(total.toLocaleString())} movies</span>
        </div>
      </div>
      <div class="lab-dashboard-metrics">
        ${dashboardMetricCard('Total Size', formatFileSize(histogram.total_size_bytes))}
        ${dashboardMetricCard('Total Runtime', formatDashboardRuntime(histogram.total_runtime_minutes))}
        ${dashboardMetricCard('Avg Video Bitrate', formatDashboardVideoBitrate(histogram.video_bitrate_kbps?.mean))}
        ${dashboardMetricCard('Avg Audio Bitrate', formatBitrate(histogram.audio_bitrate_kbps?.mean))}
      </div>
      <div class="lab-dashboard-breakdowns">
        ${dashboardBreakdownCard('Quality Profile Breakdown', qualityRows)}
        ${dashboardBreakdownCard('Library Improvement Metrics', improvementRows)}
        ${dashboardBreakdownCard('Resolution Breakdown', resolutionRows)}
        ${dashboardBreakdownCard('Surround Sound Breakdown', surroundSoundRows)}
      </div>
    `;
  }

  function currentPolicyEditorRenderKey(definitions) {
    return JSON.stringify({
      surfaceMode: state.surfaceMode,
      section: state.policySectionLabel,
      busy: state.policyBusy,
      drafts: state.policyDrafts,
      definitions,
      lopsidedDraft: state.lopsidedDraft,
      lopsidedView: state.lopsidedView,
      lopsidedBusy: state.lopsidedBusy,
      lopsidedRev: lopsidedRevision(),
    });
  }

  function renderPolicyEditor() {
    const definitions = currentPolicyDefinitions();
    if (!policySurfaceOpen()) {
      state.policyEditorRenderKey = '';
      el.policyEditorPanel.innerHTML = '';
      return;
    }
    const renderKey = currentPolicyEditorRenderKey(definitions);
    if (state.policyEditorRenderKey === renderKey) return;
    if (!definitions.length) {
      state.policyEditorRenderKey = renderKey;
      el.policyEditorPanel.innerHTML = `
        <div class="lab-policy-header">
          <div class="lab-policy-heading">
            <div class="lab-kicker">Policy Editor</div>
            <h2>Policy loading required</h2>
            <p>Open policy with a source selected to load the current library policy contract.</p>
          </div>
        </div>
      `;
      return;
    }
    const sections = definitions.map(definition => {
      const isOpen = state.policySectionLabel === definition.label;
      return `
        <section class="lab-policy-card ${isOpen ? 'is-open' : ''}">
          <div class="lab-policy-section-header" data-policy-section="${escapeHtml(definition.label)}" role="button" tabindex="0" aria-expanded="${isOpen ? 'true' : 'false'}">
            <div class="lab-policy-meta">
              <span class="lab-kicker">${escapeHtml(definition.group || 'Policy')}</span>
            </div>
            <h3>${escapeHtml(definition.display_name || humanProfileLabel(definition.label))}</h3>
            <p>${escapeHtml(definition.summary || '')}</p>
            <p>${escapeHtml(definition.rule_summary || '')}</p>
          </div>
          ${isOpen ? `
            <div class="lab-policy-fields" data-policy-editor="${escapeHtml(definition.label)}">${policyDefinitionFields(definition)}</div>
            <div class="lab-policy-actions">
              <button id="policySaveButton" class="lab-action-button is-primary" type="button" data-policy-save="${escapeHtml(definition.label)}" ${state.policyBusy ? 'disabled' : ''}>Save</button>
              <button type="button" data-policy-reset="${escapeHtml(definition.label)}" ${state.policyBusy ? 'disabled' : ''}>Reset</button>
            </div>
          ` : ''}
        </section>
      `;
    }).join('');
    el.policyEditorPanel.innerHTML = `
      <div class="lab-policy-header">
        <div class="lab-policy-heading">
          <div class="lab-kicker">Policy Editor</div>
          <p>Define global policies for your media library that will be enforced by the repair workflows.</p>
        </div>
      </div>
      <div class="lab-policy-sections">${sections}${lopsidedPolicySection()}</div>
    `;
    state.policyEditorRenderKey = renderKey;
    el.policyEditorPanel.querySelectorAll('[data-policy-section]').forEach(section => {
      const toggle = () => {
        const label = section.dataset.policySection || '';
        state.policySectionLabel = state.policySectionLabel === label ? '' : label;
        renderPolicyEditor();
      };
      section.addEventListener('click', toggle);
      section.addEventListener('keydown', event => {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        event.preventDefault();
        toggle();
      });
    });
    el.policyEditorPanel.querySelectorAll('[data-policy-reset]').forEach(button => {
      button.addEventListener('click', () => {
        delete state.policyDrafts[button.dataset.policyReset || ''];
        renderPolicyEditor();
      });
    });
    el.policyEditorPanel.querySelectorAll('[data-policy-save]').forEach(button => {
      button.addEventListener('click', () => savePolicyDefinition(button.dataset.policySave || ''));
    });
    el.policyEditorPanel.querySelectorAll('[data-policy-editor]').forEach(editor => {
      editor.querySelectorAll('[data-policy-field]').forEach(input => {
        input.addEventListener('change', () => {
          const label = editor.dataset.policyEditor || '';
          state.policyDrafts[label] = policyEditorValues(label);
        });
      });
    });
    wireLopsidedPolicySection();
  }

  function policyEditorValues(label) {
    const editor = document.querySelector(`[data-policy-editor="${label}"]`);
    if (!editor) return {};
    const values = {};
    editor.querySelectorAll('[data-policy-field]').forEach(input => {
      const key = input.dataset.policyField;
      if (key) values[key] = input.value;
    });
    return values;
  }

  async function savePolicyDefinition(label) {
    const payload = currentPolicyPayload();
    if (!label || !payload || state.policyBusy) return;
    state.policyBusy = true;
    state.policyDrafts[label] = policyEditorValues(label);
    renderPolicyEditor();
    try {
      const result = await postJson('/api/policy/update', {
        label,
        values: state.policyDrafts[label],
        source: normalizeSourceKey(el.sourcePath.value),
        policy_revision: payload.policy_revision || '',
        operator_preferences_revision: payload.operator_preferences_revision || '',
      });
      applyPolicyPayload(result);
      markAuditLedgerDirty();
      delete state.policyDrafts[label];
      if (label === 'default_source') {
        const nextSource = preferredDefaultSource();
        el.sourcePath.value = nextSource;
        if (nextSource) {
          state.surfaceMode = 'audit';
          await refreshAuditPayload({ immediate: true });
        }
      }
      if (label !== 'default_source' && el.sourcePath.value.trim()) {
        const surfaceDismissed = dismissActiveSurface();
        if (surfaceDismissed) {
          renderFilterVisibility();
          renderRows();
          renderSidePanel();
        }
        if (isWeakMode()) await runWeakEncodes();
        else if (isRepairDefaultsMode()) await runRepairDefaults();
        else if (isJunkMode() && label === 'library_defaults') await runJunk();
      }
    } catch (error) {
      el.inspectionPane.textContent = error.message;
    } finally {
      state.policyBusy = false;
      renderPolicyRail();
      renderPolicyEditor();
      renderSidePanel();
    }
  }

  async function ensurePolicyPayload() {
    if (currentPolicyDefinitions().length) return currentPolicyPayload();
    const payload = await postJson('/api/policy/read', {});
    applyPolicyPayload(payload);
    return payload;
  }

  async function openPolicySection(label) {
    await ensurePolicyPayload();
    state.policySectionLabel = label || '';
    state.surfaceMode = 'policy';
    renderFilterVisibility();
    renderRows();
    renderSidePanel();
  }

  async function togglePolicyEditor() {
    if (policySurfaceOpen()) {
      state.surfaceMode = 'default';
      renderFilterVisibility();
      renderRows();
      renderSidePanel();
      return;
    }
    await openPolicySection(state.policySectionLabel || '');
  }

  function handlePolicyToggleError(error) {
    el.inspectionPane.textContent = error.message;
  }

  const SETTINGS_KEY_FIELDS = [
    {
      field: 'omdb',
      name: 'OMDb API key',
      summary: 'Enables IMDb rating lookups and original-language detection for foreign-audio defaults. Optional — absence simply disables that enrichment.',
    },
    {
      field: 'tmdb',
      name: 'TMDb API key',
      summary: 'Alternate canonical-list provider. Optional — canonical lists otherwise run off the local IMDb dataset.',
    },
  ];

  function settingsSourceLabel(source) {
    if (source === 'env') return 'from environment';
    if (source === 'saved') return 'from saved file';
    return '';
  }

  function settingsKeyStatusLine(status) {
    if (!status || !status.present) return 'No key set — optional enrichment.';
    const origin = settingsSourceLabel(status.source);
    const suffix = origin ? ` (${origin})` : '';
    return `Key saved ••••${escapeHtml(status.last4 || '')}${suffix}.`;
  }

  function currentSettingsRenderKey() {
    return JSON.stringify({
      status: state.settingsStatus,
      funMode: state.funMode,
      busy: state.settingsBusy,
    });
  }

  function renderSettingsPanel() {
    if (!settingsSurfaceOpen()) {
      state.settingsRenderKey = '';
      el.settingsPanel.innerHTML = '';
      return;
    }
    const renderKey = currentSettingsRenderKey();
    if (state.settingsRenderKey === renderKey) return;
    const keys = state.settingsStatus || {};
    const cards = SETTINGS_KEY_FIELDS.map(spec => {
      const status = keys[spec.field];
      const present = Boolean(status && status.present);
      return `
        <section class="lab-policy-card is-open">
          <div class="lab-policy-meta"><span class="lab-kicker">API key</span></div>
          <h3>${escapeHtml(spec.name)}</h3>
          <p>${escapeHtml(spec.summary)}</p>
          <p>${settingsKeyStatusLine(status)}</p>
          <div class="lab-policy-fields">
            <div class="lab-policy-field">
              <label for="settings-field-${spec.field}">${present ? 'Replace key' : 'Paste key'}</label>
              <input id="settings-field-${spec.field}" data-settings-field="${spec.field}" type="password" autocomplete="off" spellcheck="false" placeholder="Paste new key">
            </div>
          </div>
          <div class="lab-policy-actions">
            <button class="lab-action-button is-primary" type="button" data-settings-save="${spec.field}" ${state.settingsBusy ? 'disabled' : ''}>Save</button>
            <button type="button" data-settings-clear="${spec.field}" ${state.settingsBusy || !present ? 'disabled' : ''}>Clear</button>
          </div>
        </section>
      `;
    }).join('');
    el.settingsPanel.innerHTML = `
      <div class="lab-policy-header">
        <div class="lab-policy-heading">
          <div class="lab-kicker">Settings</div>
          <p>Manage workbench-wide preferences and optional API keys. Preferences and keys are stored server-side; only the last four key characters are ever shown.</p>
        </div>
      </div>
      <div class="lab-policy-sections">${cards}</div>
    `;
    state.settingsRenderKey = renderKey;
    el.settingsPanel.querySelectorAll('[data-settings-save]').forEach(button => {
      button.addEventListener('click', () => saveSettingsKey(button.dataset.settingsSave || ''));
    });
    el.settingsPanel.querySelectorAll('[data-settings-clear]').forEach(button => {
      button.addEventListener('click', () => clearSettingsKey(button.dataset.settingsClear || ''));
    });
  }

  function applySettings(result) {
    const payload = result || {};
    state.settingsStatus = payload.keys || {};
    state.funMode = Boolean(payload.fun_mode);
    if (state.policyPayload && payload.operator_preferences) {
      state.policyPayload.operator_preferences = {
        ...(state.policyPayload.operator_preferences || {}),
        ...payload.operator_preferences,
      };
      state.policyPayload.operator_preferences_revision = payload.operator_preferences_revision || '';
    }
    if (state.settingsStatus.omdb) {
      window.OMDB_AVAILABLE = Boolean(state.settingsStatus.omdb.present);
    }
  }

  async function fetchSettings() {
    const result = await postJson('/api/settings/read', {});
    applySettings(result);
  }

  async function saveSettingsKey(field) {
    if (!field || state.settingsBusy) return;
    const input = el.settingsPanel.querySelector(`[data-settings-field="${field}"]`);
    const value = (input?.value || '').trim();
    if (!value) return;
    await commitSettingsKey(field, value);
  }

  async function clearSettingsKey(field) {
    if (!field || state.settingsBusy) return;
    await commitSettingsKey(field, '');
  }

  async function commitSettingsKey(field, value) {
    state.settingsBusy = true;
    state.settingsRenderKey = '';
    renderSettingsPanel();
    try {
      const result = await postJson('/api/settings/keys', { [field]: value });
      applySettings(result);
    } catch (error) {
      el.inspectionPane.textContent = error.message;
    } finally {
      state.settingsBusy = false;
      state.settingsRenderKey = '';
      renderSidePanel();
    }
  }

  async function saveSettingsPreference(field, enabled) {
    if (!field || state.settingsBusy) return;
    state.settingsBusy = true;
    state.settingsRenderKey = '';
    renderSettingsPanel();
    try {
      const result = await postJson('/api/settings/preferences', { [field]: enabled });
      applySettings(result);
      renderRows();
    } catch (error) {
      el.inspectionPane.textContent = error.message;
    } finally {
      state.settingsBusy = false;
      state.settingsRenderKey = '';
      renderSidePanel();
    }
  }

  async function toggleSettings() {
    if (settingsSurfaceOpen()) {
      state.surfaceMode = 'default';
      renderFilterVisibility();
      renderRows();
      renderSidePanel();
      return;
    }
    await fetchSettings();
    state.surfaceMode = 'settings';
    state.settingsRenderKey = '';
    renderFilterVisibility();
    renderRows();
    renderSidePanel();
  }

  function formatAuditRecordedAt(value) {
    if (!value) return '—';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString([], {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    });
  }

  function auditSubjectLabel(event) {
    const subjects = Array.isArray(event?.subjects) ? event.subjects : [];
    const subject = subjects[0] || null;
    if (!subject) return '—';
    if (subjects.length > 1) {
      if (subject.kind === 'movie' || subject.kind === 'follow_up') {
        return `Movies · ${subjects.length} titles`;
      }
      if (subject.kind === 'file') {
        return `Files · ${subjects.length} items`;
      }
    }
    const movieLabel = subject.title ? (subject.year ? `${subject.title} (${subject.year})` : subject.title) : '';
    if (subject.kind === 'movie' || subject.kind === 'follow_up') {
      if (movieLabel) return `Movie · ${movieLabel}`;
      if (subject.path) return `Movie · ${fileNameFromPath(subject.path)}`;
      return 'Movie';
    }
    if (subject.kind === 'movie_change') {
      if (movieLabel) return `Normalize Change · ${movieLabel}`;
      const currentValue = String(subject.details?.current_value || '').trim();
      if (currentValue) return `Normalize Change · ${currentValue}`;
      if (subject.path) return `Normalize Change · ${fileNameFromPath(subject.path)}`;
      return 'Normalize Change';
    }
    if (subject.kind === 'file') {
      if (event?.workflow === 'junk') return 'Junk File';
      if (subject.path) return `File · ${fileNameFromPath(subject.path)}`;
      return event?.workflow === 'junk' ? 'Junk File' : 'File';
    }
    if (subject.kind === 'source_root') return 'Library';
    if (subject.kind === 'system') return 'System';
    if (subject.kind === 'policy_definition') {
      const label = String(subject.item_id || '').trim();
      return label ? `Policy · ${policyDefinitionDisplayLabel(label)}` : 'Policy';
    }
    if (subject.kind === 'replacement_queue') return 'Replacement Queue';
    if (subject.kind === 'replacement_completed') return 'Replacement Completed';
    if (subject.kind === 'delete') return 'Deletion Record';
    if (subject.kind === 'repair_review') return 'Repair Review';
    if (movieLabel) return movieLabel;
    if (subject.path) return `Path · ${fileNameFromPath(subject.path)}`;
    if (subject.kind) return humanProfileLabel(subject.kind);
    return '—';
  }

  function auditSubjectTitle(subject) {
    if (!subject) return '—';
    if (subject.title) return subject.year ? `${subject.title} (${subject.year})` : subject.title;
    if (subject.path) return fileNameFromPath(subject.path);
    return humanProfileLabel(subject.kind || 'item');
  }

  function auditActionChipMeta(event) {
    const workflow = String(event?.workflow || '').trim();
    const action = String(event?.action || '').trim();
    if (workflow === 'system' && action === 'start') {
      return { label: 'System Boot', tone: 'is-audit-system-user' };
    }
    if (action === 'repair') {
      return { label: 'Remux Repair', tone: 'is-audit-media-repair' };
    }
    if (action === 'delete') {
      if (workflow === 'junk') return { label: 'Junk Delete', tone: 'is-audit-file' };
      if (workflow === 'weak_encode') return { label: 'Weak Encode Delete', tone: 'is-audit-file' };
      return { label: 'File Delete', tone: 'is-audit-file' };
    }
    if (action === 'apply') {
      return { label: 'Normalize Apply', tone: 'is-audit-file' };
    }
    if (action === 'scan') {
      return { label: 'Scan', tone: 'is-audit-system-user' };
    }
    if (workflow === 'policy' && action === 'update') {
      return { label: 'Policy Update', tone: 'is-audit-system-user' };
    }
    if (action === 'export') {
      return { label: 'Catalogue Export', tone: 'is-audit-system-user' };
    }
    if (action === 'telemetry_vote') {
      return { label: 'Telemetry Vote', tone: 'is-audit-telemetry' };
    }
    if (action === 'trait_observation') {
      return { label: 'Trait Observation', tone: 'is-audit-telemetry' };
    }
    if (action.startsWith('follow_up_')) {
      return { label: 'Follow-up', tone: 'is-audit-system-user' };
    }
    if (action.startsWith('legacy_')) {
      return { label: humanProfileLabel(action), tone: 'is-audit-system-background' };
    }
    return {
      label: humanProfileLabel(action || workflow || 'recorded'),
      tone: workflow === 'system' ? 'is-audit-system-background' : 'is-audit-system-user',
    };
  }

  function auditOutcomeLabel(event) {
    const action = String(event?.action || '').trim();
    const workflow = String(event?.workflow || '').trim();
    const effects = Array.isArray(event?.effects) ? event.effects : [];
    if (workflow === 'system' && action === 'start') return 'System booted';
    if (action === 'scan') return 'Scan performed';
    if (workflow === 'policy' && action === 'update') return 'Policy updated';
    if (action === 'repair') {
      const fileCount = effects.filter(effect => (effect?.status || '') === 'applied' && (effect?.kind || '') === 'remux_repair').length;
      return fileCount > 1 ? `Remux completed for ${fileCount} files` : 'Remux completed';
    }
    if (action === 'delete') {
      const deletedCount = effects.filter(effect => (effect?.status || '') === 'applied').length;
      if (workflow === 'junk') return deletedCount > 1 ? `Deleted ${deletedCount} junk files` : 'Deleted junk file';
      return deletedCount > 1 ? `Deleted ${deletedCount} files` : 'Deleted file';
    }
    if (action.startsWith('follow_up_')) return humanProfileLabel(action);
    if (!effects.length) return event?.reversal?.capability === 'recorded_only' ? 'Recorded reversal' : 'Recorded';
    const lead = effects[0];
    const kind = humanProfileLabel(lead.kind || 'event');
    const status = humanProfileLabel(lead.status || 'recorded');
    return `${kind} · ${status}`;
  }

  function auditRepairFamilyLabels(event) {
    const workflow = String(event?.workflow || '').trim();
    const metadata = event?.metadata || {};
    const labels = [];
    if (workflow === 'audio_packaging' || metadata.include_audio) labels.push('audio default');
    if (metadata.drop_foreign_audio) labels.push('foreign-audio prune');
    if (workflow === 'subtitle_readiness' || metadata.include_subtitle) labels.push('subtitle default');
    return labels;
  }

  function auditRepairFamilySummary(event, effect = null) {
    const labels = auditRepairFamilyLabels(event);
    const parts = labels.length ? [labels.join(' + ')] : ['remux'];
    const removedTracks = Number(effect?.details?.removed_audio_tracks || 0);
    if (removedTracks > 0) {
      parts.push(`removed ${removedTracks} foreign audio track${removedTracks === 1 ? '' : 's'}`);
    }
    return parts.join(' · ');
  }

  function auditRepairBreakdownRows(event) {
    const subjects = Array.isArray(event?.subjects) ? event.subjects : [];
    const effects = Array.isArray(event?.effects) ? event.effects : [];
    const familyLabels = auditRepairFamilyLabels(event);
    if (String(event?.action || '').trim() !== 'repair') return [];
    if (!subjects.length) return [];
    if (subjects.length <= 1 && familyLabels.length <= 1) return [];
    return subjects.map(subject => {
      const subjectPath = String(subject?.path || '').trim();
      const effect = effects.find(item => String(item?.path || '').trim() === subjectPath) || null;
      return {
        title: auditSubjectTitle(subject),
        summary: auditRepairFamilySummary(event, effect),
      };
    });
  }

  function auditRepairBreakdownMarkup(event) {
    const rows = auditRepairBreakdownRows(event);
    if (!rows.length) return '';
    const eventId = String(event?.event_id || '').trim();
    const isOpen = eventId && state.auditOpenBreakdowns.has(eventId);
    return `
      <button class="lab-audit-summary-toggle" type="button" data-audit-breakdown-toggle="${escapeHtml(eventId)}" aria-expanded="${isOpen ? 'true' : 'false'}">
        <span class="lab-audit-summary-toggle-copy">${escapeHtml(event.summary || '—')}</span>
      </button>
    `;
  }

  function auditActionChipMarkup(event) {
    const meta = auditActionChipMeta(event);
    return `<span class="lab-cell-pill ${escapeHtml(meta.tone || '')}">${escapeHtml(meta.label)}</span>`;
  }

  function renderAuditSummaryCell(event) {
    if (auditRepairBreakdownRows(event).length) return auditRepairBreakdownMarkup(event);
    return `
      <div class="lab-audit-summary-copy">
        <span class="lab-cell-text">${escapeHtml(event.summary || '—')}</span>
      </div>
    `;
  }

  function renderAuditRepairChildRows(event) {
    const rows = auditRepairBreakdownRows(event);
    const eventId = String(event?.event_id || '').trim();
    if (!rows.length || !eventId || !state.auditOpenBreakdowns.has(eventId)) return '';
    return rows.map(row => `
      <tr class="lab-audit-child-row" data-audit-parent-event-id="${escapeHtml(eventId)}">
        <td class="lab-audit-child-spacer" aria-hidden="true"></td>
        <td class="lab-audit-child-spacer" aria-hidden="true"></td>
        <td class="lab-audit-child-spacer" aria-hidden="true"></td>
        <td class="lab-cell-anchor lab-audit-child-subject" title="${escapeHtml(row.title)}"><span class="lab-cell-text">${escapeHtml(row.title)}</span></td>
        <td class="lab-cell-supporting lab-audit-child-outcome"><span class="lab-cell-text">Remux file</span></td>
        <td class="lab-cell-supporting lab-audit-child-summary" title="${escapeHtml(row.summary)}"><span class="lab-cell-text">${escapeHtml(row.summary)}</span></td>
      </tr>
    `).join('');
  }

  function auditEffectLabel(event) {
    const effects = Array.isArray(event?.effects) ? event.effects : [];
    if (!effects.length) return event?.reversal?.capability === 'recorded_only' ? 'Recorded reversal' : 'Recorded only';
    const lead = effects[0];
    const kind = humanProfileLabel(lead.kind || 'event');
    const status = humanProfileLabel(lead.status || 'recorded');
    if (effects.length === 1) return `${kind} · ${status}`;
    if (effects.every(effect => (effect?.kind || '') === (lead.kind || '') && (effect?.status || '') === (lead.status || ''))) {
      const unit = lead.kind === 'remux_repair' ? 'file' : 'item';
      return `${kind} · ${status} to ${effects.length} ${unit}${effects.length === 1 ? '' : 's'}`;
    }
    return `${kind} · ${status} +${effects.length - 1}`;
  }

  function auditEventsNewestFirst(events) {
    return (Array.isArray(events) ? events.slice() : []).sort((left, right) => {
      const leftRecordedAt = String(left?.recorded_at || '');
      const rightRecordedAt = String(right?.recorded_at || '');
      if (leftRecordedAt === rightRecordedAt) return 0;
      return leftRecordedAt < rightRecordedAt ? 1 : -1;
    });
  }

  function auditFollowupsNewestFirst(followups) {
    return (Array.isArray(followups) ? followups.slice() : []).sort((left, right) => {
      const leftKey = `${String(left?.updated_at || '')} ${String(left?.created_at || '')}`;
      const rightKey = `${String(right?.updated_at || '')} ${String(right?.created_at || '')}`;
      if (leftKey === rightKey) return String(left?.follow_up_id || '') < String(right?.follow_up_id || '') ? 1 : -1;
      return leftKey < rightKey ? 1 : -1;
    });
  }

  function auditSessionContextLabel(payload) {
    const event = payload?.latest_system_start;
    if (!event?.recorded_at) return '';
    return `Session started ${formatAuditRecordedAt(event.recorded_at)}`;
  }

  function bindAuditBreakdownToggleState() {
    if (!el.auditPanel) return;
    el.auditPanel.querySelectorAll('button[data-audit-breakdown-toggle]').forEach(button => {
      button.addEventListener('click', () => {
        const eventId = String(button.dataset.auditBreakdownToggle || '').trim();
        if (!eventId) return;
        if (state.auditOpenBreakdowns.has(eventId)) state.auditOpenBreakdowns.delete(eventId);
        else state.auditOpenBreakdowns.add(eventId);
        renderAuditPanel();
      });
    });
  }

  function renderAuditPanel() {
    if (!auditSurfaceOpen()) {
      el.auditPanel.innerHTML = '';
      return;
    }
    if (!el.sourcePath.value.trim()) {
      el.auditPanel.innerHTML = `
        <div class="lab-policy-header">
          <div class="lab-policy-heading">
            <div class="lab-kicker">Audit Ledger</div>
            <h2>Source required</h2>
            <p>Select a source to load recorded actions for this library.</p>
          </div>
        </div>
      `;
      return;
    }
    if (state.auditBusy && !state.auditPayload) {
      el.auditPanel.innerHTML = `
        <div class="lab-policy-header">
          <div class="lab-policy-heading">
            <div class="lab-kicker">Audit Ledger</div>
            <h2>Loading activity</h2>
            <p>Reading recent ledger activity and active follow-ups.</p>
          </div>
        </div>
      `;
      return;
    }
    const events = auditEventsNewestFirst(state.auditPayload?.events);
    const followups = Array.isArray(state.auditPayload?.active_followups) ? state.auditPayload.active_followups : [];
    const sessionContextLabel = auditSessionContextLabel(state.auditPayload);
    if (!events.length) {
      el.auditPanel.innerHTML = `
        <div class="lab-policy-header">
          <div class="lab-policy-heading">
            <div class="lab-kicker">Audit Ledger</div>
            <h2>No recorded actions</h2>
            <p>Run a workflow and confirm an action to populate this ledger surface.</p>
          </div>
        </div>
      `;
      return;
    }
    el.auditPanel.innerHTML = `
      <div class="lab-policy-header">
        <div class="lab-policy-heading">
          <div class="lab-kicker">Audit Ledger</div>
          <h2>Recent library actions</h2>
          <p>Action-first history for this source, ordered from most recent to oldest.</p>
        </div>
      </div>
      <div class="lab-audit-summary">
        <span class="chip">${events.length} recent event${events.length === 1 ? '' : 's'}</span>
        <span class="chip queue">${followups.length} active follow-up${followups.length === 1 ? '' : 's'}</span>
      </div>
      ${sessionContextLabel ? `<div class="lab-audit-context">${escapeHtml(sessionContextLabel)}</div>` : ''}
      <div class="lab-audit-table lab-rhythm-surface" data-rhythm-surface="rows">
        <table class="lab-scan-table">
          <colgroup>
            <col style="width: 22ch">
            <col style="width: 14ch">
            <col style="width: 19ch">
            <col style="width: 12%">
            <col style="width: 20ch">
            <col style="width: 24%">
          </colgroup>
          <thead>
            <tr>
              <th>Recorded</th>
              <th>Action</th>
              <th>Workflow</th>
              <th>Subject</th>
              <th>Outcome</th>
              <th>Summary</th>
            </tr>
          </thead>
          <tbody>
            ${events.map(event => `
              <tr class="${auditRepairBreakdownRows(event).length ? 'lab-audit-parent-row is-expandable' : 'lab-audit-parent-row'}${state.auditOpenBreakdowns.has(String(event?.event_id || '').trim()) ? ' is-open' : ''}">
                <td class="lab-cell-supporting lab-cell-mono" title="${escapeHtml(event.recorded_at || '')}"><span class="lab-cell-text">${escapeHtml(formatAuditRecordedAt(event.recorded_at || ''))}</span></td>
                <td class="lab-cell-status" title="${escapeHtml(event.action || '')}">${auditActionChipMarkup(event)}</td>
                <td class="lab-cell-supporting" title="${escapeHtml(event.workflow || '')}"><span class="lab-cell-text">${escapeHtml(humanProfileLabel(event.workflow || 'audit'))}</span></td>
                <td class="lab-cell-anchor" title="${escapeHtml(auditSubjectLabel(event))}"><span class="lab-cell-text">${escapeHtml(auditSubjectLabel(event))}</span></td>
                <td class="lab-cell-supporting" title="${escapeHtml(auditOutcomeLabel(event))}"><span class="lab-cell-text">${escapeHtml(auditOutcomeLabel(event))}</span></td>
                <td class="lab-cell-supporting" title="${escapeHtml(event.summary || '')}">${renderAuditSummaryCell(event)}</td>
              </tr>
              ${renderAuditRepairChildRows(event)}
            `).join('')}
          </tbody>
        </table>
      </div>
    `;
    bindAuditBreakdownToggleState();
  }

  function inspectionSummaryForRow(row) {
    if (isWeakMode()) return `${row.issue} · ${row.resolution || '—'}`;
    if (isRepairDefaultsMode()) return `${row.issue_family || 'Issue'} · ${row.issue}`;
    if (isCanonicalMode()) return `${canonicalOwnedStatusLabel(row)} · ${row.quality_profile || '—'}`;
    if (isImmersiveMode()) return `${traitDisplayLabel(row.trait)} · ${immersiveVerdictDisplayLabel(row.release_status)} · ${formatOpportunityDisplayLabel(row.opportunity)}`;
    if (isJunkMode()) return `${row.issue} · ${row.confidence || 'review'}`;
    return `${row.projected_path || row.current_value} · ${row.confidence || 'review'}`;
  }

  function renderInspectionPane() {
    if (!surfaceOpen()) {
      el.inspectionPane.innerHTML = '';
      return;
    }
    if (auditSurfaceOpen()) {
      const followups = auditFollowupsNewestFirst(state.auditPayload?.active_followups);
      const events = auditEventsNewestFirst(state.auditPayload?.events).slice(0, 8);
      if (!el.sourcePath.value.trim()) {
        el.inspectionPane.innerHTML = '<div class="lab-preview-empty"><strong>Audit source required.</strong><div>Select a source to open the ledger surface.</div></div>';
        return;
      }
      if (state.auditBusy) {
        el.inspectionPane.innerHTML = '<div class="lab-preview-empty"><strong>Loading audit context.</strong><div>Recent activity and follow-ups are being read now.</div></div>';
        return;
      }
      el.inspectionPane.innerHTML = `
        <div class="lab-inspection-pane">
          <div class="lab-inspection-summary"><strong>${followups.length}</strong> active follow-up${followups.length === 1 ? '' : 's'} currently remain open for this source.</div>
          <div class="lab-inspection-table">
            <table class="lab-scan-table">
              <thead>
                <tr>
                  <th>Subject</th>
                  <th>Audit Reading</th>
                </tr>
              </thead>
              <tbody>
                ${(followups.length ? followups : events).map(item => {
                  const subject = item.subject?.title
                    ? (item.subject.year ? `${item.subject.title} (${item.subject.year})` : item.subject.title)
                    : auditSubjectLabel(item);
                  const reading = followups.length
                    ? `${humanProfileLabel(item.kind || 'follow_up')} · ${item.summary || 'Active'}`
                    : `${humanProfileLabel(item.action || 'recorded')} · ${item.summary || 'Recorded action'}`;
                  return `
                    <tr>
                      <td class="lab-cell-anchor" title="${escapeHtml(subject || '—')}"><span class="lab-cell-text">${escapeHtml(subject || '—')}</span></td>
                      <td class="lab-cell-supporting" title="${escapeHtml(reading)}"><span class="lab-cell-text">${escapeHtml(reading)}</span></td>
                    </tr>
                  `;
                }).join('')}
              </tbody>
            </table>
          </div>
          <div class="lab-inspection-note">Preview and action controls are suppressed while the audit ledger is open.</div>
        </div>
      `;
      return;
    }
    if (dashboardSurfaceOpen()) {
      const payload = currentDashboardPayload();
      if (!payload) {
        el.inspectionPane.innerHTML = '<div class="lab-preview-empty"><strong>No dashboard payload.</strong><div>Run a profile-bearing workflow for this source to load the dashboard surface.</div></div>';
        return;
      }
      const histogram = payload.histogram || {};
      const total = Number(histogram.movie_count ?? ((payload.movies || []).length));
      const reviewCount = Number(histogram.profile_counts?.needs_review || 0);
      const replacementDefinition = currentReplacementDefinition();
      const cutoff = replacementDefinition?.fields?.[0]?.value || state.weakFloor;
      el.inspectionPane.innerHTML = `
        <div class="lab-inspection-pane">
          <div class="lab-inspection-summary"><strong>${total.toLocaleString()}</strong> movies are represented in the current dashboard snapshot for this source.</div>
          <div class="lab-inspection-table">
            <table class="lab-scan-table">
              <thead>
                <tr>
                  <th>Reading</th>
                  <th>Value</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td class="lab-cell-anchor"><span class="lab-cell-text">Needs Review</span></td>
                  <td class="lab-cell-supporting"><span class="lab-cell-text">${escapeHtml(reviewCount.toLocaleString())}</span></td>
                </tr>
                <tr>
                  <td class="lab-cell-anchor"><span class="lab-cell-text">Weak Encode Floor</span></td>
                  <td class="lab-cell-supporting"><span class="lab-cell-text">${escapeHtml(replacementFloorDisplayLabel(cutoff))}</span></td>
                </tr>
                <tr>
                  <td class="lab-cell-anchor"><span class="lab-cell-text">Scan Model</span></td>
                  <td class="lab-cell-supporting"><span class="lab-cell-text">Reuses latest profile-bearing scan for this source</span></td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="lab-inspection-note">Preview and action controls are suppressed while dashboard view is open.</div>
        </div>
      `;
      return;
    }
    const rows = state.filteredRows.slice(0, 10);
    if (!rows.length) {
      el.inspectionPane.innerHTML = '<div class="lab-preview-empty"><strong>No inspection rows.</strong><div>Run the current workflow or relax the active filters.</div></div>';
      return;
    }
    const key = (usesSimpleSelectionShell() || isCanonicalMode() || isImmersiveMode()) ? 'row_id' : 'result_id';
    el.inspectionPane.innerHTML = `
      <div class="lab-inspection-pane">
        <div class="lab-inspection-summary"><strong>${rows.length}</strong> visible inspection row${rows.length === 1 ? '' : 's'} shown in reduced-reading mode while policy editing is active.</div>
        <div class="lab-inspection-table">
          <table class="lab-scan-table">
            <thead>
              <tr>
                <th>File Name</th>
                <th>Inspection Reading</th>
              </tr>
            </thead>
            <tbody>
              ${rows.map(row => `
                <tr class="${state.activeRowId === row[key] ? 'active' : ''}">
                  <td class="lab-cell-anchor lab-cell-mono" title="${escapeHtml(fileNameFromPath(row.current_path || row.current_value || ''))}"><span class="lab-cell-text">${escapeHtml(fileNameFromPath(row.current_path || row.current_value || ''))}</span></td>
                  <td class="lab-cell-supporting" title="${escapeHtml(inspectionSummaryForRow(row))}"><span class="lab-cell-text">${escapeHtml(inspectionSummaryForRow(row))}</span></td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
        <div class="lab-inspection-note">Preview and action controls are suppressed while policy editing is active.</div>
      </div>
    `;
  }

  function currentHeaders() {
    if (isWeakMode()) return WEAK_HEADERS;
    if (isRepairDefaultsMode()) return REPAIR_HEADERS;
    if (isCanonicalMode()) return CANONICAL_HEADERS;
    if (isImmersiveMode()) return IMMERSIVE_HEADERS;
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
      const titleAttr = header.tooltip ? ` title="${escapeHtml(header.tooltip)}"` : '';
      return `<th${classAttr}${priorityAttr}><button class="sort" data-sort="${escapeHtml(header.key)}"${titleAttr}>${escapeHtml(header.label)}</button></th>`;
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

  function repairIssueSummary(item) {
    const parts = [];
    const audioIssue = movieAudioPackagingIssueCode(item);
    const subtitleIssue = movieSubtitleReadinessIssueCode(item);
    if (audioIssue) parts.push(audioIssue === 'default_non_english_audio_with_weak_english' ? 'non-English audio is default · English backup is weaker' : 'non-English audio is default');
    if (subtitleIssue && movieSubtitleReadinessIsRepairable(item)) parts.push(humanSubtitleReadinessIssueLabel(subtitleIssue));
    if (audioIssue && combinedSubtitleWillRun(item) && combinedSubtitleSecondOrder(item)) {
      const stagedIssue = repairPlanCombinedSubtitle(item)?.issue_code || '';
      parts.push(`after audio default flips: ${humanSubtitleReadinessIssueLabel(stagedIssue)}`);
    }
    return parts.join(' | ');
  }

  function repairCurrentDefaultSummary(item) {
    const parts = [];
    if (movieAudioPackagingIssueCode(item)) parts.push(`audio default: ${describeAudioStream(movieDefaultAudioStream(item))}`);
    if (movieSubtitleReadinessIsRepairable(item) || combinedSubtitleWillRun(item)) parts.push(`subtitle default: ${describeSubtitleStream(movieDefaultSubtitleStream(item))}`);
    return parts.join(' | ') || '—';
  }

  function repairTargetSummary(item) {
    const parts = [];
    if (movieAudioPackagingIssueCode(item)) parts.push(`audio default: ${describeAudioStream(movieAudioPackagingTarget(item))}`);
    if (movieSubtitleReadinessIsRepairable(item)) parts.push(`subtitle default: ${describeSubtitlePolicyTarget(movieSubtitleReadinessRepairTarget(item))}`);
    if (movieAudioPackagingIssueCode(item) && combinedSubtitleWillRun(item) && combinedSubtitleSecondOrder(item)) {
      parts.push(`after audio switch, subtitle default: ${describeSubtitlePolicyTarget(movieCombinedSubtitleRepairTarget(item))}`);
    }
    return parts.join(' | ') || '—';
  }

  function repairRowForItem(item) {
    const issueFamilies = Array.isArray(item?.repair_plan?.issue_families) ? item.repair_plan.issue_families : [];
    const audioIssueCode = movieAudioPackagingIssueCode(item);
    const subtitleIssueCode = movieSubtitleReadinessIssueCode(item);
    return {
      row_id: item.path || '',
      path: item.path || '',
      item,
      selectable: Boolean(item.path) && issueFamilies.length > 0 && !repairDefaultsSelectionLocked(),
      issue_families: issueFamilies,
      current_path: item.path || '',
      issue: repairIssueSummary(item),
      current_default: repairCurrentDefaultSummary(item),
      repair_target: repairTargetSummary(item),
      default_subtitle: repairDefaultSubtitleLabel(item),
      resolution: actualResolutionLabel(item),
      audio_bitrate: item?.facts?.audio_bitrate_kbps || 0,
      file_size: item?.facts?.file_size_bytes || 0,
      audio_issue_code: audioIssueCode,
      subtitle_issue_code: subtitleIssueCode,
      combined_subtitle_issue_code: repairPlanCombinedSubtitle(item)?.issue_code || '',
      combined_subtitle_second_order: combinedSubtitleSecondOrder(item),
      workflow_status: issueFamilies.length === 2 ? 'both' : (issueFamilies[0] === 'audio' ? (audioIssueCode === 'default_non_english_audio_with_weak_english' ? 'weak_english' : 'wrong_default') : subtitleIssueCode),
    };
  }

  function weakFloorStanceFields() {
    const definitions = currentQualityProfileDefinitions();
    const hasFloors = definition => (definition?.fields || []).some(field => field.key === 'video_1080p_kbps' || field.key === 'audio_bitrate_kbps');
    const cutoffRank = qualityStanceRank(state.weakFloor);
    let chosen = definitions.find(entry => entry?.label === state.weakFloor && hasFloors(entry));
    if (!chosen) {
      chosen = definitions
        .filter(entry => hasFloors(entry) && qualityStanceRank(entry.label) >= cutoffRank)
        .sort((left, right) => qualityStanceRank(left.label) - qualityStanceRank(right.label))[0];
    }
    const fields = {};
    (chosen?.fields || []).forEach(field => { fields[field.key] = field.value; });
    return fields;
  }

  const HEALTHY_AUDIO_KBPS_PER_CHANNEL = 107;

  function deficitTriageScore(ratio) {
    if (ratio == null || !isFinite(ratio) || ratio <= 0) return null;
    if (ratio >= 1) return 1;
    return Math.min(10, Math.max(1, Math.ceil((1 - ratio) * 10) + 1));
  }

  function weakTriageBreakdown(item) {
    const facts = item?.facts || {};
    const fields = weakFloorStanceFields();
    const axes = [];
    const resolution = String(facts.resolution_bucket || '').toLowerCase();
    let videoFloor = 0;
    if (resolution === '2160p' || resolution === '4k') videoFloor = Number(fields.video_2160p_kbps || 0);
    else if (resolution === '1080p') videoFloor = Number(fields.video_1080p_kbps || 0);
    const videoBitrate = Number(facts.video_bitrate_kbps || 0);
    if (videoFloor > 0 && videoBitrate > 0) axes.push({ axis: 'video', ratio: videoBitrate / videoFloor });
    const audioBitrate = Number(facts.audio_bitrate_kbps || 0);
    const channels = Number(facts.audio_channels || 0);
    if (audioBitrate > 0 && channels > 0) axes.push({ axis: 'audio', ratio: (audioBitrate / channels) / HEALTHY_AUDIO_KBPS_PER_CHANNEL });
    if (!axes.length) return { score: null, offender: null };
    const worst = axes.reduce((left, right) => (right.ratio < left.ratio ? right : left));
    return { score: deficitTriageScore(worst.ratio), offender: worst.axis };
  }

  function weakRowForItem(item) {
    const triage = weakTriageBreakdown(item);
    return {
      row_id: item.path || '',
      path: item.path || '',
      item,
      selectable: isStrictWeakMovie(item),
      current_path: item.path || '',
      issue: movieProfileInlineSummary(item) || humanProfileLabel(item?.profile?.label || ''),
      badges: collectWeakBadges(item),
      triage: triage.score,
      triageOffender: triage.offender,
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
      issue: repairIssueSummary(item),
      current_default: describeAudioStream(movieDefaultAudioStream(item)),
      repair_target: repairTargetSummary(item),
      resolution: actualResolutionLabel(item),
      audio_bitrate: item?.facts?.audio_bitrate_kbps || 0,
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
      resolution: actualResolutionLabel(item),
      audio_bitrate: item?.facts?.audio_bitrate_kbps || 0,
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
      return (state.repairPayload?.movies || [])
        .filter(item => !!movieAudioPackagingIssueCode(item) || movieSubtitleReadinessIsRepairable(item))
        .map(repairRowForItem);
    }
    if (isCanonicalMode()) return canonicalRows();
    if (isImmersiveMode()) return immersiveRows();
    if (isJunkMode()) return (state.junkPayload?.junk || []).map(junkRowForItem);
    return normalizeRows();
  }

  function canonicalRows() {
    const summary = activeCanonicalListSummary();
    const entries = Array.isArray(summary?.all_entries) ? summary.all_entries : [];
    const profileByPath = canonicalProfileItemsByPath();
    return entries.map((entry, index) => {
      const currentPath = entry.path || '';
      const item = currentPath ? (profileByPath.get(currentPath) || null) : null;
      return {
        row_id: `${summary?.id || 'canonical'}:${index + 1}:${entry.title || ''}:${entry.year || ''}`,
        rank: index + 1,
        title: entry.title || '',
        year: entry.year || '',
        imdb_id: entry.imdb_id || '',
        owned: !!entry.owned,
        in_library: entry.owned ? 'owned' : 'missing',
        quality_profile: canonicalQualityProfileLabel(item) || (entry.owned ? 'Owned' : '—'),
        current_path: currentPath,
        item,
        path: currentPath,
      };
    });
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
        if (status === 'weak_english' && row.workflow_status !== 'weak_english') return false;
        if (status === 'wrong_default' && row.workflow_status !== 'wrong_default') return false;
        if (status === 'queued' && row.workflow_status !== 'queued') return false;
        if (status === 'forced_english' && !['english_forced_not_default', 'wrong_default_forced_subtitle'].includes(row.subtitle_issue_code)) return false;
        if (status === 'non_english_audio' && row.subtitle_issue_code !== 'wrong_default_subtitle_language') return false;
        if (status === 'clear_default' && !['unnecessary_default_subtitle', 'multiple_default_subtitles'].includes(row.subtitle_issue_code)) return false;
        if (status === 'both' && row.workflow_status !== 'both') return false;
        if (status === 'audio_only' && row.workflow_status === 'both') return false;
        if (status === 'audio_only' && !rowTouchesFamily(row, 'audio')) return false;
        if (status === 'subtitle_only' && row.workflow_status === 'both') return false;
        if (status === 'subtitle_only' && !rowTouchesFamily(row, 'subtitle')) return false;
        if (query) {
          const haystack = `${row.current_path} ${row.issue_family} ${row.issue} ${row.current_default} ${row.repair_target}`.toLowerCase();
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
    } else if (isCanonicalMode()) {
      rows = rows.filter(row => {
        if (query) {
          const haystack = `${row.rank} ${row.title} ${row.year} ${canonicalOwnedStatusLabel(row)} ${row.quality_profile} ${row.current_path}`.toLowerCase();
          if (!haystack.includes(query)) return false;
        }
        return true;
      });
    } else if (isImmersiveMode()) {
      const trait = el.traitFilter.value;
      const opportunity = el.traitStatusFilter.value;
      const defaultOpportunities = new Set(['upgrade_found', 'partial_coverage', 'already_covered', 'quality_review', 'no_known_upgrade', 'conflicting_reports']);
      rows = rows.filter(row => {
        if (trait !== 'all' && row.trait !== trait) return false;
        if (opportunity === 'default' && !defaultOpportunities.has(row.opportunity)) return false;
        if (!['default', 'all'].includes(opportunity) && row.opportunity !== opportunity) return false;
        if (query) {
          const haystack = `${row.title} ${row.year} ${traitDisplayLabel(row.trait)} ${immersiveVerdictDisplayLabel(row.release_status)} ${formatOpportunityDisplayLabel(row.opportunity)} ${localCopySummary(row)}`.toLowerCase();
          if (!haystack.includes(query)) return false;
        }
        return true;
      });
    } else {
      const bucket = el.bucketFilter.value;
      rows = rows.filter(row => {
        if (bucket === 'actionable' && !row.actionable) return false;
        if (bucket === 'unchanged' && row.confidence !== 'unchanged') return false;
        if ((bucket === 'safe' || bucket === 'review') && row.confidence !== bucket) return false;
        if (query) {
          const haystack = `${row.current_value} ${row.projected_path}`.toLowerCase();
          if (!haystack.includes(query)) return false;
        }
        return true;
      });
    }
    rows.sort((a, b) => compareRows(a, b, state.sort.key, state.sort.dir));
    state.rows = activeRows();
    state.filteredRows = rows;
  }

  function compareRows(a, b, key, dir) {
    const mult = dir === 'asc' ? 1 : -1;
    if (isCanonicalMode()) {
      const read = row => {
        if (key === 'rank' || key === 'year') return Number(row[key] || 0);
        if (key === 'in_library') return row.owned ? 0 : 1;
        return String(row[key] || '').toLowerCase();
      };
      const av = read(a);
      const bv = read(b);
      return av < bv ? -1 * mult : av > bv ? 1 * mult : 0;
    }
    if (isImmersiveMode()) {
      const verdictRank = { upgrade_available: 0, likely_available: 1, no_known_release: 2, contested: 3, unverified: 4 };
      const opportunityRank = { upgrade_found: 0, partial_coverage: 1, quality_review: 2, already_covered: 3, no_known_upgrade: 4, conflicting_reports: 5, research_needed: 6 };
      const read = row => {
        if (key === 'release_status') return verdictRank[row.release_status] ?? 5;
        if (key === 'opportunity') return opportunityRank[row.opportunity] ?? 7;
        if (key === 'coverage') return localCopySummary(row).toLowerCase();
        return String(row[key] || '').toLowerCase();
      };
      if (key !== 'title') {
        const titleOrder = String(a.title || '').localeCompare(String(b.title || ''), undefined, { sensitivity: 'base' })
          || Number(a.year || 0) - Number(b.year || 0);
        if (titleOrder) return titleOrder;
      }
      const av = read(a);
      const bv = read(b);
      return av < bv ? -1 * mult : av > bv ? 1 * mult : 0;
    }
    if (usesSimpleSelectionShell()) {
      const read = row => {
        if (key === 'badges') return Array.isArray(row.badges) ? row.badges.length : 0;
        if (key === 'video_bitrate' || key === 'audio_bitrate' || key === 'channels' || key === 'file_size' || key === 'triage') return Number(row[key] || 0);
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
  function selectedWeakPaths() {
    return state.filteredRows.filter(row => state.selected.has(row.row_id) && row.selectable).map(row => row.path);
  }

  function selectedWeakItems() {
    return state.filteredRows.filter(row => state.selected.has(row.row_id) && row.selectable).map(row => row.item);
  }

  function selectedRepairPaths() {
    return state.filteredRows.filter(row => state.selected.has(row.row_id)).map(row => row.path);
  }

  function selectedRepairItems() {
    return state.filteredRows.filter(row => state.selected.has(row.row_id)).map(row => row.item);
  }

  function selectedRepairRows() {
    return state.filteredRows.filter(row => state.selected.has(row.row_id));
  }

  function repairRowsForAction(rows, action = state.repairAction) {
    return rows.filter(row => repairRowMatchesAction(row, action));
  }

  function selectedRepairRowsForAction(action = state.repairAction) {
    return repairRowsForAction(selectedRepairRows(), action);
  }

  function selectedRepairApplicability(action = state.repairAction) {
    const rows = selectedRepairRows();
    const applicableRows = repairRowsForAction(rows, action);
    return {
      selectedRows: rows,
      applicableRows,
      skippedRows: rows.filter(row => !repairRowMatchesAction(row, action)),
    };
  }

  function selectedRepairAudioPaths() {
    return selectedRepairRowsForAction().filter(row => rowTouchesFamily(row, 'audio')).map(row => row.path);
  }

  function selectedRepairSubtitleRows() {
    return selectedRepairRowsForAction().filter(row => rowTouchesFamily(row, 'subtitle'));
  }

  function selectedJunkPaths() {
    return state.filteredRows.filter(row => state.selected.has(row.row_id) && row.selectable).map(row => row.path);
  }

  function selectedJunkItems() {
    return state.filteredRows.filter(row => state.selected.has(row.row_id) && row.selectable).map(row => row.item);
  }

  function renderSelectionButtons() {
    if (isCanonicalMode() || isImmersiveMode()) {
      el.selectAllButton.disabled = true;
      el.deselectAllButton.disabled = true;
      el.selectAllButton.textContent = 'Select all';
      el.deselectAllButton.textContent = 'Deselect all';
      return;
    }
    const selectableRows = usesSimpleSelectionShell() ? state.filteredRows.filter(row => row.selectable) : state.filteredRows;
    const filteredCount = selectableRows.length;
    const selectedVisibleCount = usesSimpleSelectionShell()
      ? state.filteredRows.filter(row => state.selected.has(row.row_id)).length
      : selectableRows.filter(row => state.selected.has(row.result_id)).length;
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
    el.confirmButton.hidden = false;
    if (isCanonicalMode() || isImmersiveMode()) {
      el.confirmButton.hidden = true;
      el.confirmButton.disabled = true;
      el.confirmButton.classList.remove('is-danger');
      el.confirmButton.textContent = 'Read-only';
      return;
    }
    if (isWeakMode()) {
      const count = selectedWeakPaths().length;
      el.confirmButton.disabled = count === 0 || state.applyInFlight;
      el.confirmButton.classList.add('is-danger');
      el.confirmButton.textContent = state.applyInFlight ? `Deleting Selected Files (${count})` : `Delete Selected Files (${count})`;
      return;
    }
    if (isRepairDefaultsMode()) {
      // Audio/Sub Repair is intentionally non-destructive in the current UI.
      // Keep the shared confirm button available for delete-capable flows only.
      el.confirmButton.hidden = true;
      el.confirmButton.disabled = true;
      el.confirmButton.classList.remove('is-danger');
      el.confirmButton.textContent = 'This page is non-destructive';
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
    if (!usesDeletePreviewShell()) closeTrackPopover();
    el.workflowButton.dataset.active = surfaceOpen() ? 'false' : 'true';
    el.scanTablePanel.hidden = surfaceOpen();
    el.dashboardPanel.hidden = !dashboardSurfaceOpen();
    el.policyEditorPanel.hidden = !policySurfaceOpen();
    el.auditPanel.hidden = !auditSurfaceOpen();
    if (el.settingsPanel) el.settingsPanel.hidden = !settingsSurfaceOpen();
    el.previewPane.hidden = surfaceOpen();
    el.inspectionPane.hidden = !surfaceOpen();
    el.previewControls.hidden = surfaceOpen();
    el.previewPanelKicker.textContent = auditSurfaceOpen() ? 'Audit Context' : (dashboardSurfaceOpen() ? 'Dashboard Context' : 'Downstream Preview');
    el.previewPanelHeading.textContent = auditSurfaceOpen() ? 'Ledger Reading' : (dashboardSurfaceOpen() ? 'Library Overview' : 'Projected Output');
    renderShellLayout();
    renderConfirmButton();
    renderWorkflowActionControls();
    updateRepairLockOverlay();
  }

  function renderRows() {
    applyFilters();
    synchronizeSelectionWithRows();
    renderSelectionButtons();
    if (!state.filteredRows.length) {
      closeTrackPopover();
      const colspan = String(currentHeaders().length);
      const emptyMessage = isImmersiveMode()
        ? (state.immersivePayload
          ? 'No title-trait rows match the active filters.'
          : 'Run Review Format Upgrade Candidates to compare known releases with feature coverage across your copies.')
        : 'No rows for the active filters.';
      el.rowsBody.innerHTML = `<tr><td colspan="${colspan}">${escapeHtml(emptyMessage)}</td></tr>`;
      renderConfirmButton();
      renderWorkflowActionControls();
      return;
    }
    el.rowsBody.innerHTML = isWeakMode()
      ? state.filteredRows.map(renderWeakRow).join('')
      : (isRepairDefaultsMode()
        ? state.filteredRows.map(renderRepairRow).join('')
        : (isCanonicalMode()
          ? state.filteredRows.map(renderCanonicalRow).join('')
          : (isImmersiveMode()
          ? state.filteredRows.map(renderImmersiveRow).join('')
          : (isJunkMode()
          ? state.filteredRows.map(renderJunkRow).join('')
          : state.filteredRows.map(renderNormalizeRow).join('')))));
    attachRowHandlers();
    renderJunkFilenameCells();
    renderTrackPopover();
    renderConfirmButton();
    renderWorkflowActionControls();
    updateRepairLockOverlay();
  }

  function simpleSelectionRowClass(rowId) {
    const classes = [];
    if (state.selected.has(rowId)) classes.push('is-selected');
    if (state.activeRowId === rowId) classes.push('active');
    return classes.join(' ');
  }

  function renderNormalizeRow(row) {
    return `
      <tr class="${state.activeRowId === row.result_id ? 'active' : ''}" data-row-id="${escapeHtml(row.result_id)}">
        <td class="lab-cell-foundation lab-cell-select" data-priority="essential"><input type="checkbox" data-row-check="${escapeHtml(row.result_id)}" ${state.selected.has(row.result_id) ? 'checked' : ''}></td>
        <td class="lab-cell-anchor" data-priority="essential" title="${escapeHtml(row.current_value)}"><span class="lab-cell-text">${escapeHtml(fileNameFromPath(row.current_value))}</span></td>
        <td class="lab-cell-path" data-priority="desktop" title="${escapeHtml(row.projected_path)}"><span class="lab-cell-text">${projectedPathMarkup(row.projected_path)}</span></td>
        <td class="lab-cell-status" data-priority="essential"><span class="lab-cell-pill ${normalizeConfidenceClass(row.confidence)}">${escapeHtml(row.confidence)}</span></td>
        <td class="lab-cell-status" data-priority="medium"><span class="lab-cell-pill">${escapeHtml(row.reason_bucket)}</span></td>
      </tr>
    `;
  }

  function renderWeakRow(row) {
    const checked = state.selected.has(row.row_id) ? 'checked' : '';
    const hasAudioTracks = audioTracksForRow(row).length > 0;
    const audioBitrateMarkup = hasAudioTracks
      ? `<button class="lab-audio-popover-trigger" type="button" data-track-popover="${escapeHtml(row.row_id)}" data-track-popover-kind="audio" aria-expanded="${state.trackPopoverRowId === row.row_id && state.trackPopoverKind === 'audio' ? 'true' : 'false'}">${escapeHtml(formatBitrate(row.audio_bitrate))}</button>`
      : `<span class="lab-cell-text">${escapeHtml(formatBitrate(row.audio_bitrate))}</span>`;
    const flagVideo = row.triageOffender === 'video' ? ' lab-triage-flag' : '';
    const flagAudio = row.triageOffender === 'audio' ? ' lab-triage-flag' : '';
    return `
      <tr class="${escapeHtml(simpleSelectionRowClass(row.row_id))}" data-row-id="${escapeHtml(row.row_id)}">
        <td class="lab-cell-foundation lab-cell-select" data-priority="essential">${row.selectable ? `<input type="checkbox" data-row-check="${escapeHtml(row.row_id)}" ${checked}>` : ''}</td>
        <td class="lab-cell-anchor" data-priority="essential" title="${escapeHtml(row.current_path)}"><span class="lab-cell-text">${escapeHtml(fileNameFromPath(row.current_path))}</span></td>
        <td class="lab-cell-decision" data-priority="essential" title="${escapeHtml(row.issue)}"><span class="lab-cell-text">${escapeHtml(row.issue)}</span></td>
        <td class="lab-cell-signal lab-cell-mono" data-priority="essential" title="${row.triage == null ? 'No measurable bitrate deficit against the quality floor' : `Triage score ${row.triage} of 10`}"><span class="lab-cell-text">${row.triage == null ? '—' : escapeHtml(String(row.triage))}</span></td>
        <td class="lab-cell-signal" data-priority="essential">${weakBadgeClusterMarkup(row.badges)}</td>
        <td class="lab-cell-supporting${flagVideo}" data-priority="medium" title="${escapeHtml(row.resolution || '—')}"><span class="lab-cell-text">${escapeHtml(row.resolution || '—')}</span></td>
        <td class="lab-cell-signal lab-cell-mono${flagVideo}" data-priority="essential" title="${escapeHtml(formatBitrate(row.video_bitrate))}"><span class="lab-cell-text">${escapeHtml(formatBitrate(row.video_bitrate))}</span></td>
        <td class="lab-cell-signal lab-cell-mono${flagAudio}" data-priority="desktop" title="${escapeHtml(formatBitrate(row.audio_bitrate))}">${audioBitrateMarkup}</td>
        <td class="lab-cell-signal lab-cell-mono${flagAudio}" data-priority="medium" title="${row.channels ? escapeHtml(String(row.channels)) : '—'}"><span class="lab-cell-text">${row.channels ? escapeHtml(String(row.channels)) : '—'}</span></td>
        <td class="lab-cell-supporting${flagAudio}" data-priority="desktop" title="${escapeHtml(row.audio_summary || '—')}"><span class="lab-cell-text">${escapeHtml(row.audio_summary || '—')}</span></td>
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
      ? `<button class="lab-audio-popover-trigger" type="button" data-track-popover="${escapeHtml(row.row_id)}" data-track-popover-kind="audio" aria-expanded="${state.trackPopoverRowId === row.row_id && state.trackPopoverKind === 'audio' ? 'true' : 'false'}">${escapeHtml(formatBitrate(row.audio_bitrate))}</button>`
      : `<span class="lab-cell-text">${escapeHtml(formatBitrate(row.audio_bitrate))}</span>`;
    return `
      <tr class="${escapeHtml(simpleSelectionRowClass(row.row_id))}" data-row-id="${escapeHtml(row.row_id)}">
        <td class="lab-cell-foundation lab-cell-select" data-priority="essential">${row.selectable ? `<input type="checkbox" data-row-check="${escapeHtml(row.row_id)}" ${checked}>` : ''}</td>
        <td class="lab-cell-anchor" data-priority="essential" title="${escapeHtml(row.current_path)}" data-junk-filename-cell>
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

  function canonicalStatusClass(row) {
    return row.owned ? 'is-safe' : 'is-not-available';
  }

  function renderCanonicalRow(row) {
    const inspectable = row.owned && row.item;
    const qualityMarkup = inspectable
      ? `<button class="lab-audio-popover-trigger" type="button" data-track-popover="${escapeHtml(row.row_id)}" data-track-popover-kind="audio" aria-expanded="${state.trackPopoverRowId === row.row_id && state.trackPopoverKind === 'audio' ? 'true' : 'false'}">${escapeHtml(row.quality_profile || 'Owned')}</button>`
      : `<span class="lab-cell-text">${escapeHtml(row.quality_profile || '—')}</span>`;
    return `
      <tr class="${state.activeRowId === row.row_id ? 'active' : ''}" data-row-id="${escapeHtml(row.row_id)}">
        <td class="lab-cell-foundation lab-cell-signal lab-cell-mono" data-priority="essential" title="${escapeHtml(String(row.rank || '—'))}"><span class="lab-cell-text">${escapeHtml(String(row.rank || '—'))}</span></td>
        <td class="lab-cell-anchor" data-priority="essential" title="${escapeHtml(row.title || '—')}">${canonicalTitleMarkup(row.title, row.imdb_id)}</td>
        <td class="lab-cell-signal lab-cell-mono" data-priority="medium" title="${escapeHtml(String(row.year || '—'))}"><span class="lab-cell-text">${escapeHtml(String(row.year || '—'))}</span></td>
        <td class="lab-cell-status" data-priority="essential"><span class="lab-cell-pill ${canonicalStatusClass(row)}">${escapeHtml(canonicalOwnedStatusLabel(row))}</span></td>
        <td class="lab-cell-supporting" data-priority="desktop" title="${escapeHtml(row.quality_profile || '—')}">${qualityMarkup}</td>
        <td class="lab-cell-anchor lab-cell-mono" data-priority="desktop" title="${escapeHtml(row.current_path || '—')}"><span class="lab-cell-text">${escapeHtml(row.current_path ? fileNameFromPath(row.current_path) : '—')}</span></td>
      </tr>
    `;
  }

  function renderImmersiveRow(row, index, rows) {
    const paths = Array.isArray(row.local_paths) ? row.local_paths : [];
    const copiesTitle = paths.length ? paths.join(' | ') : 'No local copy details.';
    const needsNormalization = !row.year;
    const titleTooltip = needsNormalization ? 'File name needs normalization!' : (row.title || '—');
    const yearTooltip = needsNormalization ? 'Year requires file normalization to display!' : String(row.year || '—');
    const groupKey = `${row.title || ''}\u0000${row.year || ''}`;
    const previous = rows[index - 1];
    const firstInGroup = !previous || `${previous.title || ''}\u0000${previous.year || ''}` !== groupKey;
    const parentRow = firstInGroup
      ? `
        <tr class="lab-format-parent-row">
          <td class="lab-cell-foundation lab-cell-signal lab-cell-mono" data-priority="essential"><span class="lab-cell-text" title="${escapeHtml(yearTooltip)}">${escapeHtml(String(row.year || '—'))}</span></td>
          <td class="lab-cell-anchor" data-priority="essential"><span class="lab-cell-text" title="${escapeHtml(titleTooltip)}">${escapeHtml(row.title || '—')}</span></td>
          <td class="lab-cell-status"></td>
          <td class="lab-cell-status"></td>
          <td class="lab-cell-status"></td>
          <td class="lab-cell-supporting"></td>
        </tr>
      `
      : '';
    return `
      ${parentRow}
      <tr class="lab-format-feature-row is-child-row" data-row-id="${escapeHtml(row.row_id)}">
        <td class="lab-cell-foundation lab-cell-signal lab-cell-mono lab-format-child-spacer" data-priority="essential"></td>
        <td class="lab-cell-anchor lab-format-child-spacer" data-priority="essential"></td>
        <td class="lab-cell-status lab-format-feature" data-priority="essential"><span class="lab-cell-pill">${escapeHtml(traitDisplayLabel(row.trait))}</span></td>
        <td class="lab-cell-status" data-priority="essential"><span class="lab-cell-pill ${immersiveVerdictPillClass(row.release_status)}">${escapeHtml(immersiveVerdictDisplayLabel(row.release_status))}</span></td>
        <td class="lab-cell-status" data-priority="essential"><span class="lab-cell-pill ${formatOpportunityPillClass(row.opportunity)}">${escapeHtml(formatOpportunityDisplayLabel(row.opportunity))}</span></td>
        <td class="lab-cell-supporting lab-format-copy-detail" data-priority="essential" title="${escapeHtml(copiesTitle)}"><span class="lab-cell-text">${escapeHtml(localCopySummary(row))}</span></td>
      </tr>
    `;
  }

  function repairStatusClass(row) {
    if (row.workflow_status === 'queued') return 'is-unchanged';
    if (row.workflow_status === 'weak_english') return 'is-review';
    if (row.workflow_status === 'both') return 'is-safe';
    return 'is-actionable';
  }

  function renderRepairRow(row) {
    const checked = state.selected.has(row.row_id) ? 'checked' : '';
    const disabled = repairDefaultsSelectionLocked() ? 'disabled' : '';
    const hasAudioTracks = audioTracksForRow(row).length > 0;
    const hasSubtitleTracks = subtitleTracksForRow(row).length > 0;
    const defaultAudioLabel = repairDefaultAudioLabel(row.item, row);
    const audioBitrateMarkup = hasAudioTracks
      ? `<button class="lab-audio-popover-trigger" type="button" data-track-popover="${escapeHtml(row.row_id)}" data-track-popover-kind="audio" aria-expanded="${state.trackPopoverRowId === row.row_id && state.trackPopoverKind === 'audio' ? 'true' : 'false'}">${escapeHtml(defaultAudioLabel)}</button>`
      : `<span class="lab-cell-text">${escapeHtml(defaultAudioLabel)}</span>`;
    const defaultSubtitleMarkup = hasSubtitleTracks
      ? `<button class="lab-audio-popover-trigger" type="button" data-track-popover="${escapeHtml(row.row_id)}" data-track-popover-kind="subtitle" aria-expanded="${state.trackPopoverRowId === row.row_id && state.trackPopoverKind === 'subtitle' ? 'true' : 'false'}">${escapeHtml(row.default_subtitle || 'None')}</button>`
      : `<span class="lab-cell-text">${escapeHtml(row.default_subtitle || 'None')}</span>`;
    return `
      <tr class="${escapeHtml(simpleSelectionRowClass(row.row_id))}" data-row-id="${escapeHtml(row.row_id)}">
        <td class="lab-cell-foundation lab-cell-select" data-priority="essential">${row.selectable ? `<input type="checkbox" data-row-check="${escapeHtml(row.row_id)}" ${checked} ${disabled}>` : ''}</td>
        <td class="lab-cell-anchor" data-priority="essential" title="${escapeHtml(row.current_path)}"><span class="lab-cell-text">${escapeHtml(fileNameFromPath(row.current_path))}</span></td>
        <td class="lab-cell-signal lab-cell-mono" data-priority="medium" title="${escapeHtml(defaultAudioLabel)}">${audioBitrateMarkup}</td>
        <td class="lab-cell-supporting" data-priority="desktop" title="${escapeHtml(row.default_subtitle || 'None')}">${defaultSubtitleMarkup}</td>
        <td class="lab-cell-decision" data-priority="essential" title="${escapeHtml(row.issue)}"><span class="lab-cell-text">${escapeHtml(row.issue)}</span></td>
        <td class="lab-cell-supporting" data-priority="medium" title="${escapeHtml(row.current_default || '—')}"><span class="lab-cell-text">${escapeHtml(row.current_default || '—')}</span></td>
        <td class="lab-cell-supporting" data-priority="desktop" title="${escapeHtml(row.repair_target || '—')}"><span class="lab-cell-text">${escapeHtml(row.repair_target || '—')}</span></td>
        <td class="lab-cell-signal lab-cell-mono" data-priority="medium" title="${escapeHtml(row.resolution || '—')}"><span class="lab-cell-text">${escapeHtml(row.resolution || '—')}</span></td>
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

  function synchronizeSelectionWithRows() {
    const key = (usesSimpleSelectionShell() || isImmersiveMode()) ? 'row_id' : 'result_id';
    const available = new Set(state.rows.map(row => row[key]).filter(Boolean));
    state.selected = new Set([...state.selected].filter(id => available.has(id)));
    if (state.activeRowId && !available.has(state.activeRowId)) state.activeRowId = '';
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
        if (isImmersiveMode()) return;
        state.activeRowId = rowEl.dataset.rowId || '';
        renderSidePanel();
      });
    });
    el.rowsBody.querySelectorAll('input[data-row-check]').forEach(input => {
      input.addEventListener('change', async () => {
        if (isRepairDefaultsMode() && repairDefaultsSelectionLocked()) {
          input.checked = state.selected.has(input.dataset.rowCheck || '');
          return;
        }
        const id = input.dataset.rowCheck || '';
        if (input.checked) state.selected.add(id);
        else {
          state.selected.delete(id);
          if (usesSimpleSelectionShell() && state.activeRowId === id) state.activeRowId = '';
        }
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
    });
    el.rowsBody.querySelectorAll('button[data-track-popover]').forEach(button => {
      button.addEventListener('click', event => {
        event.stopPropagation();
        const rowId = button.dataset.trackPopover || '';
        const kind = button.dataset.trackPopoverKind || 'audio';
        if (!rowId) return;
        if (state.trackPopoverRowId === rowId && state.trackPopoverKind === kind) {
          closeTrackPopover();
          return;
        }
        state.trackPopoverRowId = rowId;
        state.trackPopoverKind = kind;
        renderTrackPopover();
      });
    });
  }

  function renderTrackPopover() {
    const popover = el.trackPopover;
    if (!popover) return;
    const row = rowById(state.trackPopoverRowId);
    const anchor = state.trackPopoverRowId
      ? el.rowsBody.querySelector(`button[data-track-popover="${CSS.escape(state.trackPopoverRowId)}"][data-track-popover-kind="${CSS.escape(state.trackPopoverKind || 'audio')}"]`)
      : null;
    const tracks = audioTracksForRow(row);
    const subtitleTracks = subtitleTracksForRow(row);
    if (!row || !anchor) {
      closeTrackPopover();
      return;
    }
    if (isCanonicalMode()) {
      const facts = canonicalInspectorFacts(row);
      if (!row.item || !facts.length) {
        closeTrackPopover();
        return;
      }
      popover.innerHTML = `
        <div class="lab-audio-popover-title">Quality Profile Inspector</div>
        <ul class="lab-audio-popover-list">
          ${facts.map(([label, value]) => `
            <li class="lab-audio-popover-row">
              <span class="lab-audio-popover-lang">${escapeHtml(label)}</span>
              <span class="lab-audio-popover-facts">${escapeHtml(value)}</span>
            </li>
          `).join('')}
        </ul>
      `;
      popover.hidden = false;
      positionTrackPopover(anchor, popover);
      el.rowsBody.querySelectorAll('button[data-track-popover]').forEach(button => {
        button.setAttribute('aria-expanded', button.dataset.trackPopover === state.trackPopoverRowId && button.dataset.trackPopoverKind === state.trackPopoverKind ? 'true' : 'false');
      });
      return;
    }
    if (state.trackPopoverKind === 'subtitle') {
      if (!isRepairDefaultsMode() || !subtitleTracks.length) {
        closeTrackPopover();
        return;
      }
      popover.innerHTML = `
        <div class="lab-audio-popover-title">Subtitle Tracks</div>
        <ul class="lab-audio-popover-list">
          ${subtitleTracks.map(track => `
            <li class="lab-audio-popover-row">
              ${popoverTrackLanguageMarkup(describeSubtitleStream(track), !!track.is_default)}
              <span class="lab-audio-popover-facts">${escapeHtml(track.is_forced ? 'forced' : 'full')}</span>
            </li>
          `).join('')}
        </ul>
      `;
      popover.hidden = false;
      positionTrackPopover(anchor, popover);
      el.rowsBody.querySelectorAll('button[data-track-popover]').forEach(button => {
        button.setAttribute('aria-expanded', button.dataset.trackPopover === state.trackPopoverRowId && button.dataset.trackPopoverKind === state.trackPopoverKind ? 'true' : 'false');
      });
      return;
    }
    if (!tracks.length) {
      closeTrackPopover();
      return;
    }
    popover.innerHTML = `
      <div class="lab-audio-popover-title">Audio Tracks</div>
      <ul class="lab-audio-popover-list">
        ${tracks.map(track => `
          <li class="lab-audio-popover-row">
            ${popoverTrackLanguageMarkup(displayAudioLanguage(track.language), isEffectiveDefaultAudioTrack(track, row))}
            <span class="lab-audio-popover-facts">${escapeHtml(describeAudioPopoverFacts(track, row))}</span>
          </li>
        `).join('')}
      </ul>
    `;
    popover.hidden = false;
    positionTrackPopover(anchor, popover);
    el.rowsBody.querySelectorAll('button[data-track-popover]').forEach(button => {
      button.setAttribute('aria-expanded', button.dataset.trackPopover === state.trackPopoverRowId && button.dataset.trackPopoverKind === state.trackPopoverKind ? 'true' : 'false');
    });
  }

  function positionTrackPopover(anchor, popover) {
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

  function closeTrackPopover() {
    state.trackPopoverRowId = '';
    state.trackPopoverKind = '';
    if (!el.trackPopover) return;
    el.trackPopover.hidden = true;
    el.trackPopover.innerHTML = '';
    el.rowsBody.querySelectorAll('button[data-track-popover]').forEach(button => {
      button.setAttribute('aria-expanded', 'false');
    });
  }

  function rowById(rowId) {
    const key = (usesSimpleSelectionShell() || isCanonicalMode() || isImmersiveMode()) ? 'row_id' : 'result_id';
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
    (node._files || []).slice().sort((a, b) => {
      const leftHasSequence = Number.isFinite(a.sequence);
      const rightHasSequence = Number.isFinite(b.sequence);
      if (leftHasSequence || rightHasSequence) {
        if (!leftHasSequence) return 1;
        if (!rightHasSequence) return -1;
        if (a.sequence !== b.sequence) return a.sequence - b.sequence;
      }
      return a.name.localeCompare(b.name);
    }).forEach(file => {
      lines.push({
        label: file.folder ? `${file.name}/` : file.name,
        depth,
        mutated: Boolean(file.mutated),
        selected: Boolean(file.selected),
        deleted: Boolean(file.deleted),
        cleanup: Boolean(file.cleanup),
        staged: Boolean(file.staged),
        landing: Boolean(file.landing),
        unresolved: Boolean(file.unresolved),
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
    const markAncestorsSelected = flags.markAncestorsSelected !== false;
    const propagateDeleteState = !!flags.propagateDeleteState;
    const propagateCleanupState = !!flags.propagateCleanupState;
    let node = tree;
    parts.forEach((part, index) => {
      const isFile = index === parts.length - 1;
      if (isFile) {
        if (!node._files) node._files = [];
        node._files.push({ name: part, ...flags });
        return;
      }
      node[part] = node[part] || {};
      if (flags.deleted && propagateDeleteState) node[part]._deleted = true;
      if (flags.cleanup && propagateCleanupState) node[part]._cleanup = true;
      if (flags.selected && markAncestorsSelected) node[part]._selected = true;
      node = node[part];
    });
  }

  function renderPreviewTreeMarkup(tree) {
    const lines = [];
    flattenPreviewTree(tree, lines, 0);
    return `
      <div class="lab-tree">
        ${lines.map(line => `
          <div class="lab-tree-line lab-indent-${Math.min(line.depth, 5)} ${line.mutated ? 'is-mutated' : ''} ${line.selected ? 'is-selected' : ''} ${line.deleted ? 'is-deleted' : ''} ${line.cleanup ? 'is-cleanup' : ''} ${line.staged ? 'is-staged' : ''} ${line.landing ? 'is-landing' : ''} ${line.unresolved ? 'is-unresolved' : ''}">
            <span class="lab-tree-line-label">${escapeHtml(line.label)}</span>
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

  function weakSelectedPreviewTree(preview) {
    const tree = {};
    (preview.deleted || []).forEach(path => addPathToTree(tree, relativeToSource(path), { deleted: true, selected: true, markAncestorsSelected: false }));
    (preview.cleaned_sidecars || []).forEach(path => addPathToTree(tree, relativeToSource(path), { cleanup: true, selected: true, markAncestorsSelected: false }));
    (preview.removed_folders || []).forEach(path => addPathToTree(tree, relativeToSource(path), { cleanup: true, selected: true, folder: true, markAncestorsSelected: false }));
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
    const tree = weakSelectedPreviewTree(preview);
    const reclaimedBytes = state.filteredRows
      .filter(row => state.selected.has(row.row_id) && row.selectable)
      .reduce((sum, row) => sum + (Number(row.file_size) || 0), 0);
    el.previewPane.innerHTML = `
      <div class="lab-preview-summary">
        <strong>${preview.deleted.length}</strong> deleted media file${preview.deleted.length === 1 ? '' : 's'}.
        ${reclaimedBytes ? `<span class="chip delete">${formatFileSize(reclaimedBytes)} reclaimed</span>` : ''}
        <span class="chip delete">${preview.cleaned_sidecars.length} cleaned sidecar${preview.cleaned_sidecars.length === 1 ? '' : 's'}</span>
        <span class="chip">${preview.removed_folders.length} removed folder${preview.removed_folders.length === 1 ? '' : 's'}</span>
      </div>
      ${tree}
      ${preview.skipped.length ? `<div class="lab-preview-summary">Skipped: ${escapeHtml(preview.skipped.map(item => `${item.path || ''} ${item.reason || ''}`.trim()).join(' | '))}</div>` : ''}
    `;
  }

  function junkSelectedPreviewTree(rows) {
    const tree = {};
    rows.forEach(row => addPathToTree(tree, row.item?.relative_path || row.current_path || '', { deleted: true, selected: true, markAncestorsSelected: false }));
    return renderPreviewTreeMarkup(tree);
  }

  function renderJunkPreviewPane() {
    const selected = selectedJunkItems();
    if (!state.junkPayload) {
      el.previewPane.textContent = 'Run Remove Junk Files to inspect delete preview.';
      return;
    }
    if (!selected.length) {
      el.previewPane.innerHTML = `
        <div class="lab-preview-empty">
          <strong>No rows selected.</strong>
          <div>Select junk candidates to preview files marked as deleted.</div>
        </div>
      `;
      return;
    }
    const previewRows = state.filteredRows.filter(row => state.selected.has(row.row_id));
    const tree = junkSelectedPreviewTree(previewRows);
    const reclaimedBytes = previewRows.reduce((sum, row) => sum + (Number(row.file_size) || 0), 0);
    el.previewPane.innerHTML = `
      <div class="lab-preview-summary">
        <strong>${previewRows.length}</strong> selected junk file${previewRows.length === 1 ? '' : 's'} staged for deletion.
        ${reclaimedBytes ? `<span class="chip delete">${formatFileSize(reclaimedBytes)} reclaimed</span>` : ''}
        ${state.junkDeleteSkipped.length ? `<span class="chip">${state.junkDeleteSkipped.length} skipped on last delete</span>` : ''}
      </div>
      ${tree}
      ${state.junkDeleteSkipped.length ? `<div class="lab-preview-summary">Skipped: ${escapeHtml(state.junkDeleteSkipped.map(item => `${relativeToSource(item.path || '')} ${item.reason || ''}`.trim()).join(' | '))}</div>` : ''}
    `;
  }

  function repairPreviewTreeForRow(row, action = state.repairAction) {
    const tree = {};
    const relPath = relativeToSource(row.current_path || row.path || '');
    addPathToTree(tree, relPath, { selected: true });
    const containerNode = relPath.split('/').filter(Boolean).reduce((node, part, index, parts) => {
      if (index === parts.length - 1) {
        node[part] = node[part] || {};
        return node[part];
      }
      node[part] = node[part] || {};
      return node[part];
    }, tree);
    let sequence = 0;
    const model = buildRepairPreviewModel(row.item, action);
    model.nodes.forEach(node => addPathToTree(containerNode, node.path, { ...node.flags, sequence: sequence++ }));
    return renderPreviewTreeMarkup(tree);
  }

  function canonicalAudioLanguageValue(language) {
    const value = String(language || '').trim().toLowerCase();
    if (['eng', 'en', 'english'].includes(value)) return 'english';
    if (!value) return '';
    return value;
  }

  // Lossless remux is a stream copy, so wall-clock is I/O-bound and tracks
  // file_size / throughput. The constant is biased to this drive's slow floor
  // (~50 MB/s) on purpose: under-promising lets page-cache bursts finish the real
  // job ahead of the bar and snap it home, which reads as "done early" rather than
  // "stuck near the end". This only paces the facade; completion stays gated on the
  // activity focus advancing.
  const REMUX_BYTES_PER_SECOND = 50 * 1024 * 1024;

  function remuxEtaSeconds(bytes) {
    const size = Number(bytes) || 0;
    if (size <= 0) return 12;
    return Math.max(2, size / REMUX_BYTES_PER_SECOND);
  }

  function buildRepairPreviewPane(rows, action = state.repairAction) {
    if (!rows.length) return '<div class="lab-preview-empty"><strong>No visible items.</strong></div>';
    return rows.map(row => `
      <div class="lab-preview-item" data-remux-path="${escapeHtml(normalizePathKey(row.current_path || row.path || ''))}" data-remux-bytes="${Number(row.item?.facts?.file_size_bytes) || 0}">
        <div class="lab-preview-item-title lab-repair-card-head">
          <span class="lab-repair-card-name">${escapeHtml(fileNameFromPath(row.current_path || row.path || ''))}</span>
          <span class="lab-remux-status" data-remux-status hidden></span>
        </div>
        <div class="lab-preview-item-body">${repairPreviewTreeForRow(row, action)}</div>
      </div>
    `).join('');
  }

  // Patch remux focus onto the existing card nodes in place. The card matching the
  // backend's current_path is in flight; any card whose path we've already seen
  // complete shows done; everything else is still waiting. Completion is tracked by
  // path, not card order, since the backend doesn't walk the queue top-to-bottom.
  function syncRemuxCardStates() {
    updateRemuxFocusPath();
    const cards = el.previewPane
      ? Array.from(el.previewPane.querySelectorAll('.lab-preview-item[data-remux-path]'))
      : [];
    if (!cards.length) return;
    const focus = state.activeRemuxPath;
    cards.forEach((card) => {
      const path = card.dataset.remuxPath;
      const remuxing = !!focus && path === focus;
      const done = !remuxing && state.completedRemuxPaths.has(path);
      // Set the facade duration only as the card enters the in-flight state, so the
      // CSS fill transition runs once from empty rather than restarting each 2s poll.
      // Arm a timer for that same eta: when it fires the bar has reached its 0.88 cap,
      // so we hand off to the finalizing crawl (0.88 -> 0.96) instead of dead-stopping.
      if (remuxing && !card.classList.contains('is-remuxing')) {
        const eta = remuxEtaSeconds(card.dataset.remuxBytes);
        card.style.setProperty('--remux-eta', `${eta}s`);
        clearRemuxFinalizeTimer(card);
        card._remuxFinalizeTimer = window.setTimeout(() => {
          card.classList.add('is-remux-finalizing');
        }, eta * 1000);
      } else if (!remuxing) {
        card.style.removeProperty('--remux-eta');
        clearRemuxFinalizeTimer(card);
        card.classList.remove('is-remux-finalizing');
      }
      card.classList.toggle('is-remuxing', remuxing);
      card.classList.toggle('is-remux-done', done);
      const status = card.querySelector('[data-remux-status]');
      if (!status) return;
      status.classList.toggle('is-active', remuxing);
      status.classList.toggle('is-done', done);
      status.hidden = !remuxing && !done;
      if (remuxing) {
        const finalizing = card.classList.contains('is-remux-finalizing');
        status.innerHTML = `<span class="lab-remux-dot"></span>${finalizing ? 'finalizing lossless mux' : 'remuxing'}`;
      } else {
        status.innerHTML = done ? 'done' : '';
      }
    });
  }

  function clearRemuxFinalizeTimer(card) {
    if (card._remuxFinalizeTimer) {
      window.clearTimeout(card._remuxFinalizeTimer);
      card._remuxFinalizeTimer = 0;
    }
  }

  function combinedRepairRunsSingleRemux(action = state.repairAction) {
    return actionTouchesAudio(action) && actionTouchesSubtitle(action);
  }

  function repairReclaimedBytes(rows, action) {
    const cfg = repairActionConfig(action);
    if (!cfg.dropForeignAudio) return 0;
    return rows.reduce((sum, row) => {
      const streams = row.item?.facts?.audio_streams || [];
      const dropped = streams
        .filter(stream => {
          const lang = canonicalAudioLanguageValue(stream.language);
          return lang && lang !== 'english';
        })
        .reduce((bits, stream) => bits + (Number(stream.bitrate_kbps) || 0), 0);
      if (!dropped) return sum;
      const audioBits = streams.reduce((bits, stream) => bits + (Number(stream.bitrate_kbps) || 0), 0);
      const totalBits = (Number(row.item?.facts?.video_bitrate_kbps) || 0) + audioBits;
      const fileSize = Number(row.item?.facts?.file_size_bytes) || 0;
      if (!totalBits || !fileSize) return sum;
      return sum + fileSize * (dropped / totalBits);
    }, 0);
  }

  function renderRepairPreviewPane() {
    if (!state.repairPayload) {
      el.previewPane.textContent = 'Run Fix Audio and Subtitle Defaults to inspect repair consequences.';
      return;
    }
    const selection = selectedRepairApplicability();
    const visibleRows = repairRowsForAction(state.filteredRows);
    const previewRows = selection.applicableRows;
    if (!selection.selectedRows.length) {
      state.repairPreviewSignature = '';
      el.previewPane.innerHTML = `
        <div class="lab-preview-empty">
          <strong>No rows selected.</strong>
          <div>${escapeHtml(repairActionConfig().emptyText)}</div>
        </div>
      `;
      return;
    }
    if (!previewRows.length) {
      state.repairPreviewSignature = '';
      el.previewPane.innerHTML = `
        <div class="lab-preview-empty">
          <strong>No applicable rows.</strong>
          <div>The current selection does not support this action.</div>
        </div>
      `;
      return;
    }
    const config = repairActionConfig();
    const executionDetail = combinedRepairRunsSingleRemux(state.repairAction)
      ? ' One lossless remux runs per file.'
      : '';
    const summary = `${previewRows.length} selected ${config.summaryNoun}${previewRows.length === 1 ? '' : 's'} staged for ${config.label.toLowerCase()}.${executionDetail}`;
    const mixedSelectionLabel = selection.skippedRows.length
      ? `${selection.selectedRows.length} selected, ${selection.applicableRows.length} applicable, ${selection.skippedRows.length} skipped`
      : '';
    // Rebuild only when the card set or surrounding copy actually changes. During a
    // live remux the structure is stable, so the 2s activity poll just patches the
    // focus onto the persistent card nodes — keeping the heartbeat animation alive
    // and sparing the pane a full innerHTML churn every tick.
    const signature = [
      state.repairAction,
      summary,
      mixedSelectionLabel,
      state.repairActionNotice,
      previewRows.map(row => normalizePathKey(row.current_path || row.path || '')).join('|'),
    ].join('::');
    if (state.repairPreviewSignature === signature
        && el.previewPane.querySelector('.lab-preview-item[data-remux-path]')) {
      syncRemuxCardStates();
      return;
    }
    state.repairPreviewSignature = signature;
    state.completedRemuxPaths.clear();
    const reclaimedBytes = repairReclaimedBytes(previewRows, state.repairAction);
    el.previewPane.innerHTML = `
      <div class="lab-preview-summary">
        <strong>${summary}</strong>
        ${reclaimedBytes ? `<span class="chip delete">~${formatFileSize(reclaimedBytes)} reclaimed</span>` : ''}
        ${mixedSelectionLabel ? `<span class="chip">${escapeHtml(mixedSelectionLabel)}</span>` : ''}
        ${state.repairActionNotice ? `<span class="chip">${escapeHtml(state.repairActionNotice)}</span>` : ''}
      </div>
      <div class="lab-preview-list">
        ${buildRepairPreviewPane(previewRows, state.repairAction)}
      </div>
    `;
    syncRemuxCardStates();
  }

  const LOPSIDED_DEFAULTS = {
    audio_kbps_per_channel: 107,
    audio_efficient_kbps_per_channel: 85,
    starved_ratio: 0.5,
    min_spread: 2.5,
  };
  const LOPSIDED_CLAMPS = {
    audio_kbps_per_channel: [40, 160],
    audio_efficient_kbps_per_channel: [40, 160],
    starved_ratio: [0.2, 0.8],
    min_spread: [1.5, 5.0],
  };
  const LOPSIDED_FALLBACK_EFFICIENT = ['aac', 'eac3'];
  const LOPSIDED_FALLBACK_LOSSLESS = ['truehd', 'dtshd', 'flac', 'pcm'];
  const LOPSIDED_HEALTHY_RATIO = 1.0;
  const LOPSIDED_VB_W = 600;
  const LOPSIDED_VB_H = 168;
  const LOPSIDED_PLOT = { left: 12, right: 14, top: 14, bottom: 26 };
  const LOPSIDED_MAX_DOTS = 600;

  function lopsidedClamp(key, value) {
    const [low, high] = LOPSIDED_CLAMPS[key];
    let n = Number(value);
    if (!isFinite(n)) n = LOPSIDED_DEFAULTS[key];
    return Math.max(low, Math.min(high, n));
  }

  function lopsidedStandards() {
    return activeProfilePayload()?.movie_standards || currentPolicyPayload()?.movie_standards || {};
  }

  function lopsidedRevision() {
    return activeProfilePayload()?.movie_standards_revision
      || currentPolicyPayload()?.movie_standards_revision
      || '';
  }

  function lopsidedSavedConfig() {
    const block = lopsidedStandards().lopsided_encode || {};
    const base = lopsidedClamp('audio_kbps_per_channel', block.audio_kbps_per_channel ?? LOPSIDED_DEFAULTS.audio_kbps_per_channel);
    const efficient = lopsidedClamp('audio_efficient_kbps_per_channel', block.audio_efficient_kbps_per_channel ?? LOPSIDED_DEFAULTS.audio_efficient_kbps_per_channel);
    return {
      audio_kbps_per_channel: base,
      audio_efficient_kbps_per_channel: Math.min(efficient, base),
      starved_ratio: lopsidedClamp('starved_ratio', block.starved_ratio ?? LOPSIDED_DEFAULTS.starved_ratio),
      min_spread: lopsidedClamp('min_spread', block.min_spread ?? LOPSIDED_DEFAULTS.min_spread),
      efficient_audio_codecs: (block.efficient_audio_codecs || LOPSIDED_FALLBACK_EFFICIENT).map(c => String(c).toLowerCase()),
      lossless_audio_codecs: (block.lossless_audio_codecs || LOPSIDED_FALLBACK_LOSSLESS).map(c => String(c).toLowerCase()),
      healthy_ratio: Number(block.healthy_ratio ?? LOPSIDED_HEALTHY_RATIO) || LOPSIDED_HEALTHY_RATIO,
    };
  }

  function lopsidedDraftConfig() {
    const cfg = lopsidedSavedConfig();
    const draft = state.lopsidedDraft || {};
    ['audio_kbps_per_channel', 'audio_efficient_kbps_per_channel', 'starved_ratio', 'min_spread'].forEach(key => {
      if (draft[key] != null) cfg[key] = lopsidedClamp(key, draft[key]);
    });
    cfg.audio_efficient_kbps_per_channel = Math.min(cfg.audio_efficient_kbps_per_channel, cfg.audio_kbps_per_channel);
    return cfg;
  }

  function lopsidedDirty() {
    const saved = lopsidedSavedConfig();
    const draft = lopsidedDraftConfig();
    return ['audio_kbps_per_channel', 'audio_efficient_kbps_per_channel', 'starved_ratio', 'min_spread']
      .some(key => Math.abs(saved[key] - draft[key]) > 1e-9);
  }

  function lopsidedSetDraft(key, value) {
    const draft = { ...(state.lopsidedDraft || {}) };
    draft[key] = lopsidedClamp(key, value);
    if (key === 'audio_kbps_per_channel') {
      const cap = draft[key];
      const eff = draft.audio_efficient_kbps_per_channel != null
        ? draft.audio_efficient_kbps_per_channel
        : lopsidedSavedConfig().audio_efficient_kbps_per_channel;
      if (eff > cap) draft.audio_efficient_kbps_per_channel = cap;
    }
    if (key === 'audio_efficient_kbps_per_channel') {
      const cap = draft.audio_kbps_per_channel != null
        ? draft.audio_kbps_per_channel
        : lopsidedSavedConfig().audio_kbps_per_channel;
      if (draft[key] > cap) draft[key] = cap;
    }
    state.lopsidedDraft = draft;
  }

  function lopsidedBuildFacts() {
    const movies = currentDashboardPayload()?.movies || activeProfilePayload()?.movies || [];
    const cfg = lopsidedSavedConfig();
    const standards = lopsidedStandards();
    const facts = [];
    movies.forEach((item, index) => {
      const f = item?.facts || {};
      const channels = Number(f.audio_channels || 0);
      const audioBitrate = Number(f.audio_bitrate_kbps || 0);
      const videoBitrate = Number(f.video_bitrate_kbps || 0);
      const resolution = String(f.resolution_bucket || '').toLowerCase();
      const videoCfg = (standards.video || {})[resolution] || {};
      const videoReference = Number(videoCfg.reference_kbps || 0) || Number(videoCfg.minimum_kbps || 0);
      if (!channels || !audioBitrate || !videoBitrate || !videoReference) return;
      const codec = String(f.audio_format_family || f.audio_codec || '').toLowerCase();
      let codecClass = 'baseline';
      if (cfg.lossless_audio_codecs.includes(codec)) codecClass = 'lossless';
      else if (cfg.efficient_audio_codecs.includes(codec)) codecClass = 'efficient';
      facts.push({
        index,
        title: fileNameFromPath(item.relative_path || item.path || '') || 'Untitled',
        audioPerCh: audioBitrate / channels,
        videoRatio: videoBitrate / videoReference,
        codec,
        codecClass,
        channels,
        audioBitrate,
        videoBitrate,
        estimated: !!(f.audio_bitrate_estimated || f.video_bitrate_approximate),
      });
    });
    return facts;
  }

  function lopsidedFacts() {
    const movies = currentDashboardPayload()?.movies || activeProfilePayload()?.movies || [];
    const signature = `${lopsidedRevision()}|${movies.length}`;
    if (!state._lopsidedFactsCache || state._lopsidedFactsCache.signature !== signature) {
      state._lopsidedFactsCache = { signature, facts: lopsidedBuildFacts() };
    }
    return state._lopsidedFactsCache.facts;
  }

  function lopsidedVerdict(f, cfg) {
    const perChannel = f.codecClass === 'efficient'
      ? cfg.audio_efficient_kbps_per_channel
      : cfg.audio_kbps_per_channel;
    if (perChannel <= 0) return null;
    const audioRatio = f.audioPerCh / perChannel;
    const videoRatio = f.videoRatio;
    const high = Math.max(videoRatio, audioRatio);
    const low = Math.min(videoRatio, audioRatio);
    if (low <= 0 || high < cfg.healthy_ratio || low > cfg.starved_ratio) return null;
    const spread = high / low;
    if (spread < cfg.min_spread) return null;
    if (audioRatio <= videoRatio) {
      if (f.codecClass === 'lossless') return null;
      return { side: 'audio', spread, confidence: f.estimated ? 'review' : 'fail' };
    }
    return { side: 'video', spread, confidence: f.estimated ? 'review' : 'fail' };
  }

  function lopsidedHitCount(facts, cfg) {
    let n = 0;
    for (const f of facts) if (lopsidedVerdict(f, cfg)) n++;
    return n;
  }

  function lopsidedAudioPerChDomainMax(facts) {
    let max = 160;
    for (const f of facts) if (f.audioPerCh > max) max = f.audioPerCh;
    return Math.min(max * 1.02, 400);
  }

  function lopsidedXToPx(value, domainMax) {
    const span = LOPSIDED_VB_W - LOPSIDED_PLOT.left - LOPSIDED_PLOT.right;
    return LOPSIDED_PLOT.left + (Math.max(0, value) / domainMax) * span;
  }

  function lopsidedPxToX(px, domainMax) {
    const span = LOPSIDED_VB_W - LOPSIDED_PLOT.left - LOPSIDED_PLOT.right;
    return Math.max(0, ((px - LOPSIDED_PLOT.left) / span) * domainMax);
  }

  function lopsidedJitterY(index) {
    const top = LOPSIDED_PLOT.top + 4;
    const bottom = LOPSIDED_VB_H - LOPSIDED_PLOT.bottom - 4;
    const pseudo = (Math.sin(index * 12.9898) * 43758.5453) % 1;
    const frac = pseudo < 0 ? pseudo + 1 : pseudo;
    return top + frac * (bottom - top);
  }

  function lopsidedSampleFacts(facts) {
    if (facts.length <= LOPSIDED_MAX_DOTS) return facts;
    const step = facts.length / LOPSIDED_MAX_DOTS;
    const sampled = [];
    for (let i = 0; i < LOPSIDED_MAX_DOTS; i += 1) sampled.push(facts[Math.floor(i * step)]);
    return sampled;
  }

  function lopsidedFloorSvg(facts, cfg) {
    const domainMax = lopsidedAudioPerChDomainMax(facts);
    const baseX = lopsidedXToPx(cfg.audio_kbps_per_channel, domainMax);
    const effX = lopsidedXToPx(cfg.audio_efficient_kbps_per_channel, domainMax);
    const starvedX = lopsidedXToPx(cfg.audio_kbps_per_channel * cfg.starved_ratio, domainMax);
    const yTop = LOPSIDED_PLOT.top;
    const yBottom = LOPSIDED_VB_H - LOPSIDED_PLOT.bottom;
    const dots = lopsidedSampleFacts(facts).map(f => {
      const cx = lopsidedXToPx(f.audioPerCh, domainMax).toFixed(1);
      const cy = lopsidedJitterY(f.index).toFixed(1);
      return `<circle class="lab-lopsided-dot is-${f.codecClass}" cx="${cx}" cy="${cy}" r="2.4"></circle>`;
    }).join('');
    const ticks = [0, 40, 85, 107, Math.round(domainMax)].filter((v, i, arr) => arr.indexOf(v) === i && v <= domainMax)
      .map(v => {
        const x = lopsidedXToPx(v, domainMax).toFixed(1);
        return `<line class="lab-lopsided-tick" x1="${x}" y1="${yBottom}" x2="${x}" y2="${yBottom + 4}"></line>`
          + `<text class="lab-lopsided-axis" x="${x}" y="${yBottom + 15}" text-anchor="middle">${v}</text>`;
      }).join('');
    const line = (knob, x, klass, label) => `
      <g class="lab-lopsided-line ${klass}" data-lopsided-knob="${knob}" tabindex="0" role="slider">
        <rect class="lab-lopsided-grab" x="${(x - 7).toFixed(1)}" y="${yTop - 2}" width="14" height="${yBottom - yTop + 6}"></rect>
        <line x1="${x.toFixed(1)}" y1="${yTop}" x2="${x.toFixed(1)}" y2="${yBottom}"></line>
        <polygon class="lab-lopsided-handle" points="${(x - 4).toFixed(1)},${yTop - 6} ${(x + 4).toFixed(1)},${yTop - 6} ${x.toFixed(1)},${yTop}"></polygon>
        <text class="lab-lopsided-line-label" x="${x.toFixed(1)}" y="${yTop - 9}" text-anchor="middle">${label}</text>
      </g>`;
    return `
      <svg class="lab-lopsided-floor" viewBox="0 0 ${LOPSIDED_VB_W} ${LOPSIDED_VB_H}" preserveAspectRatio="none" data-lopsided-domain-max="${domainMax}">
        <rect class="lab-lopsided-starved-zone" x="${LOPSIDED_PLOT.left}" y="${yTop}" width="${(starvedX - LOPSIDED_PLOT.left).toFixed(1)}" height="${yBottom - yTop}"></rect>
        <line class="lab-lopsided-baseline-axis" x1="${LOPSIDED_PLOT.left}" y1="${yBottom}" x2="${LOPSIDED_VB_W - LOPSIDED_PLOT.right}" y2="${yBottom}"></line>
        ${ticks}
        ${dots}
        ${line('starved', starvedX, 'is-starved', '½')}
        ${line('audio_efficient_kbps_per_channel', effX, 'is-efficient', 'eff')}
        ${line('audio_kbps_per_channel', baseX, 'is-base', 'base')}
      </svg>`;
  }

  function lopsidedMiniHist(values, lo, hi, marker, klass) {
    const bins = 24;
    const counts = new Array(bins).fill(0);
    values.forEach(v => {
      if (v < lo || v > hi) return;
      let idx = Math.floor(((v - lo) / (hi - lo)) * bins);
      if (idx >= bins) idx = bins - 1;
      if (idx < 0) idx = 0;
      counts[idx] += 1;
    });
    const max = Math.max(1, ...counts);
    const w = 220;
    const h = 40;
    const bw = w / bins;
    const bars = counts.map((c, i) => {
      const bh = (c / max) * (h - 2);
      return `<rect class="lab-lopsided-hist-bar" x="${(i * bw).toFixed(1)}" y="${(h - bh).toFixed(1)}" width="${(bw - 0.6).toFixed(1)}" height="${bh.toFixed(1)}"></rect>`;
    }).join('');
    const mx = (((Math.max(lo, Math.min(hi, marker)) - lo) / (hi - lo)) * w).toFixed(1);
    return `
      <svg class="lab-lopsided-hist ${klass}" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
        ${bars}
        <line class="lab-lopsided-hist-marker" x1="${mx}" y1="0" x2="${mx}" y2="${h}"></line>
      </svg>`;
  }

  function lopsidedFormatValue(knob, value) {
    if (knob === 'min_spread' || knob === 'starved_ratio') return `${value.toFixed(2)}×`;
    return `${Math.round(value)} kbps`;
  }

  function lopsidedKnobsView(facts, cfg) {
    const perChValues = facts.map(f => f.audioPerCh);
    const lowValues = [];
    const spreadValues = [];
    facts.forEach(f => {
      const perChannel = f.codecClass === 'efficient' ? cfg.audio_efficient_kbps_per_channel : cfg.audio_kbps_per_channel;
      const audioRatio = perChannel > 0 ? f.audioPerCh / perChannel : 0;
      const high = Math.max(f.videoRatio, audioRatio);
      const low = Math.min(f.videoRatio, audioRatio);
      lowValues.push(low);
      if (low > 0 && high >= cfg.healthy_ratio) spreadValues.push(high / low);
    });
    const register = (knob, klass, label, value, step, spark) => {
      const [min, max] = LOPSIDED_CLAMPS[knob];
      return `
        <div class="lab-lopsided-register is-${klass}">
          <div class="lab-lopsided-register-label">
            <span class="lab-lopsided-register-name">${label}</span>
            <span class="lab-lopsided-register-value" data-lopsided-value="${knob}">${lopsidedFormatValue(knob, value)}</span>
          </div>
          <input class="lab-lopsided-slider" type="range" data-lopsided-slider="${knob}"
            min="${min}" max="${max}" step="${step}" value="${value}">
          <div class="lab-lopsided-spark">${spark}</div>
        </div>`;
    };
    return `
      <div class="lab-lopsided-registers">
        ${register('audio_efficient_kbps_per_channel', 'efficient', 'AAC / EAC3 FLOOR', cfg.audio_efficient_kbps_per_channel, 1, lopsidedMiniHist(perChValues, 0, 200, cfg.audio_efficient_kbps_per_channel, 'is-efficient'))}
        ${register('audio_kbps_per_channel', 'base', 'AC3 / DTS FLOOR', cfg.audio_kbps_per_channel, 1, lopsidedMiniHist(perChValues, 0, 200, cfg.audio_kbps_per_channel, 'is-base'))}
        ${register('starved_ratio', 'starved', 'STARVED RATIO', cfg.starved_ratio, 0.01, lopsidedMiniHist(lowValues, 0, 1.5, cfg.starved_ratio, 'is-starved'))}
        ${register('min_spread', 'spread', 'MIN SPREAD (HIGH ÷ LOW)', cfg.min_spread, 0.1, lopsidedMiniHist(spreadValues, 1, 5, cfg.min_spread, 'is-spread'))}
      </div>`;
  }

  function lopsidedTunerBody(facts) {
    const saved = lopsidedSavedConfig();
    const cfg = lopsidedDraftConfig();
    const savedHits = lopsidedHitCount(facts, saved);
    const draftHits = lopsidedHitCount(facts, cfg);
    const dirty = lopsidedDirty();
    const view = state.lopsidedView === 'scatter' ? 'scatter' : 'registers';
    const viewMarkup = view === 'scatter'
      ? `${lopsidedFloorSvg(facts, cfg)}
        <div class="lab-lopsided-legend">
          <span class="is-efficient">● efficient</span>
          <span class="is-base">● baseline</span>
          <span class="is-lossless">● lossless</span>
          <span class="is-starved-key">░ starved</span>
        </div>`
      : lopsidedKnobsView(facts, cfg);
    return `
      <div class="lab-lopsided-body">
        <div class="lab-lopsided-toggle" role="tablist">
          <button type="button" data-lopsided-view="registers" class="${view === 'registers' ? 'is-active' : ''}">registers</button>
          <button type="button" data-lopsided-view="scatter" class="${view === 'scatter' ? 'is-active' : ''}">scatter</button>
        </div>
        ${viewMarkup}
        <div class="lab-lopsided-footer">
          <div class="lab-lopsided-anchor">lopsided hits: <strong>${savedHits}</strong> → <strong class="${draftHits === savedHits ? '' : 'is-changed'}" data-lopsided-draft-hits>${draftHits}</strong>
            <span class="lab-lopsided-count-note">${facts.length} files scored</span></div>
          <div class="lab-lopsided-actions">
            <button type="button" class="lab-lopsided-reset" data-lopsided-reset ${dirty ? '' : 'disabled'}>Reset</button>
            <button type="button" class="lab-lopsided-save lab-action-button is-primary" data-lopsided-save ${dirty && !state.lopsidedBusy ? '' : 'disabled'}>${state.lopsidedBusy ? 'Saving…' : 'Save'}</button>
          </div>
        </div>
      </div>`;
  }

  function lopsidedPolicySection() {
    const isOpen = state.policySectionLabel === 'lopsided_encode';
    const facts = lopsidedFacts();
    const draftHits = facts.length ? lopsidedHitCount(facts, lopsidedDraftConfig()) : 0;
    const body = !isOpen
      ? ''
      : (facts.length
        ? lopsidedTunerBody(facts)
        : `<div class="lab-lopsided-empty">Run a profile-bearing scan for this source (Review Low-Quality Encodes) to load the dot cloud, then tune the floor against your own files.</div>`);
    return `
      <section class="lab-policy-card lab-lopsided-card ${isOpen ? 'is-open' : ''}">
        <div class="lab-policy-section-header" data-policy-section="lopsided_encode" role="button" tabindex="0" aria-expanded="${isOpen ? 'true' : 'false'}">
          <div class="lab-policy-meta">
            <span class="lab-kicker">Detector</span>
            ${facts.length ? `<span class="lab-lopsided-headhits">${draftHits} hit${draftHits === 1 ? '' : 's'}</span>` : ''}
          </div>
          <h3>Lopsided encode thresholds</h3>
          <p>Tune the audio baselines, starved gate, and spread gate against your own library. Saved values apply on the next scan.</p>
        </div>
        ${body}
      </section>`;
  }

  function wireLopsidedPolicySection() {
    const host = el.policyEditorPanel;
    if (!host || state.policySectionLabel !== 'lopsided_encode') return;
    const facts = lopsidedFacts();
    if (!facts.length) return;
    wireLopsidedTuner(host, facts);
  }

  function lopsidedUpdateReadout(host, facts) {
    const cfg = lopsidedDraftConfig();
    const saved = lopsidedSavedConfig();
    const draftHits = lopsidedHitCount(facts, cfg);
    const savedHits = lopsidedHitCount(facts, saved);
    const draftEl = host.querySelector('[data-lopsided-draft-hits]');
    if (draftEl) {
      draftEl.textContent = draftHits;
      draftEl.classList.toggle('is-changed', draftHits !== savedHits);
    }
    const headHits = host.querySelector('.lab-lopsided-headhits');
    if (headHits) headHits.textContent = `${draftHits} hit${draftHits === 1 ? '' : 's'}`;
    const dirty = lopsidedDirty();
    const resetBtn = host.querySelector('[data-lopsided-reset]');
    if (resetBtn) resetBtn.disabled = !dirty;
    const saveBtn = host.querySelector('[data-lopsided-save]');
    if (saveBtn) saveBtn.disabled = !dirty || state.lopsidedBusy;
    host.querySelectorAll('[data-lopsided-value]').forEach(node => {
      const knob = node.dataset.lopsidedValue;
      node.textContent = lopsidedFormatValue(knob, cfg[knob]);
    });
    host.querySelectorAll('.lab-lopsided-headhits').forEach(node => {
      node.textContent = `${draftHits} hit${draftHits === 1 ? '' : 's'}`;
    });
  }

  function lopsidedMoveFloorLines(host, facts) {
    const svg = host.querySelector('.lab-lopsided-floor');
    if (!svg) return;
    const cfg = lopsidedDraftConfig();
    const domainMax = Number(svg.dataset.lopsidedDomainMax) || lopsidedAudioPerChDomainMax(facts);
    const yTop = LOPSIDED_PLOT.top;
    const yBottom = LOPSIDED_VB_H - LOPSIDED_PLOT.bottom;
    const place = (knob, value) => {
      const group = svg.querySelector(`[data-lopsided-knob="${knob}"]`);
      if (!group) return;
      const x = lopsidedXToPx(value, domainMax);
      group.querySelector('rect').setAttribute('x', (x - 7).toFixed(1));
      const ln = group.querySelector('line');
      ln.setAttribute('x1', x.toFixed(1));
      ln.setAttribute('x2', x.toFixed(1));
      group.querySelector('polygon').setAttribute('points', `${(x - 4).toFixed(1)},${yTop - 6} ${(x + 4).toFixed(1)},${yTop - 6} ${x.toFixed(1)},${yTop}`);
      group.querySelector('text').setAttribute('x', x.toFixed(1));
    };
    place('audio_kbps_per_channel', cfg.audio_kbps_per_channel);
    place('audio_efficient_kbps_per_channel', cfg.audio_efficient_kbps_per_channel);
    place('starved', cfg.audio_kbps_per_channel * cfg.starved_ratio);
    const zone = svg.querySelector('.lab-lopsided-starved-zone');
    if (zone) {
      const starvedX = lopsidedXToPx(cfg.audio_kbps_per_channel * cfg.starved_ratio, domainMax);
      zone.setAttribute('width', Math.max(0, starvedX - LOPSIDED_PLOT.left).toFixed(1));
    }
  }

  function wireLopsidedTuner(host, facts) {
    host.querySelectorAll('[data-lopsided-view]').forEach(button => {
      button.addEventListener('click', event => {
        event.stopPropagation();
        state.lopsidedView = button.dataset.lopsidedView;
        renderPolicyEditor();
      });
    });
    host.querySelectorAll('[data-lopsided-reset]').forEach(button => {
      button.addEventListener('click', event => {
        event.stopPropagation();
        state.lopsidedDraft = null;
        renderPolicyEditor();
      });
    });
    host.querySelectorAll('[data-lopsided-save]').forEach(button => {
      button.addEventListener('click', event => {
        event.stopPropagation();
        saveLopsidedDraft();
      });
    });
    host.querySelectorAll('[data-lopsided-slider]').forEach(input => {
      input.addEventListener('input', () => {
        lopsidedSetDraft(input.dataset.lopsidedSlider, input.value);
        lopsidedUpdateReadout(host, facts);
      });
      input.addEventListener('change', () => renderPolicyEditor());
    });
    const svg = host.querySelector('.lab-lopsided-floor');
    if (svg) {
      const domainMax = Number(svg.dataset.lopsidedDomainMax) || lopsidedAudioPerChDomainMax(facts);
      svg.querySelectorAll('[data-lopsided-knob]').forEach(group => {
        const knob = group.dataset.lopsidedKnob;
        const apply = clientX => {
          const rect = svg.getBoundingClientRect();
          const px = ((clientX - rect.left) / rect.width) * LOPSIDED_VB_W;
          const domainValue = lopsidedPxToX(px, domainMax);
          if (knob === 'starved') {
            const base = lopsidedDraftConfig().audio_kbps_per_channel;
            lopsidedSetDraft('starved_ratio', base > 0 ? domainValue / base : 0.5);
          } else {
            lopsidedSetDraft(knob, domainValue);
          }
          lopsidedMoveFloorLines(host, facts);
          lopsidedUpdateReadout(host, facts);
        };
        group.addEventListener('pointerdown', event => {
          event.preventDefault();
          group.setPointerCapture(event.pointerId);
          group.classList.add('is-dragging');
          apply(event.clientX);
        });
        group.addEventListener('pointermove', event => {
          if (!group.hasPointerCapture(event.pointerId)) return;
          apply(event.clientX);
        });
        const release = event => {
          if (!group.hasPointerCapture?.(event.pointerId)) return;
          group.releasePointerCapture(event.pointerId);
          group.classList.remove('is-dragging');
          renderPolicyEditor();
        };
        group.addEventListener('pointerup', release);
        group.addEventListener('pointercancel', release);
      });
    }
  }

  async function saveLopsidedDraft() {
    if (!lopsidedDirty() || state.lopsidedBusy) return;
    const cfg = lopsidedDraftConfig();
    state.lopsidedBusy = true;
    renderPolicyEditor();
    try {
      const result = await postJson('/api/movies/standards/update', {
        label: 'lopsided_encode',
        source: normalizeSourceKey(el.sourcePath.value),
        revision: lopsidedRevision(),
        values: {
          audio_kbps_per_channel: cfg.audio_kbps_per_channel,
          audio_efficient_kbps_per_channel: cfg.audio_efficient_kbps_per_channel,
          starved_ratio: cfg.starved_ratio,
          min_spread: cfg.min_spread,
        },
      });
      applyLopsidedSaveResult(result);
      state.lopsidedDraft = null;
      markAuditLedgerDirty();
    } catch (error) {
      window.alert?.(`Could not save lopsided thresholds: ${error.message}`);
    } finally {
      state.lopsidedBusy = false;
      renderPolicyEditor();
    }
  }

  function applyLopsidedSaveResult(result) {
    const standards = result?.movie_standards;
    const revision = result?.movie_standards_revision;
    if (!standards) return;
    [state.weakPayload, state.repairPayload, state.canonicalProfilePayload, state.immersivePayload, state.dashboardProfilePayload, state.policyPayload]
      .forEach(payload => {
        if (!payload) return;
        payload.movie_standards = standards;
        if (revision != null) payload.movie_standards_revision = revision;
      });
    state._lopsidedFactsCache = null;
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
    if (isCanonicalMode()) {
      renderCanonicalPreviewPane();
      return;
    }
    if (isImmersiveMode()) {
      renderImmersivePreviewPane();
      return;
    }
    if (isJunkMode()) {
      renderJunkPreviewPane();
      return;
    }
    renderSelectedPreview();
  }

  function renderSidePanel() {
    renderPanelVisibility();
    renderPolicyRail();
    renderDashboardPanel();
    renderPolicyEditor();
    renderAuditPanel();
    renderSettingsPanel();
    if (surfaceOpen()) {
      renderInspectionPane();
      return;
    }
    renderPreviewPane();
  }

  function renderCanonicalPreviewPane() {
    if (!state.canonicalPayload) {
      el.previewPane.textContent = 'Run Compare Against Canonical Lists to inspect list coverage.';
      return;
    }
    const summary = activeCanonicalListSummary();
    if (!summary) {
      el.previewPane.innerHTML = '<div class="lab-preview-empty"><strong>No canonical lists loaded.</strong><div>Run Compare Against Canonical Lists to load list coverage.</div></div>';
      return;
    }
    const activeRow = rowById(state.activeRowId);
    if (!activeRow) {
      const missingPreview = Array.isArray(summary.missing_titles) ? summary.missing_titles.slice(0, 6) : [];
      el.previewPane.innerHTML = `
        <div class="lab-preview-summary">
          <strong>${escapeHtml(summary.label || 'Canonical List')}</strong>
          <span class="chip">${summary.covered_count || 0}/${summary.total_count || 0} owned</span>
          <span class="chip">${summary.missing_count || 0} missing</span>
        </div>
        <div class="lab-preview-list">
          <div class="lab-preview-item">
            <div class="lab-preview-item-title">Coverage</div>
            <div class="lab-preview-item-body">${escapeHtml(`${summary.coverage_percent || 0}% coverage across ${summary.total_count || 0} titles.`)}</div>
          </div>
          <div class="lab-preview-item">
            <div class="lab-preview-item-title">Missing Preview</div>
            <div class="lab-preview-item-body">${missingPreview.length ? escapeHtml(missingPreview.map(item => `${item.title} (${item.year})`).join(' | ')) : 'Complete or near-complete coverage.'}</div>
          </div>
        </div>
      `;
      return;
    }
    const facts = canonicalInspectorFacts(activeRow);
    el.previewPane.innerHTML = `
      <div class="lab-preview-summary">
        <strong>${canonicalTitleMarkup(activeRow.title, activeRow.imdb_id)}${activeRow.year ? ` (${escapeHtml(String(activeRow.year))})` : ''}</strong>
        <span class="chip ${activeRow.owned ? '' : 'queue'}">${escapeHtml(canonicalOwnedStatusLabel(activeRow))}</span>
      </div>
      <div class="lab-preview-list">
        <div class="lab-preview-item">
          <div class="lab-preview-item-title">Library State</div>
          <div class="lab-preview-item-body">${escapeHtml(activeRow.current_path || 'Not present in the current library.')}</div>
        </div>
        <div class="lab-preview-item">
          <div class="lab-preview-item-title">Quality Profile</div>
          <div class="lab-preview-item-body">${escapeHtml(activeRow.quality_profile || '—')}</div>
        </div>
        ${facts.length ? `
          <div class="lab-preview-item">
            <div class="lab-preview-item-title">Inspector Reading</div>
            <div class="lab-preview-item-body">${escapeHtml(facts.map(([label, value]) => `${label}: ${value}`).join(' | '))}</div>
          </div>
        ` : ''}
      </div>
    `;
  }

  function renderImmersivePreviewPane() {
    if (!state.immersivePayload) {
      el.previewPane.innerHTML = '<div class="lab-preview-empty"><strong>Run Review Format Upgrade Candidates.</strong><div>Compares known releases with UHD, Dolby Vision, immersive audio, Open Matte, and Hybrid coverage across your copies.</div></div>';
      return;
    }
    const rows = immersiveRows();
    el.previewPane.innerHTML = `
      <div class="lab-preview-summary">
        <strong>Format Upgrade Candidates</strong>
        <span class="chip">${new Set(rows.map(row => `${row.title}\u0000${row.year}`)).size} title${new Set(rows.map(row => `${row.title}\u0000${row.year}`)).size === 1 ? '' : 's'}</span>
      </div>
      <div class="lab-preview-list">
        <div class="lab-preview-item">
          <div class="lab-preview-item-title">How to read this view</div>
          <div class="lab-preview-item-body">Each title owns one row per upgrade feature. <strong>Known Release</strong> reports corpus knowledge; <strong>Your Copies</strong> reports local coverage and the resulting opportunity.</div>
        </div>
        <div class="lab-preview-item">
          <div class="lab-preview-item-title">Local feature claims</div>
          <div class="lab-preview-item-body">UHD, Dolby Vision, and immersive audio are probed from media facts. Open Matte and Hybrid are read from filename tokens and accepted only when the copy clears the selected quality floor.</div>
        </div>
        <div class="lab-preview-item">
          <div class="lab-preview-item-title">Default filter</div>
          <div class="lab-preview-item-body">The default view keeps actionable, covered, quality-review, negative, and conflicting rows visible. Select Research Needed to inspect features with no release evidence.</div>
        </div>
      </div>
    `;
  }

  async function runImmersive() {
    const source = el.sourcePath.value.trim();
    const payload = await postJson('/api/movies/profile', { source });
    state.immersivePayload = payload;
    markAuditLedgerDirty();
    state.immersivePayloadSource = normalizeSourceKey(source);
    applyPolicyPayload(payload);
    updateDashboardPayload(payload, source);
    state.selected = new Set();
    state.activeRowId = '';
    state.previewMode = 'selected';
    renderRows();
    renderSidePanel();
  }

  async function runNormalize() {
    const payload = await postJson('/api/movies/normalize', { source: el.sourcePath.value });
    state.normalizePayload = payload;
    markAuditLedgerDirty();
    state.selected = new Set();
    state.activeRowId = '';
    state.previewMode = 'selected';
    renderRows();
    renderSidePanel();
  }

  async function runWeakEncodes() {
    const source = el.sourcePath.value.trim();
    const payload = await postJson('/api/movies/profile', { source, weak_floor: state.weakFloor });
    state.weakPayload = payload;
    markAuditLedgerDirty();
    state.weakPayloadSource = normalizeSourceKey(source);
    applyPolicyPayload(payload);
    updateDashboardPayload(payload, source);
    state.selected = new Set();
    state.activeRowId = '';
    state.previewMode = 'selected';
    clearDeletePreviewState();
    renderRows();
    renderSidePanel();
  }

  async function runRepairDefaults() {
    const source = el.sourcePath.value.trim();
    const payload = await postJson('/api/movies/profile', { source });
    state.repairPayload = payload;
    markAuditLedgerDirty();
    state.repairPayloadSource = normalizeSourceKey(source);
    applyPolicyPayload(payload);
    updateDashboardPayload(payload, source);
    state.selected = new Set();
    state.activeRowId = '';
    state.previewMode = 'selected';
    state.repairActionNotice = '';
    clearDeletePreviewState();
    renderRows();
    renderSidePanel();
  }

  async function runJunk() {
    const payload = await postJson('/api/movies/junk', { source: el.sourcePath.value });
    state.junkPayload = payload;
    markAuditLedgerDirty();
    state.selected = new Set();
    state.activeRowId = '';
    state.previewMode = 'selected';
    clearDeletePreviewState();
    renderRows();
    renderSidePanel();
  }

  async function runCanonicalLists() {
    const source = el.sourcePath.value.trim();
    const requestedListId = state.canonicalSelectedListId || el.canonicalListFilter?.value || 'top_100';
    const payload = await postJson('/api/movies/canonical-lists', { source });
    state.canonicalPayload = payload;
    const lists = canonicalListsForPayload(payload);
    state.canonicalSelectedListId = lists.find(item => item.id === requestedListId)?.id
      || lists.find(item => item.id === 'top_100')?.id
      || lists.find(item => item.id === 'top_250')?.id
      || lists.find(item => item.id === 'top_500')?.id
      || lists[0]?.id
      || 'top_100';
    if (!state.canonicalProfilePayload || state.canonicalProfileSource !== source) {
      state.canonicalProfilePayload = await postJson('/api/movies/profile', { source });
    }
    state.canonicalProfileSource = normalizeSourceKey(source);
    applyPolicyPayload(state.canonicalProfilePayload);
    updateDashboardPayload(state.canonicalProfilePayload, source);
    state.selected = new Set();
    state.activeRowId = '';
    state.previewMode = 'selected';
    markAuditLedgerDirty();
    renderFilterVisibility();
    renderRows();
    renderSidePanel();
  }

  async function exportCatalogue() {
    const source = normalizeSourceKey(el.sourcePath.value);
    if (!source) throw new Error('Source path required for catalogue export.');
    state.catalogueExportInFlight = true;
    renderSidePanel();
    try {
      const response = await fetch('/api/movies/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source }),
      });
      if (!response.ok) {
        let message = '/api/movies/register failed';
        try {
          const payload = await response.json();
          message = payload.error || message;
        } catch {
          // Keep the fallback message when the response body is not JSON.
        }
        throw new Error(message);
      }
      const blob = await response.blob();
      const downloadUrl = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = downloadUrl;
      link.download = downloadFilenameFromDisposition(response.headers.get('Content-Disposition'));
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(downloadUrl);
      markAuditLedgerDirty();
    } finally {
      state.catalogueExportInFlight = false;
      renderSidePanel();
    }
  }

  async function runActiveWorkflow() {
    if (repairWorkflowBusy()) return;
    const surfaceDismissed = dismissActiveSurface();
    if (surfaceDismissed) {
      renderFilterVisibility();
      renderRows();
      renderSidePanel();
    }
    state.runInFlight = true;
    renderRunButton();
    try {
      if (isWeakMode()) await runWeakEncodes();
      else if (isRepairDefaultsMode()) await runRepairDefaults();
      else if (isCanonicalMode()) await runCanonicalLists();
      else if (isImmersiveMode()) await runImmersive();
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
        return !!movieAudioPackagingIssueCode(item) || movieSubtitleReadinessIsRepairable(item);
      }),
    };
  }

  async function deleteSelectedRepairAudio() {
    const paths = selectedRepairAudioPaths();
    if (!paths.length) return;
    state.applyInFlight = true;
    renderConfirmButton();
      try {
        const source = el.sourcePath.value.trim();
        const delResponse = await fetch('/api/movies/delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source, paths, issue_family: 'audio_packaging' }),
      });
      const delPayload = await delResponse.json();
      if (!delResponse.ok) throw new Error(delPayload.error || 'delete failed');
      state.repairPayload = removeWeakDeletedItems(state.repairPayload, delPayload.deleted || []);
      markAuditLedgerDirty();
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

  async function runAudioRepair(paths, action) {
    if (!paths.length) return;
    state.audioFixBusy = true;
    const dropForeignAudio = repairActionConfig(action).dropForeignAudio;
    state.repairActionNotice = dropForeignAudio
      ? `Running English-default remux and foreign-audio prune for ${paths.length} file${paths.length === 1 ? '' : 's'}.`
      : `Running English-default remux for ${paths.length} file${paths.length === 1 ? '' : 's'}.`;
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
      state.repairPayload = mergeUpdatedProfileItems(state.repairPayload, payload.updated_items || [], { dropResolved: true, action });
      markAuditLedgerDirty();
      state.repairActionNotice = dropForeignAudio
        ? `${payload.fixed?.length || 0} audio prune remux${(payload.fixed?.length || 0) === 1 ? '' : 's'} completed.`
        : `${payload.fixed?.length || 0} audio default${(payload.fixed?.length || 0) === 1 ? '' : 's'} repaired.`;
      renderRows();
      renderSidePanel();
      return payload;
    } catch (error) {
      state.repairActionNotice = error.message;
      renderRows();
      renderSidePanel();
      throw error;
    } finally {
      state.audioFixBusy = false;
      await refreshActivityPayload();
      renderRows();
      renderSidePanel();
    }
  }

  async function runSubtitleRepair(rows, action) {
    const paths = rows.map(row => row.path);
    if (!paths.length) return;
    const issueCodes = Object.fromEntries(rows.map(row => [row.path, row.subtitle_issue_code]));
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
      state.repairPayload = mergeUpdatedProfileItems(state.repairPayload, payload.updated_items || [], { dropResolved: true, action });
      markAuditLedgerDirty();
      state.repairActionNotice = `${payload.fixed?.length || 0} subtitle default${(payload.fixed?.length || 0) === 1 ? '' : 's'} repaired.`;
      renderRows();
      renderSidePanel();
      return payload;
    } catch (error) {
      state.repairActionNotice = error.message;
      renderRows();
      renderSidePanel();
      throw error;
    } finally {
      state.subtitleFixBusy = false;
      await refreshActivityPayload();
      renderRows();
      renderSidePanel();
    }
  }

  async function runCombinedRepair(paths, action) {
    if (!paths.length) return;
    state.audioFixBusy = true;
    state.subtitleFixBusy = true;
    const dropForeignAudio = repairActionConfig(action).dropForeignAudio;
    state.repairActionNotice = dropForeignAudio
      ? `Running single-pass audio, subtitle, and foreign-audio remux for ${paths.length} file${paths.length === 1 ? '' : 's'}.`
      : `Running single-pass audio and subtitle remux for ${paths.length} file${paths.length === 1 ? '' : 's'}.`;
    renderRows();
    renderSidePanel();
    try {
      const response = await fetch('/api/movies/repair-defaults/fix', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source: el.sourcePath.value.trim(),
          paths,
          include_audio: actionTouchesAudio(action),
          include_subtitle: actionTouchesSubtitle(action),
          drop_foreign_audio: dropForeignAudio,
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || 'repair defaults fix failed');
      state.repairPayload = mergeUpdatedProfileItems(state.repairPayload, payload.updated_items || [], { dropResolved: true, action });
      markAuditLedgerDirty();
      state.repairActionNotice = `${payload.fixed?.length || 0} combined repair remux${(payload.fixed?.length || 0) === 1 ? '' : 's'} completed.`;
      renderRows();
      renderSidePanel();
      return payload;
    } catch (error) {
      state.repairActionNotice = error.message;
      renderRows();
      renderSidePanel();
      throw error;
    } finally {
      state.audioFixBusy = false;
      state.subtitleFixBusy = false;
      await refreshActivityPayload();
      renderRows();
      renderSidePanel();
    }
  }

  function selectedSubtitleRowsFromPayload(selectedPaths) {
    const chosen = new Set(selectedPaths);
    return (state.repairPayload?.movies || [])
      .filter(item => chosen.has(item.path || '') && movieSubtitleReadinessIsRepairable(item))
      .map(repairRowForItem)
      .filter(row => rowTouchesFamily(row, 'subtitle'));
  }

  function confirmSafeRepairWarningGates(action, applicableRows) {
    if (currentWarningGateSafetyLevel() !== 'safe') return true;
    const count = applicableRows.length;
    if (!count) return false;
    // Dropping foreign audio is the sole trigger that turns a repair into a real
    // ffmpeg remux; every other action is a disposition flip routed through the
    // mkvpropedit fast lane (milliseconds, in place). Gate only the remux case.
    if (!repairActionConfig(action).dropForeignAudio) return true;
    const actionLabel = repairActionConfig(action).label.toLowerCase();
    const combinedSinglePass = combinedRepairRunsSingleRemux(action);
    const initialMessage = [
      combinedSinglePass
        ? 'This action plans the final audio/subtitle state first, then runs one lossless ffmpeg remux per selected movie.'
        : `This action runs ffmpeg remux workloads for each selected movie${actionTouchesSubtitle(action) ? ', including subtitle repair actions' : ''}.`,
      'These are larger and more CPU-intensive than the rest of the system.',
      'On a reasonable modern PC, expect roughly 1-10 minutes per movie depending on CPU speed and drive read/write bandwidth.',
      'Recommended starting posture: try single-file jobs until you are comfortable chaining repair actions together.',
      '',
      `Continue with ${actionLabel} for ${count} file${count === 1 ? '' : 's'}?`,
    ].join('\n');
    if (!window.confirm(initialMessage)) return false;
    if (count <= 3) return true;
    const queueMessage = [
      `You selected ${count} files.`,
      combinedSinglePass
        ? 'Each file will run as one lossless remux job, processed one file at a time.'
        : 'These remux jobs are queued and processed as a chain, one file at a time.',
      'The system will keep working through the selection until the queue is finished.',
      '',
      combinedSinglePass
        ? 'Continue with this multi-file remux run?'
        : 'Continue with this multi-file remux queue?',
    ].join('\n');
    return window.confirm(queueMessage);
  }

  async function runSelectedRepairAction(action) {
    const applicableRows = selectedRepairRowsForAction(action);
    const selectedPaths = applicableRows.map(row => row.path);
    if (!selectedPaths.length) return;
    if (!confirmSafeRepairWarningGates(action, applicableRows)) {
      state.repairActionNotice = 'Remux action canceled.';
      renderRows();
      renderSidePanel();
      return;
    }
    if (actionTouchesAudio(action) && actionTouchesSubtitle(action)) {
      await runCombinedRepair(selectedPaths, action);
    } else if (actionTouchesAudio(action)) {
      const audioPaths = applicableRows.filter(row => rowTouchesFamily(row, 'audio')).map(row => row.path);
      if (audioPaths.length) await runAudioRepair(audioPaths, action);
    } else if (actionTouchesSubtitle(action)) {
      const subtitleRows = selectedSubtitleRowsFromPayload(selectedPaths);
      if (subtitleRows.length) await runSubtitleRepair(subtitleRows, action);
    }
    state.previewMode = 'selected';
    renderRows();
    renderSidePanel();
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
          body: JSON.stringify({ source, paths, issue_family: 'weak_encode' }),
        });
        const delPayload = await delResponse.json();
        if (!delResponse.ok) throw new Error(delPayload.error || 'delete failed');
        state.weakPayload = removeWeakDeletedItems(state.weakPayload, delPayload.deleted || []);
        await refreshDashboardPayload(source, { weakFloor: state.weakFloor });
        markAuditLedgerDirty();
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
        await refreshDashboardPayload(source, { weakFloor: state.weakFloor });
        markAuditLedgerDirty();
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
      markAuditLedgerDirty();
      state.selected = new Set();
      state.activeRowId = '';
      state.previewMode = 'selected';
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
    dismissAuditSurface();
    state.workflow = ['weak-encodes', 'repair-defaults', 'canonical-lists', 'format-upgrades', 'junk'].includes(workflow) ? workflow : 'normalize';
    state.layoutMode = LAYOUT_MODES.default;
    state.surfaceMode = 'default';
    state.selected = new Set();
    state.activeRowId = '';
    state.previewMode = 'selected';
    state.repairAction = defaultRepairAction();
    state.repairActionNotice = '';
    state.sort = isCanonicalMode()
      ? { key: 'rank', dir: 'asc' }
      : (isImmersiveMode()
        ? { key: 'title', dir: 'asc' }
        : (isWeakMode()
          ? { key: 'triage', dir: 'desc' }
          : (usesSimpleSelectionShell() ? { key: 'current_path', dir: 'asc' } : { key: 'current_value', dir: 'asc' })));
    clearDeletePreviewState();
    closeTrackPopover();
    syncWorkflowUrl();
    renderWorkflowHeader();
    renderFilterVisibility();
    renderRunButton();
    renderTableHeader();
    renderRows();
    renderSidePanel();
  }

  async function refreshActivityPayload() {
    const source = normalizeSourceKey(el.sourcePath.value);
    if (!source) {
      state.activityPayload = null;
      state.activityRefreshInFlight = false;
      renderWorkflowHeader();
      renderRunButton();
      renderRows();
      renderSidePanel();
      return;
    }
    if (state.activityRefreshInFlight) return;
    state.activityRefreshInFlight = true;
    try {
      const response = await fetch(`/api/activity?source=${encodeURIComponent(source)}`);
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || 'activity read failed');
      state.activityPayload = payload;
    } catch (error) {
      state.activityPayload = null;
    } finally {
      state.activityRefreshInFlight = false;
      renderWorkflowHeader();
      renderRunButton();
      renderRows();
      renderSidePanel();
    }
  }

  function scheduleActivityPoll() {
    if (state.activityPollTimer) window.clearTimeout(state.activityPollTimer);
    state.activityPollTimer = window.setTimeout(async () => {
      state.activityPollTimer = 0;
      await refreshActivityPayload();
      scheduleActivityPoll();
    }, ACTIVITY_POLL_MS);
  }

  el.workflowButton.addEventListener('click', () => {
    if (repairWorkflowBusy()) return;
    const open = el.workflowMenu.hidden;
    el.workflowMenu.hidden = !open;
    el.workflowButton.setAttribute('aria-expanded', open ? 'true' : 'false');
  });

  [el.workflowNormalize, el.workflowWeakEncodes, el.workflowRepairDefaults, el.workflowCanonicalLists, el.workflowImmersive, el.workflowJunk].forEach(button => {
    button.addEventListener('click', async () => {
      if (repairWorkflowBusy()) return;
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
      el.trackPopover
      && !el.trackPopover.hidden
      && !el.trackPopover.contains(event.target)
      && !(event.target instanceof Element && event.target.closest('button[data-track-popover]'))
    ) {
      closeTrackPopover();
    }
    if (
      state.onboardingVisible
      && event.target instanceof Element
      && event.target.id === 'onboardingGateBackdrop'
    ) {
      hideOnboardingGate({ remember: true });
    }
  });

  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') closeTrackPopover();
    if (event.key === 'Escape' && state.onboardingVisible) hideOnboardingGate({ remember: true });
  });

  window.addEventListener('resize', () => {
    if (state.trackPopoverRowId) renderTrackPopover();
    updateRepairLockOverlay();
  });

  window.addEventListener('scroll', () => {
    if (state.trackPopoverRowId) renderTrackPopover();
    updateRepairLockOverlay();
  }, true);

  [el.searchInput, el.bucketFilter, el.workflowStatusFilter, el.canonicalListFilter, el.traitFilter, el.traitStatusFilter].forEach(control => {
    control.addEventListener('change', async () => {
      if (control === el.canonicalListFilter) {
        state.canonicalSelectedListId = el.canonicalListFilter.value || 'top_100';
      }
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
    state.previewMode = 'selected';
    state.repairActionNotice = '';
    clearDeletePreviewState();
    renderFilterVisibility();
    renderTableHeader();
    renderRows();
    renderSidePanel();
  });

  el.repairActionButton.addEventListener('click', () => {
    const action = el.repairActionSelect.value || defaultRepairAction();
    const request = runSelectedRepairAction(action);
    request.catch(error => {
      el.previewPane.textContent = error.message;
    });
  });

  if (el.dashboardToggle) {
    el.dashboardToggle.addEventListener('click', () => {
      state.surfaceMode = dashboardSurfaceOpen() ? 'default' : 'dashboard';
      renderFilterVisibility();
      renderRows();
      renderSidePanel();
    });
  }

  renderWorkflowHeader();
  renderFilterVisibility();
  renderRunButton();
  renderTableHeader();
  renderSelectionButtons();
  renderPanelVisibility();
  renderSidePanel();
  syncWorkflowUrl();
  showOnboardingGate();

  el.policyToggle.addEventListener('click', () => {
    togglePolicyEditor().catch(handlePolicyToggleError);
  });

  if (el.settingsToggle) {
    el.settingsToggle.addEventListener('click', () => {
      toggleSettings().catch(handlePolicyToggleError);
    });
  }

  el.auditToggle.addEventListener('click', () => {
    (async () => {
      if (auditSurfaceOpen()) {
        state.surfaceMode = 'default';
        closeAuditEventSource();
      } else {
        state.surfaceMode = 'audit';
        await refreshAuditPayload({ immediate: true });
      }
      renderFilterVisibility();
      renderRows();
      renderSidePanel();
    })().catch(handlePolicyToggleError);
  });

  el.runButton.addEventListener('click', () => {
    if (repairWorkflowBusy()) return;
    runActiveWorkflow().catch(error => {
      el.previewPane.textContent = error.message;
    });
  });

  el.sourcePath.addEventListener('input', () => {
    state.auditPayload = null;
    state.auditNeedsRefresh = false;
    state.auditRefreshInFlight = false;
    state.auditBusy = false;
    state.auditSignature = '';
    state.activityPayload = null;
    closeAuditEventSource();
    refreshActivityPayload().catch(() => {});
    scheduleActivityPoll();
    renderSidePanel();
    if (auditSurfaceOpen() && auditSourceKey()) {
      refreshAuditPayload({ immediate: true }).catch(error => {
        el.inspectionPane.textContent = error.message;
      });
    }
  });

  if (el.placeholderDownloadToggle) {
    el.placeholderDownloadToggle.addEventListener('click', () => {
      exportCatalogue().catch(error => {
        el.previewPane.textContent = error.message;
      });
    });
  }

  el.confirmButton.addEventListener('click', () => {
    confirmSelected().catch(error => {
      el.previewPane.textContent = error.message;
    });
  });

  if (el.onboardingGateClose) {
    el.onboardingGateClose.addEventListener('click', () => {
      hideOnboardingGate({ remember: true });
    });
  }

  (async () => {
    try {
      await ensurePolicyPayload();
      if (!normalizeSourceKey(el.sourcePath.value)) {
        const startupSource = preferredDefaultSource();
        if (startupSource) el.sourcePath.value = startupSource;
      }
      await refreshActivityPayload();
      scheduleActivityPoll();
      if (normalizeSourceKey(el.sourcePath.value)) {
        state.surfaceMode = 'audit';
        await refreshAuditPayload({ immediate: true });
      }
    } catch (error) {
      el.inspectionPane.textContent = error.message;
    } finally {
      renderFilterVisibility();
      renderRows();
      renderSidePanel();
    }
  })();
})();
